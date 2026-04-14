from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    app_name: str = "NID Barcode Scanner"
    app_version: str = "3.0.0"
    log_level: str = "INFO"

    max_file_size_mb: int = 10
    timeout_seconds: int = 15
    thread_workers: int = 3
    min_image_dimension: int = 200

    allowed_extensions: frozenset[str] = frozenset({"png", "jpg", "jpeg", "webp", "bmp"})

    @property
    def max_file_size(self) -> int:
        return self.max_file_size_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()
