from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    
    APP_TITLE: str = "IgirePay Idempotency Gateway"
    APP_VERSION: str = "1.0.0"
    APP_ENV: str = "development"          

    
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    RELOAD: bool = True                   

    
    PROCESSING_DELAY_SECONDS: float = 2.0

    
    KEY_TTL_SECONDS: int = 86_400         

    
    RATE_LIMIT_MAX: int = 10
    RATE_LIMIT_WINDOW_SECONDS: int = 60

    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )



settings = Settings()
