from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    SECRET_KEY: str = "dev-secret-key-please-change-in-production-32chars!!"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    DATABASE_URL: str = "sqlite+aiosqlite:///./graphrag.db"
    UPLOAD_DIR: str = "./storage/uploads"
    KG_DIR: str = "./storage/kg"
    CHUNKS_DIR: str = "./storage/chunks"

    DEEPSEEK_API_KEY: str = ""
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com/v1"
    MINERU_API_KEY: str = ""
    API_KEY_ENCRYPTION_KEY: str
    MINERU_BASE_URL: str = "https://mineru.net/api/v4"
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
    OPENROUTER_EMBEDDING_MODEL: str = "qwen/qwen3-embedding-8b"

    PORT: int = 8000

    def ensure_dirs(self):
        Path(self.UPLOAD_DIR).mkdir(parents=True, exist_ok=True)
        Path(self.KG_DIR).mkdir(parents=True, exist_ok=True)
        Path(self.CHUNKS_DIR).mkdir(parents=True, exist_ok=True)

settings = Settings()
settings.ensure_dirs()
