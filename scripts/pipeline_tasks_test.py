#!/usr/bin/env python3
"""Ad-hoc pipeline test: plan a basic conversation unit, generate 5 tasks per topic, log tasks and metrics.

Usage: PYTHONPATH=. python scripts/pipeline_tasks_test.py
"""
import asyncio
import json
import logging
import time
from typing import List, Dict

from app.services.pipeline.pipeline.core import PipelineStep, PipelineContext, PipelineOrchestrator
from app.infrastructure.llm.client import get_llm_client
from app.settings import get_settings


logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


class TrainingPlanStep(PipelineStep):
    def __init__(self):
        super().__init__(name="TrainingPlan", agent_name="Architect 🧠", icon="🧠")

    async def execute(self, ctx: PipelineContext) -> None:
        await self._emit_start(ctx, "Designing training unit for basic conversation...")
        settings = get_settings()
        llm = await get_llm_client()

        prompt = (
            "Design a compact learning plan for a BASIC CONVERSATION unit. "
            "Return ONLY JSON with fields: \n"
            "{\n"
            "  \"unit\": \"Basic Conversation\",\n"
            "  \"cefr\": \"A2\",\n"
            "  \"topics\": [\"greetings\", \"introductions\", \"small talk\"],\n"
            "  \"objectives\": [\"say hello\", \"introduce yourself\", \"ask/answer how-are-you\" ]\n"
            "}\n"
            "Keep it concise; 3-4 topics is enough."
        )

        resp = await llm.generate(
            system_prompt="You are a precise curriculum architect.",
            user_prompt=prompt,
            provider=settings.default_provider_fast or "stub",
            model=settings.gemini_model_fast,
            max_tokens=400
        )

        text = resp.text
        start = text.find("{")
        end = text.rfind("}") + 1
        if start < 0 or end <= start:
            raise ValueError("Planner returned no JSON")
        plan = json.loads(text[start:end])
        if not plan.get("topics"):
            plan["topics"] = ["greetings", "introductions", "small talk"]
        ctx.set("training_plan", plan)

        await self._emit_complete(ctx, f"Plan ready: {plan.get('unit', 'Unit')} with {len(plan.get('topics', []))} topics")


class TaskGeneratorStep(PipelineStep):
    def __init__(self):
        super().__init__(name="TaskGenerator", agent_name="Task Designer 🛠️", icon="🛠️")
        self.total_tokens_in = 0
        self.total_tokens_out = 0
        self.calls = 0
        self.parser_version = "v1"
        self.run_id: str | None = None

    async def execute(self, ctx: PipelineContext) -> None:
        await self._emit_start(ctx, "Generating 5 tasks per topic...")
        settings = get_settings()
        llm = await get_llm_client()

        # Pull run_id from context for provenance
        self.run_id = ctx.get("run_id")

        plan = ctx.get("training_plan", {})
        topics: List[str] = plan.get("topics", [])
        if not topics:
            raise ValueError("No topics found in training plan")

        tasks_all: List[Dict] = []
        t0 = time.perf_counter()

        for idx, topic in enumerate(topics, 1):
            prompt = (
                f"You are an exercise designer for language learning.\n"
                f"Topic: {topic}\n"
                "Create exactly 5 varied tasks in JSON list under key 'tasks'.\n"
                "Each task has: type, instruction, sample_answer. Keep instructions short."
            )

            resp = await llm.generate(
                system_prompt="You are an exercise designer for language learning.",
                user_prompt=prompt,
                provider=settings.default_provider_fast or "stub",
                model=settings.gemini_model_fast,
                max_tokens=800
            )

            self.calls += 1
            self.total_tokens_in += resp.tokens_in
            self.total_tokens_out += resp.tokens_out

            text = resp.text
            start = text.find("{")
            end = text.rfind("}") + 1
            if start < 0 or end <= start:
                raise ValueError(f"No JSON for topic {topic}")
            task_json = json.loads(text[start:end])
            topic_tasks = task_json.get("tasks", [])

            # Log each task
            for t_idx, task in enumerate(topic_tasks, 1):
                logger.info(f"[{idx}/{len(topics)}] {topic} | Task {t_idx}: {task}")

            tasks_all.extend([{**task, "topic": topic} for task in topic_tasks])

            # Persist to JSONL with provenance and metrics per batch
            record = {
                "run_id": self.run_id,
                "topic": topic,
                "tasks": topic_tasks,
                "request": {
                    "system_prompt": "You are an exercise designer for language learning.",
                    "user_prompt": prompt,
                    "parser_version": self.parser_version
                },
                "metrics": {
                    "tokens_in": resp.tokens_in,
                    "tokens_out": resp.tokens_out,
                    "latency_ms": resp.latency_ms
                },
                "timestamp": time.time()
            }
            with open("reports/generated_tasks.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")

        elapsed = (time.perf_counter() - t0) * 1000
        ctx.set("tasks", tasks_all)
        ctx.set("task_metrics", {
            "calls": self.calls,
            "tokens_in": self.total_tokens_in,
            "tokens_out": self.total_tokens_out,
            "latency_ms": round(elapsed, 1)
        })

        await self._emit_complete(
            ctx,
            f"Generated {len(tasks_all)} tasks across {len(topics)} topics",
            {"tokens_in": self.total_tokens_in, "tokens_out": self.total_tokens_out, "latency_ms": round(elapsed, 1)}
        )


aSYNC_STEPS = [TrainingPlanStep(), TaskGeneratorStep()]


async def main():
    run_id = f"run_{int(time.time() * 1000)}"
    ctx = PipelineContext({"run_id": run_id})
    orch = PipelineOrchestrator(steps=aSYNC_STEPS)
    await orch.run(ctx)

    plan = ctx.get("training_plan", {})
    tasks = ctx.get("tasks", [])
    metrics = ctx.get("task_metrics", {})

    # Also persist a summary record (plan + metrics) to JSONL
    summary = {
        "run_id": run_id,
        "plan": plan,
        "task_metrics": metrics,
        "generated_tasks_count": len(tasks),
        "parser_version": "v1",
        "timestamp": time.time(),
        "pipeline_duration_ms": round(ctx.get_duration() * 1000, 1)
    }
    with open("reports/generated_tasks_summary.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(summary, ensure_ascii=False) + "\n")

    print("\n=== PLAN ===")
    print(json.dumps(plan, indent=2, ensure_ascii=False))

    print("\n=== TASKS (first 5) ===")
    for task in tasks[:5]:
        print(json.dumps(task, ensure_ascii=False))
    print(f"Total tasks: {len(tasks)}")

    print("\n=== METRICS ===")
    print(json.dumps(metrics, indent=2))

    print(f"\nPipeline duration: {ctx.get_duration():.2f}s, steps completed: {ctx.metadata['steps_completed']}")


if __name__ == "__main__":
    asyncio.run(main())

