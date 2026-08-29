"""Application configuration, loaded from environment variables."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Core
    app_name: str = "Contract Signing App"
    api_prefix: str = "/api"
    debug: bool = False

    # Database
    database_url: str = "postgresql+psycopg2://contract_app:contract_app@localhost:5432/contracts"

    # Redis / Celery
    redis_url: str = "redis://localhost:6379/0"

    # Object storage (MinIO / S3)
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "contracts"
    minio_secure: bool = False
    presigned_url_ttl_seconds: int = 300

    # Auth
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 60 * 8

    # Uploads
    max_upload_bytes: int = 50 * 1024 * 1024

    # CORS
    cors_origins: str = "http://localhost:3000,http://localhost:5173"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def s3_endpoint_url(self) -> str:
        scheme = "https" if self.minio_secure else "http"
        return f"{scheme}://{self.minio_endpoint}"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
