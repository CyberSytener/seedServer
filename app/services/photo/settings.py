"""
Settings for photo editing feature
Extended settings for S3, AI provider, and billing
"""

import os
from typing import Optional


class PhotoEditingSettings:
    """Photo editing configuration"""

    # Feature toggle
    PHOTO_EDIT_ENABLED: bool = os.getenv("PHOTO_EDIT_ENABLED", "true").lower() == "true"

    # File validation
    PHOTO_MAX_FILE_SIZE: int = int(os.getenv("PHOTO_MAX_FILE_SIZE", "8388608"))  # 8MB
    PHOTO_MIN_IMAGE_SIZE: int = int(os.getenv("PHOTO_MIN_IMAGE_SIZE", "600"))

    # Processing
    PHOTO_RETENTION_DAYS: int = int(os.getenv("PHOTO_RETENTION_DAYS", "30"))
    PHOTO_VARIANTS_MAX: int = int(os.getenv("PHOTO_VARIANTS_MAX", "3"))
    PHOTO_COST_PER_VARIANT: float = float(os.getenv("PHOTO_COST_PER_VARIANT", "0.5"))

    # AI Provider
    IMAGE_EDIT_API_URL: str = os.getenv("IMAGE_EDIT_API_URL", "https://api.openai.com")
    IMAGE_EDIT_API_KEY: str = os.getenv("IMAGE_EDIT_API_KEY", "")
    IMAGE_EDIT_TIMEOUT_SEC: int = int(os.getenv("IMAGE_EDIT_TIMEOUT_SEC", "60"))
    IMAGE_EDIT_MAX_RETRIES: int = int(os.getenv("IMAGE_EDIT_MAX_RETRIES", "3"))

    # OpenAI Configuration
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "dall-e-3")  # or "dall-e-2"
    API_TIMEOUT_SEC: int = int(os.getenv("API_TIMEOUT_SEC", "60"))
    MAX_API_RETRIES: int = int(os.getenv("MAX_API_RETRIES", "3"))
    OUTPUT_IMAGE_SIZE: str = os.getenv("OUTPUT_IMAGE_SIZE", "1024x1024")
    OUTPUT_IMAGE_QUALITY: str = os.getenv("OUTPUT_IMAGE_QUALITY", "standard")  # "standard" or "hd"

    # AWS S3
    AWS_S3_BUCKET: str = os.getenv("AWS_S3_BUCKET", "seed-photos")
    AWS_REGION: str = os.getenv("AWS_REGION", "us-east-1")
    AWS_ACCESS_KEY_ID: Optional[str] = os.getenv("AWS_ACCESS_KEY_ID")
    AWS_SECRET_ACCESS_KEY: Optional[str] = os.getenv("AWS_SECRET_ACCESS_KEY")

    # CDN
    CDN_BASE_URL: str = os.getenv("CDN_BASE_URL", "https://cdn.seed.example.com")
    CDN_PRESIGNED_URL_EXPIRY_HOURS: int = int(os.getenv("CDN_PRESIGNED_URL_EXPIRY_HOURS", "24"))

    # Queue
    PHOTO_QUEUE_NAME: str = os.getenv("PHOTO_QUEUE_NAME", "photo_editing")
    PHOTO_WORKER_CONCURRENCY: int = int(os.getenv("PHOTO_WORKER_CONCURRENCY", "4"))

    # Billing
    PHOTO_REQUIRE_PAYMENT: bool = os.getenv("PHOTO_REQUIRE_PAYMENT", "false").lower() == "true"
    PHOTO_WATERMARK_UNTIL_PAID: bool = os.getenv("PHOTO_WATERMARK_UNTIL_PAID", "true").lower() == "true"

    # Monitoring
    PHOTO_ENABLE_METRICS: bool = os.getenv("PHOTO_ENABLE_METRICS", "true").lower() == "true"
    PHOTO_LOG_LEVEL: str = os.getenv("PHOTO_LOG_LEVEL", "INFO")
