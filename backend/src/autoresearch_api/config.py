from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AUTORESEARCH_", env_file=".env")

    database_url: str = "sqlite:///./autoresearch.db"
    project_root: Path = Path.cwd()
    runtime_root: Path = Path.cwd() / ".autoresearch"
    champion_branch: str = "master"
    allowed_origins: str = "http://localhost:5173"
    script_timeout_seconds: int = 300
    protected_paths: str = "eval.py,tests,.research"

    @field_validator("project_root", "runtime_root", mode="before")
    @classmethod
    def expand_path(cls, value: str | Path) -> Path:
        return Path(value).expanduser().resolve()

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]

    @property
    def protected_path_list(self) -> list[str]:
        return [path.strip() for path in self.protected_paths.split(",") if path.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
