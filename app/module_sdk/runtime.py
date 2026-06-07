from __future__ import annotations

import inspect
from typing import Any, Dict, List, Literal, Optional, Protocol

from pydantic import BaseModel, Field, model_validator

try:
    from jsonschema import Draft202012Validator
except Exception:  # pragma: no cover
    Draft202012Validator = None


class ModuleDiagnostic(BaseModel):
    code: str
    path: str
    message: str


class ModuleExecutionContext(BaseModel):
    module_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    execution_mode: Literal["test", "sandbox", "live"] = "test"
    capabilities: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ModuleFailure(BaseModel):
    code: str
    message: str
    retryable: bool = False
    details: Dict[str, Any] = Field(default_factory=dict)


class ModuleResult(BaseModel):
    status: Literal["succeeded", "failed"]
    output: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[ModuleFailure] = None
    diagnostics: List[ModuleDiagnostic] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_envelope(self) -> "ModuleResult":
        if self.status == "failed" and self.error is None:
            raise ValueError("failed module result requires error")
        if self.status == "succeeded" and self.error is not None:
            raise ValueError("succeeded module result cannot include error")
        return self

    @classmethod
    def success(cls, output: Dict[str, Any]) -> "ModuleResult":
        return cls(status="succeeded", output=output)

    @classmethod
    def failure(
        cls,
        *,
        code: str,
        message: str,
        retryable: bool = False,
        details: Optional[Dict[str, Any]] = None,
        diagnostics: Optional[List[ModuleDiagnostic]] = None,
    ) -> "ModuleResult":
        return cls(
            status="failed",
            error=ModuleFailure(
                code=code,
                message=message,
                retryable=retryable,
                details=details or {},
            ),
            diagnostics=diagnostics or [],
        )


class ModuleSDKError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.details = details or {}


class ModuleHandler(Protocol):
    async def execute(
        self,
        context: ModuleExecutionContext,
        inputs: Dict[str, Any],
    ) -> Dict[str, Any] | ModuleResult: ...


def validate_payload(schema: Dict[str, Any], payload: Dict[str, Any], *, root: str) -> List[ModuleDiagnostic]:
    if not schema or Draft202012Validator is None:
        return []
    validator = Draft202012Validator(schema)
    diagnostics: List[ModuleDiagnostic] = []
    for error in sorted(validator.iter_errors(payload), key=lambda item: str(list(item.path))):
        suffix = ".".join(str(part) for part in error.path)
        path = f"{root}.{suffix}" if suffix else root
        diagnostics.append(
            ModuleDiagnostic(
                code=f"sdk.{root.strip('$.')}_invalid",
                path=path,
                message=error.message,
            )
        )
    return diagnostics


async def execute_module(
    handler: ModuleHandler,
    *,
    context: ModuleExecutionContext,
    inputs: Dict[str, Any],
    input_schema: Dict[str, Any],
    output_schema: Dict[str, Any],
) -> ModuleResult:
    input_diagnostics = validate_payload(input_schema, inputs, root="$.input")
    if input_diagnostics:
        return ModuleResult.failure(
            code="sdk.input_invalid",
            message="Module input failed schema validation.",
            diagnostics=input_diagnostics,
        )

    try:
        value = handler.execute(context, inputs)
        result = await value if inspect.isawaitable(value) else value
    except ModuleSDKError as exc:
        return ModuleResult.failure(
            code=exc.code,
            message=exc.message,
            retryable=exc.retryable,
            details=exc.details,
        )
    except Exception as exc:  # noqa: BLE001
        return ModuleResult.failure(
            code="sdk.unhandled_exception",
            message=str(exc) or exc.__class__.__name__,
        )

    if isinstance(result, ModuleResult):
        envelope = result
    elif isinstance(result, dict):
        envelope = ModuleResult.success(result)
    else:
        return ModuleResult.failure(
            code="sdk.invalid_handler_result",
            message="Handler must return a dictionary or ModuleResult.",
        )
    if envelope.status == "failed":
        return envelope

    output_diagnostics = validate_payload(output_schema, envelope.output, root="$.output")
    if output_diagnostics:
        return ModuleResult.failure(
            code="sdk.output_invalid",
            message="Module output failed schema validation.",
            diagnostics=output_diagnostics,
        )
    return envelope
