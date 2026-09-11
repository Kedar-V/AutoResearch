from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MemoryScope:
    """Identity keys for recall/retain. Prefer project_id; run_id is optional session."""

    project_id: str = ""
    run_id: str = ""
    peer_id: str = "operator"
    hypothesis_id: str = ""
    trial_id: str = ""

    def session_key(self) -> str:
        if self.project_id:
            return f"project:{self.project_id}"
        if self.run_id:
            return f"run:{self.run_id}"
        return "project:default"

    def bank_id(self, prefix: str = "autoresearch") -> str:
        base = self.project_id or self.run_id or "default"
        return f"{prefix}:{base}"
