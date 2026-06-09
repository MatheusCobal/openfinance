from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    pluggy_client_id: Optional[str] = None
    pluggy_client_secret: Optional[str] = None
    pluggy_base_url: str = "https://api.pluggy.ai"
    database_url: str = "sqlite:///./openfinance.db"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
