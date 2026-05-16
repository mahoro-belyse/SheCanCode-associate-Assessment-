from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # App
    APP_TITLE: str = "IgirePay Idempotency Gateway"
    APP_VERSION: str = "1.0.0"
    APP_ENV: str = "development"          # development | production

    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    RELOAD: bool = True                   # set False in production

    # Processing
    PROCESSING_DELAY_SECONDS: float = 2.0

    # Idempotency
    KEY_TTL_SECONDS: int = 86_400         # 24 hours

    # Rate limiting
    RATE_LIMIT_MAX: int = 10
    RATE_LIMIT_WINDOW_SECONDS: int = 60

    # Read from .env file automatically
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


# Single instance used across the app
settings = Settings()
