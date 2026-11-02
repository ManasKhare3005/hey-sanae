"""Load config.yaml into a nested, attribute-accessible object."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent


class Section(dict):
    """dict that also allows cfg.llm.host style access."""

    def __getattr__(self, key: str) -> Any:
        try:
            value = self[key]
        except KeyError as exc:
            raise AttributeError(key) from exc
        return Section(value) if isinstance(value, dict) and not isinstance(value, Section) else value

    def __setattr__(self, key: str, value: Any) -> None:
        self[key] = value


def load_config(path: str | Path | None = None) -> Section:
    path = Path(path) if path else ROOT / "config.yaml"
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    # Private values (feed links, app passwords) live in secrets.yaml, which git ignores
    secrets = ROOT / "secrets.yaml"
    if secrets.exists():
        with open(secrets, "r", encoding="utf-8") as f:
            data["secrets"] = yaml.safe_load(f) or {}
    else:
        data.setdefault("secrets", {})
    if path.resolve() == (ROOT / "config.yaml").resolve():
        apply_personal(data, ROOT / "personal.yaml")
        apply_persona(data, ROOT / "persona.yaml")
    return Section(data)


def merge(base: dict, extra: dict) -> None:
    """Values from `extra` win; sections are merged key by key."""
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            merge(base[key], value)
        else:
            base[key] = value


def apply_personal(data: dict, path: Path) -> None:
    """personal.yaml (git ignores it) holds your name, location and so on, on top of config.yaml."""
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            merge(data, yaml.safe_load(f) or {})


def apply_persona(data: dict, persona_path: Path) -> None:
    """persona.yaml decides the name, the wake phrase and how the voice says tricky words."""
    if not persona_path.exists():
        return
    with open(persona_path, "r", encoding="utf-8") as f:
        p = yaml.safe_load(f) or {}
    if p.get("name"):
        data.setdefault("assistant", {})["name"] = p["name"]
    if p.get("wake_phrase"):
        # the spelling shown first; sound-alike spellings after it (the detector listens for all)
        data.setdefault("wake_word", {})["phrase"] = "|".join([p["wake_phrase"], *(p.get("wake_sounds_like") or [])])
    if p.get("pronounce"):
        tts = data.setdefault("tts", {})
        tts["spellings"] = {**p["pronounce"], **(tts.get("spellings") or {})}


def resolve_path(p: str | Path) -> Path:
    """Paths in config are relative to the project root."""
    p = Path(p)
    return p if p.is_absolute() else ROOT / p
