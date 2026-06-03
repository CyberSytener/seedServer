"""
Photo editing worker: processes jobs from queue, calls Image Edit API
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime
from typing import Optional

import httpx

from app.models.photo import PhotoContext, PhotoJobStatus
from app.services.photo.service import PhotoService
from app.services.photo.storage import PhotoStorageService
from app.infrastructure.redis.redisutil import RedisUtil

logger = logging.getLogger(__name__)


class PhotoEditWorker:
    """Worker for asynchronous photo editing"""

    def __init__(
        self,
        redis: RedisUtil,
        photo_service: PhotoService,
        storage_service: PhotoStorageService,
        image_edit_api_url: str,
        image_edit_api_key: str,
        billing_service=None,
    ):
        self.redis = redis
        self.photo_service = photo_service
        self.storage_service = storage_service
        self.image_edit_api_url = image_edit_api_url.rstrip("/")
        self.image_edit_api_key = image_edit_api_key
        self.billing_service = billing_service
        self.timeout_sec = 60
        self.max_retries = 3

    async def process_job(self, job_id: str) -> bool:
        """
        Process a single photo editing job.
        Returns True if successful, False otherwise.
        """
        try:
            logger.info(f"Starting photo edit job {job_id}")

            # Get job data
            job_data = self.redis.get_dict(f"photo_job:{job_id}")
            if not job_data:
                logger.error(f"Job data not found: {job_id}")
                return False

            user_id = job_data["user_id"]
            context = PhotoContext(job_data["context"])
            variants = job_data["variants"]
            cost_estimate = job_data["cost_estimate_usd"]

            # PHASE 4: Check user credits before processing
            if self.billing_service:
                from app.services.photo.settings import settings
                
                can_afford, reason = await self.billing_service.validate_can_afford(
                    user_id=user_id,
                    cost_usd=cost_estimate,
                    require_payment=settings.PHOTO_REQUIRE_PAYMENT,
                )
                
                if not can_afford:
                    logger.error(f"User {user_id} cannot afford job: {reason}")
                    self.photo_service.fail_job(job_id, f"Insufficient credits: {reason}")
                    return False

            # Update status: processing
            self.photo_service.update_job_status(
                job_id, PhotoJobStatus.processing, progress=10, message="Starting image processing..."
            )

            # Download original image from S3
            original_s3_key = f"uploads/{user_id}/{job_id}/original.jpg"
            
            try:
                image_bytes = await self.storage_service.download_photo(original_s3_key)
            except Exception as e:
                logger.exception(f"Failed to download original image: {str(e)}")
                self.photo_service.fail_job(job_id, f"Failed to download image: {str(e)}")
                return False

            # Build prompt based on context
            prompt = self._build_prompt(context)

            # Generate variants
            variants_data = []
            cost_actual = 0.0
            
            try:
                for variant_idx in range(variants):
                    self.photo_service.update_job_status(
                        job_id,
                        PhotoJobStatus.processing,
                        progress=20 + (variant_idx * 40),
                        message=f"Generating variant {variant_idx + 1}/{variants}...",
                    )

                    try:
                        result = await self._call_image_edit_api(
                            image_bytes, prompt, variant_idx
                        )
                        
                        # Save result to S3
                        result_s3_key = f"results/{user_id}/{job_id}/variant_{variant_idx}.jpg"
                        await self.storage_service.upload_photo(
                            result["image_bytes"],
                            job_id,
                            user_id,
                            is_original=False
                        )

                        # Generate preview URL (presigned, 1 hour expiry)
                        preview_url = self.storage_service.generate_presigned_url(
                            result_s3_key,
                            expiration_hours=1,
                            filename=f"preview_variant_{variant_idx}.jpg"
                        )

                        variant_cost = result.get("cost_usd", cost_estimate / variants)
                        variants_data.append({
                            "index": variant_idx,
                            "s3_key": result_s3_key,
                            "preview_url": preview_url,
                            "cost_usd": variant_cost,
                        })
                        cost_actual += variant_cost

                        logger.info(f"Variant {variant_idx} completed for job {job_id}")

                    except Exception as e:
                        logger.exception(f"Failed to generate variant {variant_idx}: {str(e)}")
                        self.photo_service.fail_job(job_id, f"Variant {variant_idx} failed: {str(e)}")
                        return False

                # PHASE 4: Debit actual cost from user credits
                if self.billing_service and cost_actual > 0:
                    success, new_balance = await self.billing_service.debit_user_credits(
                        user_id=user_id,
                        cost_usd=cost_actual,
                        job_id=job_id,
                        reason=f"Photo editing - {variants} variants",
                    )
                    
                    if not success:
                        logger.error(f"Failed to debit credits for user {user_id}")
                        # Refund if debit fails (job already completed)
                        await self.billing_service.refund_user_credits(
                            user_id=user_id,
                            cost_usd=cost_actual,
                            job_id=job_id,
                            reason="Debit failed - automatic refund",
                        )
                        self.photo_service.fail_job(job_id, "Failed to process payment")
                        return False

                # Mark job as done
                self.photo_service.complete_job(job_id, variants_data, cost_actual)

                logger.info(f"Completed photo job {job_id}, cost: ${cost_actual:.2f}")
                return True
                
            except Exception as e:
                logger.exception(f"Error processing variants: {str(e)}")
                self.photo_service.fail_job(job_id, f"Processing error: {str(e)}")
                return False

        except Exception as e:
            logger.exception(f"Unexpected error processing job {job_id}: {str(e)}")
            self.photo_service.fail_job(job_id, f"Processing error: {str(e)}")
            return False

    def _build_prompt(self, context: PhotoContext) -> str:
        """Build editing prompt based on context"""
        prompts = {
            PhotoContext.cv: (
                "Enhance this professional CV photo. Improve lighting, reduce shadows, "
                "brighten the face, and ensure professional appearance. "
                "Keep the original composition and pose. High quality professional result."
            ),
            PhotoContext.profile: (
                "Enhance this profile photo for social media. Improve skin tone, lighting, "
                "and overall attractiveness while maintaining natural look. "
                "Slightly soften background if needed. Make it social media ready."
            ),
            PhotoContext.linkedin: (
                "Enhance this LinkedIn profile photo. Professional appearance, "
                "good lighting, clear face details, neutral background preferred. "
                "Make it suitable for business networking. Business professional quality."
            ),
            PhotoContext.headshot: (
                "Professional headshot enhancement. Perfect lighting, skin retouching, "
                "eye enhancement. Studio-quality result expected. Commercial headshot quality."
            ),
        }
        return prompts.get(context, prompts[PhotoContext.cv])

    async def _call_image_edit_api(
        self, image_bytes: bytes, prompt: str, variant_idx: int
    ) -> dict:
        """Call Image Edit API via OpenAI adapter"""
        from app.ai_adapters import OpenAIImageEditAdapter
        from app.services.photo.settings import settings

        logger.info(f"Calling OpenAI Image Edit API (variant {variant_idx})")

        adapter = OpenAIImageEditAdapter(
            api_key=settings.openai_api_key,
            model=settings.openai_model,
            timeout_sec=settings.api_timeout_sec,
            max_retries=settings.max_api_retries,
        )

        try:
            result = await adapter.edit_image(
                image_bytes=image_bytes,
                prompt=prompt,
                size=settings.output_image_size,
                quality=settings.output_image_quality,
                variant_idx=variant_idx,
            )
            
            logger.info(
                f"AI API success (variant {variant_idx}, cost: ${result['cost_usd']:.2f})"
            )
            return result

        except Exception as e:
            logger.error(f"AI API failed (variant {variant_idx}): {str(e)}")
            raise



