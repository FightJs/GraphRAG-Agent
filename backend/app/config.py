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
    MEDIA_DIR: str = "./storage/media"

    # ── SPEC-TABLE ───────────────────────────────────────────
    TABLE_SUMMARY_ENABLED: bool = True
    TABLE_SUMMARY_MAX_TOKENS: int = 512
    TABLE_SUMMARY_MIN_CELLS: int = 4
    TABLE_LLM_REPAIR_ENABLED: bool = True
    TABLE_MAX_ROWS_FOR_FULL_PROMPT: int = 80

    DEEPSEEK_API_KEY: str = ""
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com/v1"
    MINERU_API_KEY: str = ""
    API_KEY_ENCRYPTION_KEY: str
    MINERU_BASE_URL: str = "https://mineru.net/api/v4"
    MINERU_LANGUAGE: str = "ch"
    MINERU_ENABLE_OCR: bool = True
    MINERU_ENABLE_TABLE: bool = True
    MINERU_ENABLE_FORMULA: bool = False
    MINERU_POLL_INTERVAL: float = 3.0
    MINERU_POLL_TIMEOUT: float = 300.0
    MINERU_SPLIT_BY: str = "page"  # page | section | full
    MINERU_CHUNK_MAX_CHARS: int = 1200
    MINERU_CHUNK_OVERLAP: int = 150
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
    OPENROUTER_EMBEDDING_MODEL: str = "qwen/qwen3-embedding-8b"
    MILVUS_URI: str = "./storage/milvus/milvus_lite.db"
    EMBEDDING_DIM: int = 4096

    # ── SPEC-IMAGE ───────────────────────────────────────────
    VLM_MODEL: str = "qwen/qwen2.5-vl-72b-instruct"
    VLM_MAX_IMAGE_SIDE: int = 1568
    VLM_MAX_IMAGES_PER_DOC: int = 40
    VLM_CONCURRENCY: int = 4
    MEDIA_ROUTE_MIN_CONFIDENCE: float = 0.55
    IMAGE_DESC_MAX_TOKENS: int = 512
    OCR_ENGINE: str = "rapidocr"
    OCR_LANG: str = "ch"
    MIN_OCR_CHARS: int = 10
    OCR_MIN_AVG_CONFIDENCE: float = 0.5
    IMAGE_MIN_SIDE_PX: int = 32
    IMAGE_MIN_AREA_PX: int = 1024

    MOCK_EXTERNAL_SERVICES: bool = False
    CORS_ORIGINS: str = "http://localhost:5173,http://localhost:3000"

    PORT: int = 8000

    def ensure_dirs(self):
        Path(self.UPLOAD_DIR).mkdir(parents=True, exist_ok=True)
        Path(self.KG_DIR).mkdir(parents=True, exist_ok=True)
        Path(self.CHUNKS_DIR).mkdir(parents=True, exist_ok=True)
        Path(self.MEDIA_DIR).mkdir(parents=True, exist_ok=True)

settings = Settings()
settings.ensure_dirs()
