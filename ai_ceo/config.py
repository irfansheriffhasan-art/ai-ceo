"""Typed configuration.

Every setting can be overridden with an ``AICEO_*`` environment variable or a
``.env`` file in the working directory. Provider API keys are also read from
their conventional names (``ANTHROPIC_API_KEY`` / ``OPENAI_API_KEY``).
Secrets are held as ``SecretStr`` so they never show up in logs or reprs.
"""

from __future__ import annotations

import secrets
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

ProviderName = Literal["ollama", "anthropic", "openai", "mock"]

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AICEO_",
        # Project-root .env first, then one in the working directory (later files win).
        env_file=(PROJECT_ROOT / ".env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---- LLM -----------------------------------------------------------------
    llm_provider: ProviderName = "ollama"
    llm_model: str = "llama3.1:8b"
    # Optional per-role model overrides, e.g. AICEO_LLM_ROLE_MODELS='{"frontend":"qwen2.5-coder:7b"}'
    llm_role_models: dict[str, str] = Field(default_factory=dict)
    llm_timeout_s: float = 600.0
    llm_max_retries: int = 2
    # Local models share one GPU, so calls are serialised by default.
    llm_max_concurrency: int = 1
    llm_temperature: float = 0.2

    ollama_host: str = "http://127.0.0.1:11434"
    # Keep this constant: changing num_ctx between calls forces Ollama to reload the model.
    ollama_num_ctx: int = 8192

    anthropic_api_key: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("AICEO_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY")
    )
    anthropic_effort: Literal["low", "medium", "high", "xhigh", "max"] = "medium"

    openai_api_key: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("AICEO_OPENAI_API_KEY", "OPENAI_API_KEY")
    )
    openai_base_url: str | None = None

    # Mock provider: inject a deliberate bug in the first frontend build to exercise the fix loop,
    # and pace each "model call" so a demo can be watched (0 = instant).
    mock_inject_bug: bool = True
    mock_delay_s: float = 1.5

    # ---- Orchestration -------------------------------------------------------
    task_max_attempts: int = 3
    task_timeout_s: float = 1200.0
    max_parallel_tasks: int = 3
    max_fix_iterations: int = 3
    require_human_approval: bool = False
    auto_deploy: bool = True

    # ---- Storage ---------------------------------------------------------------
    data_dir: Path = PROJECT_ROOT / "data"

    # ---- Server ----------------------------------------------------------------
    host: str = "127.0.0.1"
    port: int = 8000
    auth_token: SecretStr | None = None
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"]
    )

    # ---- Verification ------------------------------------------------------
    # auto = try Playwright's bundled Chromium, then Edge, then Chrome. "none" disables browser tests.
    browser_channel: Literal["auto", "chromium", "msedge", "chrome", "none"] = "auto"
    node_path: str = "node"
    # Generated backends are executed locally for API tests. Disable on untrusted machines.
    run_generated_backends: bool = True

    # ---- Derived paths -------------------------------------------------------
    @property
    def db_path(self) -> Path:
        return self.data_dir / "aiceo.db"

    @property
    def workspaces_dir(self) -> Path:
        return self.data_dir / "workspaces"

    @property
    def releases_dir(self) -> Path:
        return self.data_dir / "releases"

    @property
    def artifacts_dir(self) -> Path:
        return self.data_dir / "artifacts"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def web_dist_dir(self) -> Path:
        return PROJECT_ROOT / "web" / "dist"

    def model_for(self, role: str) -> str:
        return self.llm_role_models.get(role, self.llm_model)

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.workspaces_dir, self.releases_dir, self.artifacts_dir, self.logs_dir):
            d.mkdir(parents=True, exist_ok=True)

    def resolve_auth_token(self) -> str:
        """Return the API token, generating and persisting one on first use.

        The generated token is stored in ``data/auth_token`` (gitignored) so the
        dashboard login survives restarts.
        """
        if self.auth_token is not None:
            return self.auth_token.get_secret_value()
        self.ensure_dirs()
        token_file = self.data_dir / "auth_token"
        if token_file.exists():
            token = token_file.read_text(encoding="utf-8").strip()
            if token:
                return token
        token = secrets.token_urlsafe(24)
        token_file.write_text(token, encoding="utf-8")
        return token


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_dirs()
    return settings
