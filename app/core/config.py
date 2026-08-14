from __future__ import annotations

from functools import lru_cache
from typing import Literal
from urllib.parse import quote_plus

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["development", "staging", "production"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    environment: Environment = "development"
    log_level: str = "INFO"
    docs_enabled: bool = True

    db_host: str = "127.0.0.1"
    db_port: int = 3306
    db_user: str = "bolsocoberto"
    db_password: SecretStr = SecretStr("")
    db_name: str = "bolsocoberto"
    db_pool_size: int = 5
    db_max_overflow: int = 10
    db_pool_recycle_seconds: int = 1800

    run_migrations_on_startup: bool = True

    session_secret: SecretStr = SecretStr("")
    public_url: str = "http://127.0.0.1:8000"
    oauth_allowlist: str = "muhbianco@gmail.com"

    google_client_id: str = ""
    google_client_secret: SecretStr = SecretStr("")

    gemini_api_key: SecretStr = SecretStr("")
    llm_model: str = "gemini-2.5-flash"
    llm_timeout_seconds: float = 90.0

    wp_base_url: str = "https://bolsocoberto.com.br"
    wp_app_user: str = ""
    wp_app_password: SecretStr = SecretStr("")

    fetch_timeout_seconds: float = 15.0
    fetch_max_bytes: int = 1_500_000
    fetch_max_urls: int = 8
    worker_poll_seconds: float = 2.0

    api_title: str = "Bolso Coberto Editor"
    root_path: str = ""

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def oauth_allowlist_set(self) -> frozenset[str]:
        return frozenset(
            part.strip().lower()
            for part in self.oauth_allowlist.split(",")
            if part.strip()
        )

    @property
    def google_redirect_uri(self) -> str:
        return f"{self.public_url.rstrip('/')}/auth/callback"

    def _dsn(self, driver: str, database: str) -> str:
        password = quote_plus(self.db_password.get_secret_value())
        user = quote_plus(self.db_user)
        base = f"mysql+{driver}://{user}:{password}@{self.db_host}:{self.db_port}"
        if database:
            return f"{base}/{database}?charset=utf8mb4"
        return f"{base}/?charset=utf8mb4"

    @property
    def database_url(self) -> str:
        return self._dsn("asyncmy", self.db_name)

    @property
    def server_url(self) -> str:
        return self._dsn("asyncmy", "")

    @model_validator(mode="after")
    def _validate_production_secrets(self) -> Settings:
        if not self.is_production:
            return self
        missing = [
            name
            for name, value in (
                ("SESSION_SECRET", self.session_secret.get_secret_value()),
                ("DB_PASSWORD", self.db_password.get_secret_value()),
            )
            if not value
        ]
        if missing:
            raise ValueError(
                f"Variáveis obrigatórias em produção não definidas: {', '.join(missing)}"
            )
        if len(self.session_secret.get_secret_value()) < 32:
            raise ValueError("SESSION_SECRET deve ter ao menos 32 caracteres em produção.")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
