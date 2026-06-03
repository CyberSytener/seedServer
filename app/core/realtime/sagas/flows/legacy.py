from __future__ import annotations
import logging

import asyncio
import inspect
import time
from typing import Any, Dict, List, Optional

from app.core.realtime.engine import (
    BaseSaga,
    CircuitBreakerOpenError,
    RETRY_CONFIGS,
    SagaState,
    SagaStepRecord,
    StepStatus,
    retry_with_backoff,
)


class BookingFlow(BaseSaga):
    saga_type = "booking_flow"

    async def run(
        self,
        saga_id: str,
        payload: Dict[str, Any],
        steps: List[Dict[str, Any]],
        correlation_id: Optional[str] = None,
        trace_id: Optional[str] = None,
    ):
        """Execute booking saga: reserve → confirm → finalize (with circuit breaker + retry)."""
        try:
            # Step 1: Reserve slot (with circuit breaker + retry)
            self.logger.info(f"📌 Step 1: Reserving slot for saga {saga_id} [correlation: {correlation_id}]")
            step = SagaStepRecord(
                name="reserve_slot",
                status=StepStatus.IN_PROGRESS.value,
                adapter_type="booking",
                compensatable=True,
            )
            steps.append(step.to_dict())

            adapter = self.adapters.get("booking")
            if not adapter:
                raise ValueError("booking adapter not registered")

            # Get circuit breaker
            circuit_breaker = self._get_circuit_breaker("booking")

            # Check circuit breaker
            if not circuit_breaker.can_execute():
                raise CircuitBreakerOpenError("Booking adapter circuit breaker is OPEN")

            trace_context = self._ensure_trace_context(
                saga_id=saga_id,
                saga_type="booking_flow",
                action_id=None,
                user_id=None,
                correlation_id=correlation_id,
                trace_id=trace_id,
            )

            # Execute with retry
            start_time = time.time()
            try:
                span_id = self.telemetry_collector.start_adapter_call(
                    trace_context.get("root_span_id"),
                    "booking",
                    "reserve",
                    payload_size=self._safe_payload_size(payload),
                    trace_id=trace_context.get("trace_id"),
                    saga_id=saga_id,
                    correlation_id=trace_context.get("correlation_id"),
                )
                reserve_res = await retry_with_backoff(
                    func=lambda: self._call_adapter_method(
                        adapter,
                        "reserve",
                        payload,
                        trace_context=trace_context,
                    ),
                    config=self.retry_config,
                    operation_name="booking.reserve",
                    logger_instance=self.logger,
                )
                circuit_breaker.record_success()
                self.telemetry_collector.end_span(span_id, status="OK")
            except Exception as e:
                await circuit_breaker.record_failure()
                if "span_id" in locals():
                    self.telemetry_collector.end_span(span_id, status="ERROR", error=str(e))
                raise

            duration_ms = int((time.time() - start_time) * 1000)

            # Update step
            steps[-1]["status"] = StepStatus.SUCCEEDED.value
            steps[-1]["meta"] = reserve_res
            steps[-1]["duration_ms"] = duration_ms

            await self._update_saga_state(saga_id, SagaState.IN_PROGRESS.value, steps=steps)

            # Step 2: Wait for user confirmation
            self.logger.info(f"⏳ Step 2: Waiting for user confirmation for saga {saga_id}")
            step = SagaStepRecord(name="await_user_confirm", status=StepStatus.PENDING.value)
            steps.append(step.to_dict())

            # Pause saga at this point
            await self._update_saga_state(
                saga_id,
                SagaState.WAITING_CONFIRM.value,
                steps=steps,
                result={"reservation": reserve_res},
            )

            self.logger.info(f"⏳ Saga paused at confirmation: {saga_id}")

        except CircuitBreakerOpenError as e:
            self.logger.error(f"🔴 Circuit breaker open for booking adapter: {saga_id}")
            step = SagaStepRecord(
                name="reserve_slot",
                status=StepStatus.FAILED.value,
                error=str(e),
            )
            steps.append(step.to_dict())

            await self._update_saga_state(
                saga_id,
                SagaState.FAILED.value,
                steps=steps,
                result={"error": str(e), "circuit_breaker": "open"},
            )

        except Exception as e:
            self.logger.exception(f"❌ Booking flow failed: {saga_id}")
            await self._attempt_compensation(saga_id, "booking_flow", payload, steps, e)
            step = SagaStepRecord(
                name="reserve_slot",
                status=StepStatus.FAILED.value,
                error=str(e),
            )
            steps.append(step.to_dict())

            await self._update_saga_state(
                saga_id,
                SagaState.FAILED.value,
                steps=steps,
                result={"error": str(e)},
            )

    async def resume(
        self,
        *,
        saga_id: str,
        saga: Dict[str, Any],
        steps: List[Dict[str, Any]],
        confirm_payload: Dict[str, Any],
        trace_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Resume booking saga after user confirmation."""
        try:
            trace_context = trace_context or (
                self._active_traces.get(saga_id)
                or self._resolve_trace_context_from_steps(steps)
                or self._ensure_trace_context(
                    saga_id=saga_id,
                    saga_type=saga.get("saga_type"),
                    action_id=saga.get("action_id"),
                    user_id=saga.get("user_id"),
                    correlation_id=saga.get("correlation_id"),
                    trace_id=None,
                )
            )

            try:
                # Step 3: Confirm booking via adapter (with circuit breaker + retry)
                self.logger.info(f"✅ Confirming booking for saga {saga_id}")
                step = SagaStepRecord(
                    name="confirm_booking",
                    status=StepStatus.IN_PROGRESS.value,
                    adapter_type="booking",
                    compensatable=False,
                )
                steps.append(step.to_dict())

                adapter = self.adapters.get("booking")
                if not adapter:
                    raise ValueError("booking adapter not registered")

                circuit_breaker = self._get_circuit_breaker("booking")

                # Check circuit breaker
                if not circuit_breaker.can_execute():
                    raise CircuitBreakerOpenError("Booking adapter circuit breaker is OPEN")

                # Pre-populate reservation info in adapter store
                try:
                    for s in steps:
                        if s.get("name") == "reserve_slot" and s.get("meta") and s["meta"].get("reservation_id"):
                            res_meta = s["meta"]
                            reservation_id = res_meta.get("reservation_id")
                            if adapter and hasattr(adapter, "reservations"):
                                adapter.reservations[reservation_id] = {
                                    "status": res_meta.get("status", "pending"),
                                    "payload": saga["payload"],
                                    "created_at": res_meta.get("created_at"),
                                }
                except Exception:
                    logging.debug("Suppressed exception", exc_info=True)
                # Execute with retry
                start_time = time.time()
                try:
                    span_id = self.telemetry_collector.start_adapter_call(
                        trace_context.get("root_span_id"),
                        "booking",
                        "confirm",
                        payload_size=self._safe_payload_size(confirm_payload),
                        trace_id=trace_context.get("trace_id"),
                        saga_id=saga_id,
                        correlation_id=trace_context.get("correlation_id"),
                    )
                    confirm_res = await retry_with_backoff(
                        func=lambda: self._call_adapter_method(
                            adapter,
                            "confirm",
                            saga["payload"],
                            confirm_payload,
                            trace_context=trace_context,
                        ),
                        config=self.retry_config,
                        operation_name="booking.confirm",
                        logger_instance=self.logger,
                    )
                    circuit_breaker.record_success()
                    self.telemetry_collector.end_span(span_id, status="OK")
                except Exception as e:
                    await circuit_breaker.record_failure()
                    if "span_id" in locals():
                        self.telemetry_collector.end_span(span_id, status="ERROR", error=str(e))
                    raise

                duration_ms = int((time.time() - start_time) * 1000)

                steps[-1]["status"] = StepStatus.SUCCEEDED.value
                steps[-1]["meta"] = confirm_res
                steps[-1]["duration_ms"] = duration_ms

                await self._update_saga_state(
                    saga_id,
                    SagaState.SUCCEEDED.value,
                    steps=steps,
                    result={"confirmation": confirm_res},
                )

                self.logger.info(f"✅ Saga succeeded: {saga_id}")
                return {"status": "succeeded", "result": confirm_res}

            except CircuitBreakerOpenError as confirm_error:
                self.logger.error(f"🔴 Circuit breaker open during confirmation: {saga_id}")

                # Don't compensate on circuit breaker open (may recover)
                return {
                    "status": "failed",
                    "error": str(confirm_error),
                    "circuit_breaker": "open",
                    "compensated": False,
                }

            except Exception as confirm_error:
                self.logger.error(f"❌ Confirmation failed for saga {saga_id}: {confirm_error}")

                # Trigger compensation
                await self._compensate_saga(saga_id, saga, steps, confirm_error)

                return {
                    "status": "failed",
                    "error": str(confirm_error),
                    "compensated": True,
                }

        except Exception as e:
            self.logger.exception(f"❌ Resume failed: {saga_id}")
            return {"status": "error", "error": str(e)}


class CalendarFlow(BaseSaga):
    saga_type = "calendar_flow"

    async def run(
        self,
        saga_id: str,
        payload: Dict[str, Any],
        steps: List[Dict[str, Any]],
        correlation_id: Optional[str] = None,
        trace_id: Optional[str] = None,
    ):
        """Execute calendar saga: create event → send invites (with circuit breaker + retry)."""
        try:
            # Step 1: Create calendar event
            self.logger.info(f"📅 Step 1: Creating calendar event for saga {saga_id} [correlation: {correlation_id}]")
            step = SagaStepRecord(
                name="create_event",
                status=StepStatus.IN_PROGRESS.value,
                adapter_type="calendar",
                compensatable=True,
            )
            steps.append(step.to_dict())

            adapter = self.adapters.get("calendar")
            if not adapter:
                raise ValueError("calendar adapter not registered")

            circuit_breaker = self._get_circuit_breaker("calendar")

            # Check circuit breaker
            if not circuit_breaker.can_execute():
                raise CircuitBreakerOpenError("Calendar adapter circuit breaker is OPEN")

            trace_context = self._ensure_trace_context(
                saga_id=saga_id,
                saga_type="calendar_flow",
                action_id=None,
                user_id=None,
                correlation_id=correlation_id,
                trace_id=trace_id,
            )

            # Execute with retry
            start_time = time.time()
            try:
                span_id = self.telemetry_collector.start_adapter_call(
                    trace_context.get("root_span_id"),
                    "calendar",
                    "create",
                    payload_size=self._safe_payload_size(payload),
                    trace_id=trace_context.get("trace_id"),
                    saga_id=saga_id,
                    correlation_id=trace_context.get("correlation_id"),
                )
                event_res = await retry_with_backoff(
                    func=lambda: self._call_adapter_method(
                        adapter,
                        "create",
                        payload,
                        trace_context=trace_context,
                    ),
                    config=self.retry_config,
                    operation_name="calendar.create",
                    logger_instance=self.logger,
                )
                circuit_breaker.record_success()
                self.telemetry_collector.end_span(span_id, status="OK")
            except Exception as e:
                await circuit_breaker.record_failure()
                if "span_id" in locals():
                    self.telemetry_collector.end_span(span_id, status="ERROR", error=str(e))
                raise

            duration_ms = int((time.time() - start_time) * 1000)

            steps[-1]["status"] = StepStatus.SUCCEEDED.value
            steps[-1]["meta"] = event_res
            steps[-1]["duration_ms"] = duration_ms

            # No confirmation needed for calendar; auto-finalize
            await self._update_saga_state(
                saga_id,
                SagaState.SUCCEEDED.value,
                steps=steps,
                result={"event": event_res},
            )

            self.logger.info(f"✅ Calendar saga succeeded: {saga_id}")

        except CircuitBreakerOpenError as e:
            self.logger.error(f"🔴 Circuit breaker open for calendar adapter: {saga_id}")
            steps.append(SagaStepRecord(
                name="create_event",
                status=StepStatus.FAILED.value,
                error=str(e),
            ).to_dict())

            await self._update_saga_state(
                saga_id,
                SagaState.FAILED.value,
                steps=steps,
                result={"error": str(e), "circuit_breaker": "open"},
            )

        except Exception as e:
            self.logger.exception(f"❌ Calendar flow failed: {saga_id}")
            await self._attempt_compensation(saga_id, "calendar_flow", payload, steps, e)
            steps.append(SagaStepRecord(
                name="create_event",
                status=StepStatus.FAILED.value,
                error=str(e),
            ).to_dict())

            await self._update_saga_state(
                saga_id,
                SagaState.FAILED.value,
                steps=steps,
                result={"error": str(e)},
            )


class CVGenerationFlow(BaseSaga):
    saga_type = "cv_generation"

    async def run(
        self,
        saga_id: str,
        payload: Dict[str, Any],
        steps: List[Dict[str, Any]],
        correlation_id: Optional[str] = None,
        trace_id: Optional[str] = None,
    ):
        """Execute CV generation saga: parse input → generate CV."""
        try:
            self.logger.info(f"🧾 Step 1: Generating CV for saga {saga_id} [correlation: {correlation_id}]")
            step = SagaStepRecord(
                name="generate_cv",
                status=StepStatus.IN_PROGRESS.value,
                adapter_type="cv",
                compensatable=True,
            )
            steps.append(step.to_dict())

            adapter = self.adapters.get("cv") or self.adapters.get("cv_processor")
            if not adapter:
                raise ValueError("cv adapter not registered")

            request_payload = payload.get("request") or payload.get("cv_request") or payload

            trace_context = self._ensure_trace_context(
                saga_id=saga_id,
                saga_type="cv_generation",
                action_id=None,
                user_id=None,
                correlation_id=correlation_id,
                trace_id=trace_id,
            )

            async def _call_generate():
                if hasattr(adapter, "generate_cv"):
                    try:
                        from app.core.realtime.optimized.cv_contracts import CVGenerationRequest
                        if isinstance(request_payload, dict):
                            request_obj = CVGenerationRequest(**request_payload)
                        else:
                            request_obj = request_payload
                    except Exception:
                        request_obj = request_payload
                    return await self._call_adapter_method(
                        adapter,
                        "generate_cv",
                        request_obj,
                        trace_context=trace_context,
                    )
                if hasattr(adapter, "create_cv"):
                    return await self._call_adapter_method(
                        adapter,
                        "create_cv",
                        request_payload,
                        trace_context=trace_context,
                    )
                raise ValueError("cv adapter does not support generate_cv/create_cv")

            start_time = time.time()
            span_id = self.telemetry_collector.start_adapter_call(
                trace_context.get("root_span_id"),
                "cv",
                "generate",
                payload_size=self._safe_payload_size(request_payload),
                trace_id=trace_context.get("trace_id"),
                saga_id=saga_id,
                correlation_id=trace_context.get("correlation_id"),
            )
            try:
                result = await retry_with_backoff(
                    func=_call_generate,
                    config=self.retry_config,
                    operation_name="cv.generate",
                    logger_instance=self.logger,
                )
                self.telemetry_collector.end_span(span_id, status="OK")
            except Exception as e:
                self.telemetry_collector.end_span(span_id, status="ERROR", error=str(e))
                raise
            duration_ms = int((time.time() - start_time) * 1000)

            if hasattr(result, "model_dump"):
                result_payload = result.model_dump()
            else:
                result_payload = result

            steps[-1]["status"] = StepStatus.SUCCEEDED.value
            steps[-1]["meta"] = {"duration_ms": duration_ms}
            steps[-1]["duration_ms"] = duration_ms

            await self._update_saga_state(
                saga_id,
                SagaState.SUCCEEDED.value,
                steps=steps,
                result={"cv": result_payload},
            )

        except Exception as e:
            self.logger.exception(f"❌ CV generation flow failed: {saga_id}")
            await self._attempt_compensation(saga_id, "cv_generation", payload, steps, e)
            step = SagaStepRecord(
                name="generate_cv",
                status=StepStatus.FAILED.value,
                error=str(e),
            )
            steps.append(step.to_dict())

            await self._update_saga_state(
                saga_id,
                SagaState.FAILED.value,
                steps=steps,
                result={"error": str(e)},
            )


class LearningPlanFlow(BaseSaga):
    saga_type = "learning_plan"

    async def run(
        self,
        saga_id: str,
        payload: Dict[str, Any],
        steps: List[Dict[str, Any]],
        correlation_id: Optional[str] = None,
        trace_id: Optional[str] = None,
    ):
        """Execute learning plan generation saga."""
        try:
            self.logger.info(f"📚 Step 1: Generating learning plan for saga {saga_id} [correlation: {correlation_id}]")
            step = SagaStepRecord(
                name="generate_learning_plan",
                status=StepStatus.IN_PROGRESS.value,
                adapter_type="learning_plan",
                compensatable=True,
            )
            steps.append(step.to_dict())

            adapter = self.adapters.get("learning_plan") or self.adapters.get("lesson_plan")
            if not adapter:
                raise ValueError("learning_plan adapter not registered")

            request_payload = payload.get("request") or payload.get("plan_request") or payload

            trace_context = self._ensure_trace_context(
                saga_id=saga_id,
                saga_type="learning_plan",
                action_id=None,
                user_id=None,
                correlation_id=correlation_id,
                trace_id=trace_id,
            )

            async def _call_generate():
                if hasattr(adapter, "generate_learning_plan"):
                    return await self._call_adapter_method(
                        adapter,
                        "generate_learning_plan",
                        request_payload,
                        trace_context=trace_context,
                    )
                if hasattr(adapter, "generate_plan"):
                    return await self._call_adapter_method(
                        adapter,
                        "generate_plan",
                        request_payload,
                        trace_context=trace_context,
                    )
                if callable(adapter):
                    kwargs: Dict[str, Any] = {}
                    try:
                        signature = inspect.signature(adapter)
                        params = signature.parameters
                        if "trace_context" in params:
                            kwargs["trace_context"] = trace_context
                        if "trace_id" in params:
                            kwargs["trace_id"] = trace_context.get("trace_id")
                        if "correlation_id" in params:
                            kwargs["correlation_id"] = trace_context.get("correlation_id")
                    except (TypeError, ValueError):
                        pass
                    result = adapter(request_payload, **kwargs)
                    if asyncio.iscoroutine(result):
                        return await result
                    return result
                raise ValueError("learning_plan adapter does not support generate_learning_plan/generate_plan")

            start_time = time.time()
            span_id = self.telemetry_collector.start_adapter_call(
                trace_context.get("root_span_id"),
                "learning_plan",
                "generate",
                payload_size=self._safe_payload_size(request_payload),
                trace_id=trace_context.get("trace_id"),
                saga_id=saga_id,
                correlation_id=trace_context.get("correlation_id"),
            )
            try:
                result = await retry_with_backoff(
                    func=_call_generate,
                    config=self.retry_config,
                    operation_name="learning_plan.generate",
                    logger_instance=self.logger,
                )
                self.telemetry_collector.end_span(span_id, status="OK")
            except Exception as e:
                self.telemetry_collector.end_span(span_id, status="ERROR", error=str(e))
                raise
            duration_ms = int((time.time() - start_time) * 1000)

            if hasattr(result, "model_dump"):
                result_payload = result.model_dump()
            else:
                result_payload = result

            steps[-1]["status"] = StepStatus.SUCCEEDED.value
            steps[-1]["meta"] = {"duration_ms": duration_ms}
            steps[-1]["duration_ms"] = duration_ms

            await self._update_saga_state(
                saga_id,
                SagaState.SUCCEEDED.value,
                steps=steps,
                result={"learning_plan": result_payload},
            )

        except Exception as e:
            self.logger.exception(f"❌ Learning plan flow failed: {saga_id}")
            await self._attempt_compensation(saga_id, "learning_plan", payload, steps, e)
            step = SagaStepRecord(
                name="generate_learning_plan",
                status=StepStatus.FAILED.value,
                error=str(e),
            )
            steps.append(step.to_dict())

            await self._update_saga_state(
                saga_id,
                SagaState.FAILED.value,
                steps=steps,
                result={"error": str(e)},
            )


class CareerGrowthFlow(BaseSaga):
    saga_type = "career_growth_flow"

    async def run(
        self,
        saga_id: str,
        payload: Dict[str, Any],
        steps: List[Dict[str, Any]],
        correlation_id: Optional[str] = None,
        trace_id: Optional[str] = None,
    ):
        """Execute career growth saga: validate profile → generate CV → discover jobs → generate lessons → outreach."""
        try:
            trace_context = self._ensure_trace_context(
                saga_id=saga_id,
                saga_type="career_growth_flow",
                action_id=None,
                user_id=payload.get("user_id"),
                correlation_id=correlation_id,
                trace_id=trace_id,
            )

            # Step 0: Validate user profile
            self.logger.info(f"🧭 Step 0: Validating profile for saga {saga_id} [correlation: {correlation_id}]")
            step = SagaStepRecord(
                name="validate_profile",
                status=StepStatus.IN_PROGRESS.value,
            )
            steps.append(step.to_dict())

            start_time = time.time()
            persona = payload.get("user_persona") or payload.get("persona") or {}
            work_history = (
                persona.get("work_history")
                or persona.get("workHistory")
                or payload.get("work_history")
                or payload.get("workHistory")
            )
            if not work_history:
                raise ValueError("UserPersona missing work history")
            validate_duration_ms = int((time.time() - start_time) * 1000)

            steps[-1]["status"] = StepStatus.SUCCEEDED.value
            steps[-1]["meta"] = {
                "work_history_count": len(work_history) if isinstance(work_history, list) else 1,
                "duration_ms": validate_duration_ms,
            }
            steps[-1]["duration_ms"] = validate_duration_ms

            # Step 1: Generate CV
            self.logger.info(f"🧾 Step 1: Generating CV for saga {saga_id} [correlation: {correlation_id}]")
            step = SagaStepRecord(
                name="generate_cv",
                status=StepStatus.IN_PROGRESS.value,
                adapter_type="cv",
                compensatable=True,
            )
            steps.append(step.to_dict())

            cv_adapter = self.adapters.get("cv") or self.adapters.get("cv_processor")
            if not cv_adapter:
                raise ValueError("cv adapter not registered")

            cv_payload = payload.get("cv_request") or payload.get("request") or payload

            async def _call_cv():
                if hasattr(cv_adapter, "generate_cv"):
                    try:
                        from app.core.realtime.optimized.cv_contracts import CVGenerationRequest
                        if isinstance(cv_payload, dict):
                            request_obj = CVGenerationRequest(**cv_payload)
                        else:
                            request_obj = cv_payload
                    except Exception:
                        request_obj = cv_payload
                    return await self._call_adapter_method(
                        cv_adapter,
                        "generate_cv",
                        request_obj,
                        trace_context=trace_context,
                    )
                if hasattr(cv_adapter, "create_cv"):
                    return await self._call_adapter_method(
                        cv_adapter,
                        "create_cv",
                        cv_payload,
                        trace_context=trace_context,
                    )
                raise ValueError("cv adapter does not support generate_cv/create_cv")

            start_time = time.time()
            cv_span_id = self.telemetry_collector.start_adapter_call(
                trace_context.get("root_span_id"),
                "cv",
                "generate",
                payload_size=self._safe_payload_size(cv_payload),
                trace_id=trace_context.get("trace_id"),
                saga_id=saga_id,
                correlation_id=trace_context.get("correlation_id"),
            )
            try:
                cv_result = await retry_with_backoff(
                    func=_call_cv,
                    config=self.retry_config,
                    operation_name="career_growth.cv.generate",
                    logger_instance=self.logger,
                )
                self.telemetry_collector.end_span(cv_span_id, status="OK")
            except Exception as e:
                self.telemetry_collector.end_span(cv_span_id, status="ERROR", error=str(e))
                raise
            cv_duration_ms = int((time.time() - start_time) * 1000)

            cv_payload_out = cv_result.model_dump() if hasattr(cv_result, "model_dump") else cv_result
            steps[-1]["status"] = StepStatus.SUCCEEDED.value
            steps[-1]["meta"] = {"duration_ms": cv_duration_ms}
            steps[-1]["duration_ms"] = cv_duration_ms

            # Step 2: Discover jobs
            self.logger.info(f"🔍 Step 2: Discovering jobs for saga {saga_id} [correlation: {correlation_id}]")
            step = SagaStepRecord(
                name="discover_jobs",
                status=StepStatus.IN_PROGRESS.value,
                adapter_type="job_search",
                compensatable=False,
            )
            steps.append(step.to_dict())

            job_adapter = (
                self.adapters.get("job_search")
                or self.adapters.get("job_discovery")
                or self.adapters.get("job_scraper")
            )
            if not job_adapter:
                raise ValueError("job search adapter not registered")

            job_query = payload.get("target_role") or payload.get("job_title") or ""
            location = payload.get("location") or ""
            job_payload = payload.get("job_search_request") or {
                "query": job_query,
                "location": location,
                "limit": payload.get("limit", 5),
            }

            async def _call_job_search():
                if hasattr(job_adapter, "search_jobs"):
                    return await self._call_adapter_method(
                        job_adapter,
                        "search_jobs",
                        job_payload,
                        trace_context=trace_context,
                    )
                if hasattr(job_adapter, "discover_jobs"):
                    return await self._call_adapter_method(
                        job_adapter,
                        "discover_jobs",
                        job_payload,
                        trace_context=trace_context,
                    )
                if hasattr(job_adapter, "search"):
                    return await self._call_adapter_method(
                        job_adapter,
                        "search",
                        job_payload,
                        trace_context=trace_context,
                    )
                raise ValueError("job search adapter does not support search_jobs/discover_jobs")

            start_time = time.time()
            jobs_span_id = self.telemetry_collector.start_adapter_call(
                trace_context.get("root_span_id"),
                "job_search",
                "discover",
                payload_size=self._safe_payload_size(job_payload),
                trace_id=trace_context.get("trace_id"),
                saga_id=saga_id,
                correlation_id=trace_context.get("correlation_id"),
            )
            try:
                job_result = await retry_with_backoff(
                    func=_call_job_search,
                    config=self.retry_config,
                    operation_name="career_growth.job_search",
                    logger_instance=self.logger,
                )
                self.telemetry_collector.end_span(jobs_span_id, status="OK")
            except Exception as e:
                self.telemetry_collector.end_span(jobs_span_id, status="ERROR", error=str(e))
                raise
            jobs_duration_ms = int((time.time() - start_time) * 1000)

            vacancies = job_result.get("vacancies") if isinstance(job_result, dict) else job_result
            vacancies = vacancies or []

            steps[-1]["status"] = StepStatus.SUCCEEDED.value
            steps[-1]["meta"] = {
                "job_count": len(vacancies),
                "duration_ms": jobs_duration_ms,
            }
            steps[-1]["duration_ms"] = jobs_duration_ms

            # Step 3: Generate learning path / lessons (based on vacancies)
            self.logger.info(f"📚 Step 3: Generating lessons for saga {saga_id} [correlation: {correlation_id}]")
            step = SagaStepRecord(
                name="generate_learning_path",
                status=StepStatus.IN_PROGRESS.value,
                adapter_type="career_education",
                compensatable=True,
            )
            steps.append(step.to_dict())

            education_adapter = (
                self.adapters.get("career_education")
                or self.adapters.get("edu_service")
                or self.adapters.get("learning_plan")
            )
            if not education_adapter:
                raise ValueError("education adapter not registered")

            education_payload = payload.get("education_request") or {}
            if isinstance(education_payload, dict):
                education_payload = {
                    **payload,
                    **education_payload,
                    "vacancies": vacancies,
                }
            else:
                education_payload = {"payload": education_payload, "vacancies": vacancies}

            async def _call_education():
                if hasattr(education_adapter, "generate_lessons"):
                    return await self._call_adapter_method(
                        education_adapter,
                        "generate_lessons",
                        education_payload,
                        trace_context=trace_context,
                    )
                if hasattr(education_adapter, "generate_learning_path"):
                    return await self._call_adapter_method(
                        education_adapter,
                        "generate_learning_path",
                        education_payload,
                        trace_context=trace_context,
                    )
                if hasattr(education_adapter, "generate_learning_plan"):
                    return await self._call_adapter_method(
                        education_adapter,
                        "generate_learning_plan",
                        education_payload,
                        trace_context=trace_context,
                    )
                if hasattr(education_adapter, "generate_plan"):
                    return await self._call_adapter_method(
                        education_adapter,
                        "generate_plan",
                        education_payload,
                        trace_context=trace_context,
                    )
                raise ValueError("education adapter does not support lesson generation")

            start_time = time.time()
            edu_span_id = self.telemetry_collector.start_adapter_call(
                trace_context.get("root_span_id"),
                "career_education",
                "generate",
                payload_size=self._safe_payload_size(education_payload),
                trace_id=trace_context.get("trace_id"),
                saga_id=saga_id,
                correlation_id=trace_context.get("correlation_id"),
            )
            try:
                education_result = await retry_with_backoff(
                    func=_call_education,
                    config=RETRY_CONFIGS.get("reserve", self.retry_config),
                    operation_name="career_growth.education.generate",
                    logger_instance=self.logger,
                )
                self.telemetry_collector.end_span(edu_span_id, status="OK")
            except Exception as e:
                self.telemetry_collector.end_span(edu_span_id, status="ERROR", error=str(e))
                raise
            edu_duration_ms = int((time.time() - start_time) * 1000)

            education_payload_out = (
                education_result.model_dump()
                if hasattr(education_result, "model_dump")
                else education_result
            )
            steps[-1]["status"] = StepStatus.SUCCEEDED.value
            steps[-1]["meta"] = {"duration_ms": edu_duration_ms}
            steps[-1]["duration_ms"] = edu_duration_ms

            # Step 4: Apply for jobs (outreach only)
            self.logger.info(f"📨 Step 4: Applying for jobs for saga {saga_id} [correlation: {correlation_id}]")
            step = SagaStepRecord(
                name="apply_for_jobs",
                status=StepStatus.IN_PROGRESS.value,
                adapter_type="email_outreach",
                compensatable=False,
            )
            steps.append(step.to_dict())

            outreach_adapter = (
                self.adapters.get("email_outreach")
                or self.adapters.get("outreach_service")
                or self.adapters.get("email")
            )
            if not outreach_adapter:
                raise ValueError("email outreach adapter not registered")

            outreach_results = []
            outreach_start = time.time()
            try:
                for vacancy in vacancies:
                    title = vacancy.get("title") or "Job Opportunity"
                    company = vacancy.get("company") or ""
                    to_email = vacancy.get("contact_email") or payload.get("default_contact_email")
                    if not to_email:
                        outreach_results.append({
                            "status": "skipped",
                            "reason": "missing_recipient",
                            "title": title,
                            "company": company,
                        })
                        continue

                    subject = f"Application for {title}"
                    body = (
                        f"Hello{', ' + company if company else ''},\n\n"
                        f"Please find my application for the {title} role attached. "
                        f"I am excited about the opportunity and believe my background is a strong fit.\n\n"
                        f"Best regards."
                    )

                    send_payload = {
                        "to": to_email,
                        "subject": subject,
                        "body": body,
                        "attachment": cv_payload_out,
                        "correlation_id": trace_context.get("correlation_id"),
                        "vacancy": vacancy,
                    }

                    if hasattr(outreach_adapter, "send_application"):
                        send_result = await self._call_adapter_method(
                            outreach_adapter,
                            "send_application",
                            send_payload,
                            trace_context=trace_context,
                        )
                    elif hasattr(outreach_adapter, "send_email"):
                        send_result = await self._call_adapter_method(
                            outreach_adapter,
                            "send_email",
                            send_payload,
                            trace_context=trace_context,
                        )
                    else:
                        raise ValueError("email outreach adapter does not support send_application/send_email")

                    outreach_results.append(send_result)

                outreach_duration_ms = int((time.time() - outreach_start) * 1000)
                steps[-1]["status"] = StepStatus.SUCCEEDED.value
                steps[-1]["meta"] = {
                    "job_count": len(vacancies),
                    "duration_ms": outreach_duration_ms,
                }
                steps[-1]["duration_ms"] = outreach_duration_ms

                await self._update_saga_state(
                    saga_id,
                    SagaState.SUCCEEDED.value,
                    steps=steps,
                    result={
                        "cv": cv_payload_out,
                        "lessons": education_payload_out,
                        "vacancies": vacancies,
                        "outreach": outreach_results,
                    },
                )

            except Exception as outreach_error:
                outreach_duration_ms = int((time.time() - outreach_start) * 1000)
                steps[-1]["status"] = StepStatus.FAILED.value
                steps[-1]["error"] = str(outreach_error)
                steps[-1]["meta"] = {
                    "job_count": len(vacancies),
                    "duration_ms": outreach_duration_ms,
                }
                steps[-1]["duration_ms"] = outreach_duration_ms

                await self._update_saga_state(
                    saga_id,
                    SagaState.FAILED.value,
                    steps=steps,
                    result={
                        "cv": cv_payload_out,
                        "lessons": education_payload_out,
                        "vacancies": vacancies,
                        "outreach": outreach_results,
                        "error": str(outreach_error),
                        "partial_success": True,
                    },
                )

        except Exception as e:
            self.logger.exception(f"❌ Career growth flow failed: {saga_id}")
            await self._attempt_compensation(saga_id, "career_growth_flow", payload, steps, e)
            step = SagaStepRecord(
                name="career_growth_flow",
                status=StepStatus.FAILED.value,
                error=str(e),
            )
            steps.append(step.to_dict())

            await self._update_saga_state(
                saga_id,
                SagaState.FAILED.value,
                steps=steps,
                result={"error": str(e)},
            )


class DiagnosticCoreFlow(BaseSaga):
    saga_type = "diagnostic_core"

    async def run(
        self,
        saga_id: str,
        payload: Dict[str, Any],
        steps: List[Dict[str, Any]],
        correlation_id: Optional[str] = None,
        trace_id: Optional[str] = None,
    ):
        """Execute Diagnostic Core saga: portfolio analysis → diagnostic session → skill matrix."""
        try:
            request_payload = payload.get("request") or payload
            user_id = request_payload.get("user_id")
            trace_context = self._ensure_trace_context(
                saga_id=saga_id,
                saga_type="diagnostic_core",
                action_id=None,
                user_id=user_id,
                correlation_id=correlation_id,
                trace_id=trace_id,
            )

            # Step 1: Portfolio analysis
            self.logger.info(f"🧪 Step 1: Portfolio analysis for saga {saga_id} [correlation: {correlation_id}]")
            step = SagaStepRecord(name="portfolio_analysis", status=StepStatus.IN_PROGRESS.value)
            steps.append(step.to_dict())

            portfolio_result = {
                "status": "skipped",
                "reason": "portfolio adapter not registered",
            }

            portfolio_adapter = self.adapters.get("portfolio")
            has_portfolio = any(
                request_payload.get(key)
                for key in (
                    "portfolio_urls",
                    "portfolioUrls",
                    "portfolio_text",
                    "portfolioText",
                    "projects",
                    "skills",
                )
            )

            if portfolio_adapter and has_portfolio:
                async def _call_portfolio():
                    return await self._call_adapter_method(
                        portfolio_adapter,
                        "analyze",
                        request_payload,
                        trace_context=trace_context,
                    )

                span_id = self.telemetry_collector.start_adapter_call(
                    trace_context.get("root_span_id"),
                    "portfolio",
                    "analyze",
                    payload_size=self._safe_payload_size(request_payload),
                    trace_id=trace_context.get("trace_id"),
                    saga_id=saga_id,
                    correlation_id=trace_context.get("correlation_id"),
                )
                try:
                    portfolio_result = await retry_with_backoff(
                        func=_call_portfolio,
                        config=self.retry_config,
                        operation_name="diagnostic_core.portfolio",
                        logger_instance=self.logger,
                    )
                    self.telemetry_collector.end_span(span_id, status="OK")
                except Exception as e:
                    self.telemetry_collector.end_span(span_id, status="ERROR", error=str(e))
                    raise
            elif not has_portfolio:
                portfolio_result = {"status": "skipped", "reason": "no_portfolio_data"}

            steps[-1]["status"] = StepStatus.SUCCEEDED.value
            steps[-1]["meta"] = {"status": portfolio_result.get("status")}

            # Step 2: Start diagnostic session
            self.logger.info(f"🧪 Step 2: Start diagnostic session for saga {saga_id} [correlation: {correlation_id}]")
            step = SagaStepRecord(
                name="start_diagnostic_session",
                status=StepStatus.IN_PROGRESS.value,
                adapter_type="diagnostic",
                compensatable=True,
            )
            steps.append(step.to_dict())

            diagnostic_result = {
                "status": "skipped",
                "reason": "diagnostic adapter not registered",
            }

            diagnostic_adapter = self.adapters.get("diagnostic")
            target_language = request_payload.get("target_language")
            native_language = request_payload.get("native_language")
            if not user_id or not target_language or not native_language:
                diagnostic_result = {
                    "status": "skipped",
                    "reason": "missing_user_or_language",
                }
            elif diagnostic_adapter and hasattr(diagnostic_adapter, "start_session"):
                diag_payload = {
                    "user_id": user_id,
                    "target_language": target_language,
                    "native_language": native_language,
                    "start_level_guess": request_payload.get("start_level_guess") or "A2",
                    "use_adaptive": bool(request_payload.get("use_adaptive", False)),
                    "persona_id": request_payload.get("persona_id"),
                    "optimize_mode": bool(request_payload.get("optimize_mode", False)),
                }

                async def _call_diagnostic():
                    return await self._call_adapter_method(
                        diagnostic_adapter,
                        "start_session",
                        diag_payload,
                        trace_context=trace_context,
                    )

                span_id = self.telemetry_collector.start_adapter_call(
                    trace_context.get("root_span_id"),
                    "diagnostic",
                    "start_session",
                    payload_size=self._safe_payload_size(diag_payload),
                    trace_id=trace_context.get("trace_id"),
                    saga_id=saga_id,
                    correlation_id=trace_context.get("correlation_id"),
                )
                try:
                    diagnostic_result = await retry_with_backoff(
                        func=_call_diagnostic,
                        config=self.retry_config,
                        operation_name="diagnostic_core.start_session",
                        logger_instance=self.logger,
                    )
                    self.telemetry_collector.end_span(span_id, status="OK")
                except Exception as e:
                    self.telemetry_collector.end_span(span_id, status="ERROR", error=str(e))
                    raise

            steps[-1]["status"] = StepStatus.SUCCEEDED.value
            steps[-1]["meta"] = {"status": diagnostic_result.get("status", "ok")}

            # Step 3: Update skill matrix (portfolio-first, diagnostic pending)
            self.logger.info(f"🧪 Step 3: Update skill matrix for saga {saga_id} [correlation: {correlation_id}]")
            step = SagaStepRecord(
                name="update_skill_matrix",
                status=StepStatus.IN_PROGRESS.value,
                adapter_type="skill_matrix",
                compensatable=True,
            )
            steps.append(step.to_dict())

            matrix_result = {
                "status": "skipped",
                "reason": "skill_matrix adapter not registered",
            }

            if user_id:
                skill_matrix_adapter = self.adapters.get("skill_matrix")
                if skill_matrix_adapter and hasattr(skill_matrix_adapter, "update_matrix"):
                    from app.services.diagnostic.core import build_competency_model

                    competency_model = build_competency_model(
                        diagnostic_results=None,
                        portfolio_analysis=portfolio_result,
                    )

                    matrix_payload = {
                        "status": "diagnostic_started",
                        "diagnostic_session": diagnostic_result,
                        "portfolio_analysis": portfolio_result,
                        "competency_model": competency_model,
                    }

                    matrix_request = {
                        "user_id": user_id,
                        "matrix": matrix_payload,
                        "source": "diagnostic_core",
                    }

                    async def _call_matrix():
                        return await self._call_adapter_method(
                            skill_matrix_adapter,
                            "update_matrix",
                            matrix_request,
                            trace_context=trace_context,
                        )

                    span_id = self.telemetry_collector.start_adapter_call(
                        trace_context.get("root_span_id"),
                        "skill_matrix",
                        "update_matrix",
                        payload_size=self._safe_payload_size(matrix_request),
                        trace_id=trace_context.get("trace_id"),
                        saga_id=saga_id,
                        correlation_id=trace_context.get("correlation_id"),
                    )
                    try:
                        matrix_result = await retry_with_backoff(
                            func=_call_matrix,
                            config=self.retry_config,
                            operation_name="diagnostic_core.skill_matrix",
                            logger_instance=self.logger,
                        )
                        self.telemetry_collector.end_span(span_id, status="OK")
                    except Exception as e:
                        self.telemetry_collector.end_span(span_id, status="ERROR", error=str(e))
                        raise
                else:
                    matrix_result = {"status": "skipped", "reason": "skill_matrix adapter not registered"}
            else:
                matrix_result = {"status": "skipped", "reason": "missing_user_id"}

            steps[-1]["status"] = StepStatus.SUCCEEDED.value
            steps[-1]["meta"] = {"status": matrix_result.get("status", "ok")}

            await self._update_saga_state(
                saga_id,
                SagaState.SUCCEEDED.value,
                steps=steps,
                result={
                    "portfolio_analysis": portfolio_result,
                    "diagnostic_session": diagnostic_result,
                    "skill_matrix": matrix_result,
                },
            )

        except Exception as e:
            self.logger.exception(f"❌ Diagnostic Core flow failed: {saga_id}")
            await self._attempt_compensation(saga_id, "diagnostic_core", payload, steps, e)
            step = SagaStepRecord(
                name="diagnostic_core",
                status=StepStatus.FAILED.value,
                error=str(e),
            )
            steps.append(step.to_dict())

            await self._update_saga_state(
                saga_id,
                SagaState.FAILED.value,
                steps=steps,
                result={"error": str(e)},
            )


class CareerUpskillingFlow(BaseSaga):
    saga_type = "career_upskilling"

    async def run(
        self,
        saga_id: str,
        payload: Dict[str, Any],
        steps: List[Dict[str, Any]],
        correlation_id: Optional[str] = None,
        trace_id: Optional[str] = None,
    ):
        """Execute career upskilling saga: analyze gaps → await confirmation."""
        try:
            self.logger.info(
                f"🧭 Step 1: Analyzing career skill gaps for saga {saga_id} [correlation: {correlation_id}]"
            )
            step = SagaStepRecord(name="analyze_skill_gaps", status=StepStatus.IN_PROGRESS.value)
            steps.append(step.to_dict())

            request_payload = payload.get("request") or payload.get("params") or payload
            user_skills = request_payload.get("user_skills") or []
            monitored_jobs = request_payload.get("monitored_jobs") or request_payload.get("jobs") or []
            target_role = request_payload.get("target_role")
            duration_weeks = int(request_payload.get("duration_weeks") or 8)
            assessment_mode = request_payload.get("assessment_mode") or "language"

            from app.services.career.upskilling import build_skill_gap_analysis, build_upskilling_plan

            analysis = build_skill_gap_analysis(
                user_skills=user_skills,
                monitored_jobs=monitored_jobs,
            )
            plan = build_upskilling_plan(
                missing_skills=analysis.missing_skills,
                target_role=target_role,
                duration_weeks=duration_weeks,
            )

            steps[-1]["status"] = StepStatus.SUCCEEDED.value
            steps[-1]["meta"] = {
                "missing_skills": len(analysis.missing_skills),
                "matched_skills": len(analysis.matched_skills),
                "gap_score": analysis.gap_score,
            }

            result_payload = {
                "analysis": analysis.to_dict(),
                "upskilling_plan": plan.to_dict(),
                "assessment_mode": assessment_mode,
            }

            if analysis.missing_skills:
                # Pause for user confirmation before starting assessment/learning
                step = SagaStepRecord(name="await_user_confirm", status=StepStatus.PENDING.value)
                steps.append(step.to_dict())

                await self._update_saga_state(
                    saga_id,
                    SagaState.WAITING_CONFIRM.value,
                    steps=steps,
                    result=result_payload,
                )
                self.logger.info(f"⏳ Career upskilling saga paused for confirmation: {saga_id}")
                return

            await self._update_saga_state(
                saga_id,
                SagaState.SUCCEEDED.value,
                steps=steps,
                result={
                    **result_payload,
                    "note": "No missing skills detected; upskilling not required",
                },
            )

        except Exception as e:
            self.logger.exception(f"❌ Career upskilling flow failed: {saga_id}")
            step = SagaStepRecord(
                name="analyze_skill_gaps",
                status=StepStatus.FAILED.value,
                error=str(e),
            )
            steps.append(step.to_dict())

            await self._update_saga_state(
                saga_id,
                SagaState.FAILED.value,
                steps=steps,
                result={"error": str(e)},
            )

    async def resume(
        self,
        *,
        saga_id: str,
        saga: Dict[str, Any],
        steps: List[Dict[str, Any]],
        confirm_payload: Dict[str, Any],
        trace_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Resume career upskilling saga after user confirmation."""
        try:
            request_payload = saga.get("payload") or {}
            request_payload = request_payload.get("request") or request_payload.get("params") or request_payload

            trace_context = trace_context or (
                self._active_traces.get(saga_id)
                or self._resolve_trace_context_from_steps(steps)
                or self._ensure_trace_context(
                    saga_id=saga_id,
                    saga_type=saga.get("saga_type"),
                    action_id=saga.get("action_id"),
                    user_id=saga.get("user_id"),
                    correlation_id=saga.get("correlation_id"),
                    trace_id=None,
                )
            )

            assessment_mode = confirm_payload.get("assessment_mode") or request_payload.get("assessment_mode") or "language"
            target_language = request_payload.get("target_language")
            native_language = request_payload.get("native_language")
            start_level_guess = request_payload.get("start_level_guess") or "A2"
            use_adaptive = bool(request_payload.get("use_adaptive", False))

            result_snapshot = saga.get("result") or {}
            analysis = result_snapshot.get("analysis")
            upskilling_plan = result_snapshot.get("upskilling_plan")

            # Step: start assessment if language mode
            step = SagaStepRecord(
                name="start_assessment",
                status=StepStatus.IN_PROGRESS.value,
                adapter_type="diagnostic",
                compensatable=True,
            )
            steps.append(step.to_dict())

            assessment_result: Dict[str, Any]
            if assessment_mode == "language" and target_language and native_language:
                adapter = self.adapters.get("diagnostic")
                if adapter and hasattr(adapter, "start_session"):
                    assessment_payload = {
                        "user_id": saga.get("user_id") or request_payload.get("user_id"),
                        "target_language": target_language,
                        "native_language": native_language,
                        "start_level_guess": start_level_guess,
                        "use_adaptive": use_adaptive,
                        "persona_id": request_payload.get("persona_id"),
                        "optimize_mode": bool(request_payload.get("optimize_mode", False)),
                    }
                    span_id = self.telemetry_collector.start_adapter_call(
                        trace_context.get("root_span_id"),
                        "diagnostic",
                        "start_session",
                        payload_size=self._safe_payload_size(assessment_payload),
                        trace_id=trace_context.get("trace_id"),
                        saga_id=saga_id,
                        correlation_id=trace_context.get("correlation_id"),
                    )
                    try:
                        assessment_result = await self._call_adapter_method(
                            adapter,
                            "start_session",
                            assessment_payload,
                            trace_context=trace_context,
                        )
                        self.telemetry_collector.end_span(span_id, status="OK")
                    except Exception as e:
                        self.telemetry_collector.end_span(span_id, status="ERROR", error=str(e))
                        raise
                else:
                    assessment_result = {
                        "status": "skipped",
                        "reason": "diagnostic adapter not registered",
                    }
            else:
                assessment_result = {
                    "status": "skipped",
                    "reason": "assessment_mode=professional or missing language params",
                }

            steps[-1]["status"] = StepStatus.SUCCEEDED.value
            steps[-1]["meta"] = {
                "assessment_mode": assessment_mode,
            }

            learning_plan_result = None
            if assessment_mode == "language" and target_language and native_language:
                step = SagaStepRecord(
                    name="generate_learning_plan",
                    status=StepStatus.IN_PROGRESS.value,
                    adapter_type="learning_plan",
                    compensatable=True,
                )
                steps.append(step.to_dict())

                adapter = self.adapters.get("learning_plan") or self.adapters.get("lesson_plan")
                if adapter:
                    plan_payload = {
                        "user_id": saga.get("user_id") or request_payload.get("user_id"),
                        "target_language": target_language,
                        "native_language": native_language,
                        "topic": request_payload.get("target_role"),
                        "estimated_cefr": request_payload.get("estimated_cefr"),
                        "weak_subskills": request_payload.get("weak_subskills"),
                        "lesson_length": request_payload.get("lesson_length", 15),
                        "persona_id": request_payload.get("persona_id"),
                    }

                    async def _call_generate():
                        if hasattr(adapter, "generate_learning_plan"):
                            return await self._call_adapter_method(
                                adapter,
                                "generate_learning_plan",
                                plan_payload,
                                trace_context=trace_context,
                            )
                        if hasattr(adapter, "generate_plan"):
                            return await self._call_adapter_method(
                                adapter,
                                "generate_plan",
                                plan_payload,
                                trace_context=trace_context,
                            )
                        if callable(adapter):
                            kwargs: Dict[str, Any] = {}
                            try:
                                signature = inspect.signature(adapter)
                                params = signature.parameters
                                if "trace_context" in params:
                                    kwargs["trace_context"] = trace_context
                                if "trace_id" in params:
                                    kwargs["trace_id"] = trace_context.get("trace_id")
                                if "correlation_id" in params:
                                    kwargs["correlation_id"] = trace_context.get("correlation_id")
                            except (TypeError, ValueError):
                                pass
                            result = adapter(plan_payload, **kwargs)
                            if asyncio.iscoroutine(result):
                                return await result
                            return result
                        raise ValueError("learning_plan adapter does not support generate_learning_plan/generate_plan")

                    span_id = self.telemetry_collector.start_adapter_call(
                        trace_context.get("root_span_id"),
                        "learning_plan",
                        "generate",
                        payload_size=self._safe_payload_size(plan_payload),
                        trace_id=trace_context.get("trace_id"),
                        saga_id=saga_id,
                        correlation_id=trace_context.get("correlation_id"),
                    )
                    try:
                        learning_plan_result = await _call_generate()
                        self.telemetry_collector.end_span(span_id, status="OK")
                    except Exception as e:
                        self.telemetry_collector.end_span(span_id, status="ERROR", error=str(e))
                        raise
                    steps[-1]["status"] = StepStatus.SUCCEEDED.value
                else:
                    steps[-1]["status"] = StepStatus.FAILED.value
                    steps[-1]["error"] = "learning_plan adapter not registered"

            result_payload = {
                "analysis": analysis,
                "upskilling_plan": upskilling_plan,
                "assessment_mode": assessment_mode,
                "assessment": assessment_result,
                "learning_plan": learning_plan_result,
            }

            await self._update_saga_state(
                saga_id,
                SagaState.SUCCEEDED.value,
                steps=steps,
                result=result_payload,
            )

            return {"status": "succeeded", "result": result_payload}

        except Exception as e:
            self.logger.exception(f"❌ Career upskilling resume failed: {saga_id}")
            step = SagaStepRecord(
                name="resume_career_upskilling",
                status=StepStatus.FAILED.value,
                error=str(e),
            )
            steps.append(step.to_dict())

            await self._update_saga_state(
                saga_id,
                SagaState.FAILED.value,
                steps=steps,
                result={"error": str(e)},
            )

            return {"status": "failed", "error": str(e)}


