from __future__ import annotations

from dataclasses import dataclass

from app.core import persona_prompts as loader
from app.core import personas as legacy_personas


@dataclass(frozen=True)
class Persona:
    id: str
    system_message: str


def get_persona_prompt(persona_id_requested: str | None):
    return loader.get_persona_prompt(persona_id_requested)


def get_default_persona_id() -> str:
    return loader.get_default_persona_id()


def list_all_metadata():
    return loader.list_all_metadata()


def init_persona_loader(base_dir, dev_mode: bool = False) -> None:
    return loader.init_persona_loader(base_dir, dev_mode)


def get_persona_by_id(persona_id: str | None) -> Persona | None:
    pid, prompt = legacy_personas.get_persona_prompt(persona_id)
    return Persona(id=pid, system_message=prompt) if prompt else None


def get_default_diagnostic_persona() -> Persona:
    pid = legacy_personas.DEFAULT_PERSONA_ID
    prompt = legacy_personas.PERSONA_PROMPTS[pid]
    return Persona(id=pid, system_message=prompt)

__all__ = [
    "get_default_persona_id",
    "get_persona_prompt",
    "list_all_metadata",
    "init_persona_loader",
    "get_persona_by_id",
    "get_default_diagnostic_persona",
    "Persona",
]
