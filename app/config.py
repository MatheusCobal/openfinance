from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict

CONFIG_MODEL = SettingsConfigDict(
    env_file=".env",
    env_file_encoding="utf-8",
    extra="ignore",
)


class MissingPluggyCredentialsError(RuntimeError):
    pass


class DatabaseSettings(BaseSettings):
    database_url: str = "sqlite:///./openfinance.db"

    model_config = CONFIG_MODEL


class PluggySettings(BaseSettings):
    pluggy_client_id: Optional[str] = None
    pluggy_client_secret: Optional[str] = None
    pluggy_base_url: str = "https://api.pluggy.ai"

    model_config = CONFIG_MODEL

    def require_credentials(self) -> "PluggySettings":
        if not self.pluggy_client_id or not self.pluggy_client_secret:
            raise MissingPluggyCredentialsError(
                "PLUGGY_CLIENT_ID and PLUGGY_CLIENT_SECRET must be configured "
                "before using Pluggy operations."
            )
        return self


class Settings(DatabaseSettings, PluggySettings):
    """Compatibility settings object for existing imports.

    New database code should prefer ``database_settings`` and Pluggy code should
    prefer ``get_pluggy_settings()`` so each integration validates only what it
    actually needs.
    """

    model_config = CONFIG_MODEL


def get_database_settings() -> DatabaseSettings:
    return DatabaseSettings()


def get_pluggy_settings() -> PluggySettings:
    return PluggySettings()


database_settings = get_database_settings()
pluggy_settings = get_pluggy_settings()
settings = Settings()
