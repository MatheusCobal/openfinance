from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    pluggy_client_id: str
    pluggy_client_secret: str
    pluggy_base_url: str = "https://api.pluggy.ai"
    database_url: str = "sqlite:///./openfinance.db"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
