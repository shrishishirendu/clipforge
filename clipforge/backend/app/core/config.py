"""Application configuration. All env-driven so the transcription provider,
LLM, and storage backend stay swappable (see architecture §10)."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Core
    app_name: str = "ClipForge"
    environment: str = "development"

    # Data layer
    database_url: str = "postgresql+psycopg://clipforge:clipforge@localhost:5432/clipforge"
    redis_url: str = "redis://localhost:6379/0"

    # Object storage (S3-compatible; MinIO locally)
    s3_endpoint: str = "http://localhost:9000"
    s3_bucket: str = "clipforge-media"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"

    # AI / ML — swappable behind interfaces
    anthropic_api_key: str = ""
    segment_selection_model: str = "claude-sonnet-4-6"  # Sonnet is sufficient (NFR-02)
    transcription_provider: str = "whisper_local"  # or "deepgram", "assemblyai" (OQ-02)

    # Pipeline constraints
    default_target_min_sec: int = 180  # 3 min
    default_target_max_sec: int = 240  # 4 min
    nudge_step_sec: float = 0.5        # boundary nudge granularity (FR-15)


settings = Settings()
