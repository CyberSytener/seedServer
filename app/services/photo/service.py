"""
Photo editing service: validation, face detection, DB operations
"""
from __future__ import annotations

import io
import logging
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

try:
    import cv2
except Exception:  # noqa: BLE001
    cv2 = None

try:
    import numpy as np
except Exception:  # noqa: BLE001
    np = None
try:
    from PIL import Image
except Exception:  # noqa: BLE001
    Image = None

from app.infrastructure.db.sqlite import get_db
from app.models.photo import PhotoContext, PhotoJobStatus
from app.infrastructure.redis.redisutil import RedisUtil

logger = logging.getLogger(__name__)

# Face detection cascade (Haar Cascade)
FACE_CASCADE_PATH = str(Path(__file__).parent.parent / "data" / "haarcascade_frontalface_default.xml")


class PhotoValidationError(Exception):
    """Photo validation failed"""
    pass


class PhotoService:
    """Service for photo editing operations"""

    def __init__(self, redis: RedisUtil):
        self.redis = redis
        self.min_image_size = 600  # pixels
        self.max_file_size = 8 * 1024 * 1024  # 8MB
        self.face_cascade = None
        if cv2 is not None:
            self.face_cascade = cv2.CascadeClassifier(FACE_CASCADE_PATH)

    def validate_photo(self, file_bytes: bytes) -> dict:
        """
        Validate photo: format, size, face detection.
        Returns: { 'valid': bool, 'error': str, 'faces': int, 'image_shape': (h, w) }
        """
        try:
            if Image is None:
                raise PhotoValidationError("Photo validation unavailable: missing pillow")
            if cv2 is None or np is None or self.face_cascade is None:
                raise PhotoValidationError("Photo validation unavailable: missing cv2 or numpy")
            # Check file size
            if len(file_bytes) > self.max_file_size:
                raise PhotoValidationError(f"File too large: {len(file_bytes)} > {self.max_file_size}")

            # Check format and load
            try:
                img = Image.open(io.BytesIO(file_bytes))
                if img.format not in ("JPEG", "PNG"):
                    raise PhotoValidationError(f"Invalid format: {img.format}. Use JPEG or PNG.")
            except Exception as e:
                raise PhotoValidationError(f"Failed to open image: {str(e)}")

            # Check dimensions
            h, w = img.size[::-1]  # PIL uses (w, h)
            if min(h, w) < self.min_image_size:
                raise PhotoValidationError(
                    f"Image too small: {h}x{w}. Minimum {self.min_image_size}px."
                )

            # Convert to OpenCV format for face detection
            cv_img = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)

            # Detect faces
            faces = self.face_cascade.detectMultiScale(
                cv_img, scaleFactor=1.3, minNeighbors=4, minSize=(30, 30)
            )

            if len(faces) == 0:
                raise PhotoValidationError("No face detected in image.")
            if len(faces) > 1:
                raise PhotoValidationError(
                    f"Multiple faces detected ({len(faces)}). Please provide a single portrait."
                )

            logger.info(f"Photo validation passed: {h}x{w}, 1 face")
            return {"valid": True, "faces": 1, "image_shape": (h, w)}

        except PhotoValidationError as e:
            logger.warning(f"Photo validation failed: {str(e)}")
            return {"valid": False, "error": str(e), "faces": 0}
        except Exception as e:
            logger.exception(f"Unexpected error in photo validation: {str(e)}")
            return {"valid": False, "error": f"Validation error: {str(e)}", "faces": 0}

    def create_photo_job(
        self,
        user_id: str,
        context: PhotoContext,
        variants: int,
        cost_estimate_usd: float,
    ) -> str:
        """
        Create a photo editing job record.
        Returns job_id.
        """
        job_id = str(uuid.uuid4())
        job_data = {
            "job_id": job_id,
            "user_id": user_id,
            "context": context.value,
            "status": PhotoJobStatus.queued.value,
            "variants": variants,
            "progress": 0,
            "cost_estimate_usd": cost_estimate_usd,
            "cost_actual_usd": 0.0,
            "confirmed": False,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "completed_at": None,
            "preview_url": None,
            "variants_data": [],
            "message": "",
        }

        # Store in Redis (TTL 30 days)
        self.redis.set_dict(f"photo_job:{job_id}", job_data, ttl_seconds=30 * 24 * 60 * 60)

        # Also store in DB for persistence
        db = get_db()
        db.execute(
            """
            INSERT INTO photo_jobs (job_id, user_id, context, status, variants, cost_estimate_usd, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (job_id, user_id, context.value, PhotoJobStatus.queued.value, variants, cost_estimate_usd, job_data["created_at"]),
        )
        db.commit()

        logger.info(f"Created photo job {job_id} for user {user_id}, context={context}")
        return job_id

    def get_photo_job(self, job_id: str, user_id: str) -> Optional[dict]:
        """
        Get photo job details. Checks permission (user_id must match).
        """
        data = self.redis.get_dict(f"photo_job:{job_id}")
        if not data:
            # Fallback to DB
            db = get_db()
            row = db.execute(
                "SELECT * FROM photo_jobs WHERE job_id = ? AND user_id = ?",
                (job_id, user_id),
            ).fetchone()
            if row:
                # Reconstruct from DB and cache
                data = dict(row)
                self.redis.set_dict(f"photo_job:{job_id}", data, ttl_seconds=30 * 24 * 60 * 60)
                return data
            return None

        # Check permission
        if data.get("user_id") != user_id:
            logger.warning(f"Unauthorized access attempt: job {job_id}, user {user_id}")
            return None

        return data

    def update_job_status(self, job_id: str, status: PhotoJobStatus, progress: int = 0, message: str = ""):
        """Update job status in Redis and DB"""
        data = self.redis.get_dict(f"photo_job:{job_id}")
        if data:
            data["status"] = status.value
            data["progress"] = progress
            if message:
                data["message"] = message
            self.redis.set_dict(f"photo_job:{job_id}", data, ttl_seconds=30 * 24 * 60 * 60)

        db = get_db()
        db.execute(
            "UPDATE photo_jobs SET status = ?, progress = ?, updated_at = ? WHERE job_id = ?",
            (status.value, progress, datetime.now(timezone.utc).isoformat(), job_id),
        )
        db.commit()

    def complete_job(self, job_id: str, variants_data: list, cost_actual_usd: float):
        """Mark job as done with variants"""
        data = self.redis.get_dict(f"photo_job:{job_id}")
        if data:
            data["status"] = PhotoJobStatus.done.value
            data["progress"] = 100
            data["variants_data"] = variants_data
            data["cost_actual_usd"] = cost_actual_usd
            data["completed_at"] = datetime.now(timezone.utc).isoformat()
            self.redis.set_dict(f"photo_job:{job_id}", data, ttl_seconds=30 * 24 * 60 * 60)

        db = get_db()
        db.execute(
            """
            UPDATE photo_jobs SET status = ?, progress = ?, cost_actual_usd = ?, 
                                  completed_at = ?, updated_at = ? WHERE job_id = ?
            """,
            (
                PhotoJobStatus.done.value,
                100,
                cost_actual_usd,
                datetime.now(timezone.utc).isoformat(),
                datetime.now(timezone.utc).isoformat(),
                job_id,
            ),
        )
        db.commit()

    def fail_job(self, job_id: str, error_message: str):
        """Mark job as failed"""
        data = self.redis.get_dict(f"photo_job:{job_id}")
        if data:
            data["status"] = PhotoJobStatus.failed.value
            data["progress"] = 0
            data["message"] = error_message
            data["completed_at"] = datetime.now(timezone.utc).isoformat()
            self.redis.set_dict(f"photo_job:{job_id}", data, ttl_seconds=30 * 24 * 60 * 60)

        db = get_db()
        db.execute(
            """
            UPDATE photo_jobs SET status = ?, message = ?, completed_at = ?, updated_at = ? 
            WHERE job_id = ?
            """,
              (PhotoJobStatus.failed.value, error_message, datetime.now(timezone.utc).isoformat(),
               datetime.now(timezone.utc).isoformat(), job_id),
        )
        db.commit()

    def confirm_job(self, job_id: str, user_id: str, variant_index: int, cost_charged_usd: float) -> bool:
        """Mark job as confirmed (payment processed)"""
        data = self.redis.get_dict(f"photo_job:{job_id}")
        if not data or data.get("user_id") != user_id:
            return False

        data["confirmed"] = True
        data["cost_actual_usd"] = cost_charged_usd
        self.redis.set_dict(f"photo_job:{job_id}", data, ttl_seconds=30 * 24 * 60 * 60)

        db = get_db()
        db.execute(
            "UPDATE photo_jobs SET confirmed = 1, cost_actual_usd = ?, updated_at = ? WHERE job_id = ?",
            (cost_charged_usd, datetime.now(timezone.utc).isoformat(), job_id),
        )
        db.commit()
        return True

    def delete_job(self, job_id: str, user_id: str) -> bool:
        """Delete job and associated files (GDPR)"""
        data = self.redis.get_dict(f"photo_job:{job_id}")
        if not data or data.get("user_id") != user_id:
            return False

        # Remove from Redis
        self.redis.delete(f"photo_job:{job_id}")

        # Mark as cancelled in DB
        db = get_db()
        db.execute(
            "UPDATE photo_jobs SET status = ? WHERE job_id = ?",
            (PhotoJobStatus.cancelled.value, job_id),
        )
        db.commit()

        logger.info(f"Deleted photo job {job_id} for user {user_id} (GDPR request)")
        return True

    def list_user_jobs(self, user_id: str, skip: int = 0, limit: int = 20, status: Optional[str] = None) -> dict:
        """List user's photo jobs"""
        db = get_db()
        query = "SELECT * FROM photo_jobs WHERE user_id = ?"
        params = [user_id]

        if status:
            query += " AND status = ?"
            params.append(status)

        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, skip])

        rows = db.execute(query, params).fetchall()
        total = db.execute(
            "SELECT COUNT(*) as cnt FROM photo_jobs WHERE user_id = ?" + (f" AND status = ?" if status else ""),
            params[:-2],
        ).fetchone()[0]

        jobs = [dict(row) for row in rows]
        return {"total": total, "jobs": jobs}



