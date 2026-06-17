import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    WAHA_API_KEY: str = ""
    WAHA_URL: str = "http://waha:3000"
    OPENAI_API_KEY: str = ""
    OPENAI_BASE_URL: str = ""
    OPENAI_MODEL: str = "kodeapi/claude-3-7-sonnet-20250219"
    SUPABASE_URL: str = ""
    SUPABASE_KEY: str = ""
    GEMINI_API_KEY: str = ""
    BOT_PORT: int = 8000
    REGISTRATION_SECRET: str = "DEV_RIO"

    class Config:
        env_file = ".env"

settings = Settings()
