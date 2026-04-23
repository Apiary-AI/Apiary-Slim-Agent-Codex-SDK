"""Mutable runtime overrides for Codex model and reasoning effort.

`Config` is boot-time and frozen. This holder owns the two user-tunable knobs
that can change while the agent is running (via `/model` and `/effort` Telegram
commands) and persists them to a JSON file on the /home/agent/.codex volume
so the choice survives container restarts.
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path

from .config import Config

log = logging.getLogger(__name__)


class RuntimeConfig:
    PATH = os.path.join(
        os.environ.get("HOME", "/home/agent"), ".codex", "runtime_config.json"
    )
    KNOWN_MODELS = (
        "gpt-5.5",
        "gpt-5.5-mini",
        "gpt-5.4",
        "gpt-5.4-mini",
        "gpt-5.3-codex",
        "o4-mini",
        "o3",
    )
    EFFORT_LEVELS = ("minimal", "low", "medium", "high", "xhigh")
    MODEL_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")

    def __init__(self, model: str, effort: str) -> None:
        self.model = model
        self.effort = effort

    @classmethod
    def load(cls, config: Config) -> "RuntimeConfig":
        rc = cls(model=config.codex_model, effort=config.codex_reasoning_effort)
        if os.path.exists(cls.PATH):
            try:
                data = json.loads(Path(cls.PATH).read_text())
                if isinstance(data.get("model"), str):
                    rc.model = data["model"]
                if isinstance(data.get("effort"), str):
                    rc.effort = data["effort"]
                log.info(
                    "RuntimeConfig loaded from %s (model=%s, effort=%s)",
                    cls.PATH, rc.model, rc.effort,
                )
            except (OSError, json.JSONDecodeError) as e:
                log.warning("runtime_config.json unreadable (%s) — using env defaults", e)
        return rc

    def _save(self) -> None:
        Path(self.PATH).parent.mkdir(parents=True, exist_ok=True)
        Path(self.PATH).write_text(json.dumps({"model": self.model, "effort": self.effort}))

    def set_model(self, model: str) -> None:
        if not self.MODEL_RE.match(model):
            raise ValueError(f"Not a valid model id: {model!r}")
        self.model = model
        self._save()

    def set_effort(self, effort: str) -> None:
        if effort not in self.EFFORT_LEVELS:
            raise ValueError(
                f"Effort must be one of {', '.join(self.EFFORT_LEVELS)} — got {effort!r}"
            )
        self.effort = effort
        self._save()
