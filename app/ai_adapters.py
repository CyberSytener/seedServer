"""
OpenAI Image Edit API Adapter

Handles:
- Image editing via OpenAI's API
- Retry logic with exponential backoff
- Cost tracking
- Error handling
- Rate limiting
"""

import asyncio
import base64
import io
import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


class OpenAIImageEditAdapter:
    """Adapter for OpenAI Image Edit API"""

    def __init__(
        self,
        api_key: str,
        api_url: str = "https://api.openai.com",
        model: str = "dall-e-3",  # or "dall-e-2"
        timeout_sec: int = 60,
        max_retries: int = 3,
    ):
        self.api_key = api_key
        self.api_url = api_url.rstrip("/")
        self.model = model
        self.timeout_sec = timeout_sec
        self.max_retries = max_retries
        self.base_cost_usd = 0.02  # Approximate cost per image (varies by model)

    async def edit_image(
        self,
        image_bytes: bytes,
        prompt: str,
        size: str = "1024x1024",
        quality: str = "standard",
        variant_idx: int = 0,
    ) -> dict:
        """
        Edit image using OpenAI API.
        
        Args:
            image_bytes: Original image data
            prompt: Edit prompt
            size: Output size (1024x1024, 1024x1792, 1792x1024)
            quality: "standard" or "hd"
            variant_idx: Variant index for logging
        
        Returns:
            {
                "image_bytes": bytes,
                "cost_usd": float,
                "api_response": dict,
            }
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
        }

        # Convert image to base64
        image_b64 = base64.b64encode(image_bytes).decode("utf-8")

        payload = {
            "model": self.model,
            "prompt": prompt,
            "image": image_b64,
            "n": 1,
            "size": size,
            "quality": quality,
            "response_format": "url",  # Return URL instead of base64
        }

        for attempt in range(self.max_retries):
            try:
                logger.info(
                    f"Calling OpenAI Image Edit API (attempt {attempt + 1}/{self.max_retries}, "
                    f"variant {variant_idx})"
                )

                async with httpx.AsyncClient(timeout=self.timeout_sec) as client:
                    response = await client.post(
                        f"{self.api_url}/v1/images/edits",
                        json=payload,
                        headers=headers,
                    )

                    if response.status_code == 429:
                        # Rate limited - exponential backoff
                        wait_time = 2 ** attempt
                        logger.warning(
                            f"Rate limited (429). Waiting {wait_time}s before retry..."
                        )
                        await asyncio.sleep(wait_time)
                        continue

                    if response.status_code == 401:
                        raise Exception(f"Unauthorized (401): Invalid API key")

                    if response.status_code != 200:
                        raise Exception(
                            f"HTTP {response.status_code}: {response.text}"
                        )

                    result = response.json()
                    edited_image_url = result.get("data", [{}])[0].get("url")

                    if not edited_image_url:
                        raise Exception("No image URL in response")

                    # Download edited image
                    logger.info(f"Downloaded edited image from {edited_image_url[:50]}...")
                    async with httpx.AsyncClient() as img_client:
                        img_response = await img_client.get(edited_image_url, timeout=30)
                        img_response.raise_for_status()

                    # Calculate cost (approximate)
                    # DALL-E 3: $0.08/image (1024x1024), $0.12/image (1024x1792 or 1792x1024)
                    # DALL-E 2: $0.02/image
                    cost_usd = self._estimate_cost(size, quality)

                    logger.info(
                        f"OpenAI Image Edit succeeded (variant {variant_idx}, "
                        f"cost: ${cost_usd:.2f})"
                    )

                    return {
                        "image_bytes": img_response.content,
                        "cost_usd": cost_usd,
                        "api_response": result,
                        "model_used": self.model,
                        "size": size,
                    }

            except asyncio.TimeoutError:
                logger.warning(f"Timeout on attempt {attempt + 1}")
                if attempt < self.max_retries - 1:
                    wait_time = 2 ** attempt
                    await asyncio.sleep(wait_time)
                else:
                    raise Exception("OpenAI API call timeout after all retries")

            except Exception as e:
                error_msg = str(e)
                logger.error(f"Attempt {attempt + 1} failed: {error_msg}")

                if attempt < self.max_retries - 1:
                    wait_time = 2 ** attempt
                    logger.info(f"Retrying in {wait_time}s...")
                    await asyncio.sleep(wait_time)
                else:
                    raise

        raise Exception(f"Failed after {self.max_retries} retries")

    def _estimate_cost(self, size: str, quality: str) -> float:
        """Estimate API cost based on size and quality"""
        # DALL-E 3 pricing
        if self.model == "dall-e-3":
            if quality == "hd":
                if size == "1024x1024":
                    return 0.08
                else:  # 1024x1792 or 1792x1024
                    return 0.12
            else:  # standard
                if size == "1024x1024":
                    return 0.04
                else:
                    return 0.06

        # DALL-E 2 pricing
        elif self.model == "dall-e-2":
            if size == "1024x1024":
                return 0.02
            elif size == "512x512":
                return 0.018
            else:
                return 0.02

        # Default fallback
        return self.base_cost_usd

    async def batch_edit_images(
        self,
        image_bytes: bytes,
        prompt: str,
        num_variants: int = 2,
        size: str = "1024x1024",
    ) -> list:
        """Edit image multiple times to generate variants"""
        results = []
        
        for i in range(num_variants):
            try:
                result = await self.edit_image(
                    image_bytes=image_bytes,
                    prompt=prompt,
                    size=size,
                    variant_idx=i,
                )
                results.append(result)
            except Exception as e:
                logger.error(f"Failed to generate variant {i}: {str(e)}")
                raise

        return results


class GeminiImageEditAdapter:
    """Adapter for Google Gemini Vision API (image understanding + generation)"""

    def __init__(
        self,
        api_key: str,
        api_url: str = "https://generativelanguage.googleapis.com",
        model: str = "gemini-pro-vision",
        timeout_sec: int = 60,
        max_retries: int = 3,
    ):
        self.api_key = api_key
        self.api_url = api_url.rstrip("/")
        self.model = model
        self.timeout_sec = timeout_sec
        self.max_retries = max_retries

    async def edit_image(
        self,
        image_bytes: bytes,
        prompt: str,
        variant_idx: int = 0,
    ) -> dict:
        """
        Edit image using Gemini Vision API.

        Not yet implemented — Gemini does not expose a direct image-editing
        endpoint.  Use the OpenAI adapter or integrate Google Imagen when
        available.
        """
        raise NotImplementedError(
            "GeminiImageEditAdapter.edit_image is not implemented. "
            "Use OpenAIImageEditAdapter or integrate the Imagen API."
        )
