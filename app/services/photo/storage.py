"""
S3 and CDN integration for photo storage and delivery

Handles:
- Upload/download from S3
- Presigned URL generation
- EXIF data removal
- Thumbnail generation
- CDN caching headers
"""

import io
import logging
from typing import Optional, Tuple
from datetime import datetime, timedelta, timezone

try:
    import boto3
    from botocore.exceptions import ClientError
except Exception:  # noqa: BLE001
    boto3 = None
    ClientError = Exception

try:
    from PIL import Image
except Exception:  # noqa: BLE001
    Image = None

logger = logging.getLogger(__name__)


class PhotoStorageService:
    """S3 and CDN storage for photo editing"""

    def __init__(self, bucket_name: str, region: str, cdn_url: str, aws_access_key: Optional[str] = None, aws_secret_key: Optional[str] = None):
        self.bucket_name = bucket_name
        self.region = region
        self.cdn_url = cdn_url.rstrip("/")

        if boto3 is None:
            raise RuntimeError("boto3 is required for PhotoStorageService")
        if Image is None:
            raise RuntimeError("pillow is required for PhotoStorageService")
        
        # Initialize S3 client with optional explicit credentials
        s3_kwargs = {"region_name": region}
        if aws_access_key and aws_secret_key:
            s3_kwargs["aws_access_key_id"] = aws_access_key
            s3_kwargs["aws_secret_access_key"] = aws_secret_key
        
        self.s3_client = boto3.client("s3", **s3_kwargs)

    async def upload_photo(
        self,
        file_bytes: bytes,
        job_id: str,
        user_id: str,
        is_original: bool = False,
    ) -> str:
        """
        Upload photo to S3 and return S3 key.
        
        Args:
            file_bytes: Image data
            job_id: Photo job ID
            user_id: User ID
            is_original: If True, preserve original; if False, remove EXIF
        
        Returns:
            S3 key (path)
        """
        try:
            if is_original:
                s3_key = f"uploads/{user_id}/{job_id}/original.jpg"
            else:
                s3_key = f"results/{user_id}/{job_id}/variant_final.jpg"
            
            # Remove EXIF data from edited photos (privacy)
            if not is_original:
                file_bytes = self._remove_exif(file_bytes)
            
            # Upload to S3
            self.s3_client.put_object(
                Bucket=self.bucket_name,
                Key=s3_key,
                Body=file_bytes,
                ContentType="image/jpeg",
                CacheControl="max-age=2592000",  # 30 days
                Metadata={
                    "job_id": job_id,
                    "user_id": user_id,
                    "uploaded_at": datetime.now(timezone.utc).isoformat(),
                    "is_original": str(is_original),
                }
            )
            
            logger.info(f"Uploaded {s3_key}, size: {len(file_bytes)} bytes")
            return s3_key
            
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code')
            logger.exception(f"S3 ClientError uploading photo: {error_code} - {str(e)}")
            raise
        except Exception as e:
            logger.exception(f"Failed to upload photo: {str(e)}")
            raise

    async def download_photo(self, s3_key: str) -> bytes:
        """Download photo from S3"""
        try:
            response = self.s3_client.get_object(
                Bucket=self.bucket_name,
                Key=s3_key
            )
            data = response['Body'].read()
            logger.info(f"Downloaded {s3_key}, size: {len(data)} bytes")
            return data
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code')
            if error_code == 'NoSuchKey':
                logger.warning(f"S3 object not found: {s3_key}")
            else:
                logger.exception(f"S3 ClientError downloading {s3_key}: {error_code}")
            raise
        except Exception as e:
            logger.exception(f"Failed to download {s3_key}: {str(e)}")
            raise

    def generate_presigned_url(
        self,
        s3_key: str,
        expiration_hours: int = 24,
        filename: Optional[str] = None,
    ) -> str:
        """
        Generate presigned download URL (S3 → CDN or direct).
        
        Args:
            s3_key: S3 object key
            expiration_hours: URL validity (default 24 hours)
            filename: Optional custom filename for download
        
        Returns:
            Presigned URL
        """
        try:
            # Generate presigned URL
            url = self.s3_client.generate_presigned_url(
                "get_object",
                Params={
                    "Bucket": self.bucket_name,
                    "Key": s3_key,
                    "ResponseContentDisposition": (
                        f'attachment; filename="{filename}"'
                        if filename else "attachment"
                    )
                },
                ExpiresIn=expiration_hours * 3600,
            )
            
            logger.info(f"Generated presigned URL for {s3_key}, valid {expiration_hours}h")
            return url
            
        except Exception as e:
            logger.exception(f"Failed to generate presigned URL: {str(e)}")
            raise

    async def generate_thumbnail(
        self,
        file_bytes: bytes,
        size: Tuple[int, int] = (200, 200),
    ) -> bytes:
        """
        Generate thumbnail for preview.
        
        Args:
            file_bytes: Original image
            size: Thumbnail size (width, height)
        
        Returns:
            Thumbnail JPEG bytes
        """
        try:
            if Image is None:
                return file_bytes
            img = Image.open(io.BytesIO(file_bytes))
            
            # Remove EXIF
            img = img.convert('RGB')
            
            # Resize with aspect ratio preservation
            img.thumbnail(size, Image.Resampling.LANCZOS)
            
            # Create canvas and paste
            thumb = Image.new('RGB', size, (255, 255, 255))
            offset = ((size[0] - img.width) // 2, (size[1] - img.height) // 2)
            thumb.paste(img, offset)
            
            # Save as JPEG
            output = io.BytesIO()
            thumb.save(output, format='JPEG', quality=85)
            return output.getvalue()
            
        except Exception as e:
            logger.exception(f"Failed to generate thumbnail: {str(e)}")
            return file_bytes  # Return original if thumbnail fails

    def _remove_exif(self, file_bytes: bytes) -> bytes:
        """
        Remove all EXIF data from image (privacy).
        Removes: GPS, camera info, timestamps, owner name, etc.
        """
        try:
            # Load image
            img = Image.open(io.BytesIO(file_bytes))
            
            # Convert to RGB if needed (e.g., PNG with alpha)
            if img.mode in ("RGBA", "LA", "P"):
                img = img.convert("RGB")
            
            # Create new image without EXIF (copy pixel data only)
            data = list(img.getdata())
            image_without_exif = Image.new(img.mode, img.size)
            image_without_exif.putdata(data)
            
            # Save without EXIF
            output = io.BytesIO()
            image_without_exif.save(output, format='JPEG', quality=95, optimize=True)
            
            result_bytes = output.getvalue()
            logger.info(f"Removed EXIF data from image (original: {len(file_bytes)}, cleaned: {len(result_bytes)} bytes)")
            return result_bytes
            
        except Exception as e:
            logger.warning(f"Failed to remove EXIF (returning original): {str(e)}")
            return file_bytes  # Return original if EXIF removal fails

    async def delete_photo(self, s3_key: str, also_variants: bool = False):
        """
        Delete photo from S3 (GDPR).
        
        Args:
            s3_key: S3 object key
            also_variants: If True, delete all variants for this job
        """
        try:
            if also_variants:
                # Delete entire job folder (all variants)
                prefix = s3_key.rsplit('/', 1)[0]  # Get folder path
                
                response = self.s3_client.list_objects_v2(
                    Bucket=self.bucket_name,
                    Prefix=prefix
                )
                
                deleted_count = 0
                if 'Contents' in response:
                    for obj in response['Contents']:
                        try:
                            self.s3_client.delete_object(
                                Bucket=self.bucket_name,
                                Key=obj['Key']
                            )
                            deleted_count += 1
                        except ClientError as e:
                            logger.warning(f"Failed to delete {obj['Key']}: {str(e)}")
                    logger.info(f"Deleted {deleted_count} files from {prefix}")
            else:
                # Delete single file
                self.s3_client.delete_object(
                    Bucket=self.bucket_name,
                    Key=s3_key
                )
                logger.info(f"Deleted {s3_key}")
                
        except ClientError as e:
            logger.exception(f"S3 ClientError deleting photo: {str(e)}")
            raise
        except Exception as e:
            logger.exception(f"Failed to delete photo: {str(e)}")
            raise

    async def get_object_metadata(self, s3_key: str) -> dict:
        """Get S3 object metadata (size, modified date, etc.)"""
        try:
            response = self.s3_client.head_object(
                Bucket=self.bucket_name,
                Key=s3_key
            )
            return {
                'size_bytes': response.get('ContentLength', 0),
                'modified_at': response.get('LastModified'),
                'content_type': response.get('ContentType'),
                'metadata': response.get('Metadata', {})
            }
        except ClientError as e:
            if e.response.get('Error', {}).get('Code') == '404':
                logger.warning(f"S3 object not found: {s3_key}")
                return {}
            logger.exception(f"Failed to get metadata for {s3_key}: {str(e)}")
            return {}

    def cleanup_old_jobs(self, days: int = 30):
        """
        Delete old photo jobs (retention policy).
        Runs daily to clean up photos older than retention period.
        """
        try:
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)
            
            # List all objects
            paginator = self.s3_client.get_paginator('list_objects_v2')
            pages = paginator.paginate(Bucket=self.bucket_name, Prefix="uploads/")
            
            deleted_count = 0
            for page in pages:
                if 'Contents' not in page:
                    continue
                    
                for obj in page['Contents']:
                    if obj['LastModified'] < cutoff_date:
                        try:
                            self.s3_client.delete_object(
                                Bucket=self.bucket_name,
                                Key=obj['Key']
                            )
                            deleted_count += 1
                        except ClientError as e:
                            logger.warning(f"Failed to delete old object {obj['Key']}: {str(e)}")
            
            logger.info(f"Cleanup: Deleted {deleted_count} old photos (>{days} days)")
            
        except ClientError as e:
            logger.exception(f"S3 ClientError during cleanup: {str(e)}")
        except Exception as e:
            logger.exception(f"Cleanup failed: {str(e)}")


# Example usage in worker:
"""
# In photo_worker.py, update _download_from_s3 and _upload_to_s3:

storage = PhotoStorageService(
    bucket_name="seed-photos",
    region="us-east-1",
    cdn_url="https://cdn.seed.example.com"
)

async def _download_from_s3(self, s3_key: str) -> Optional[bytes]:
    return await storage.download_photo(s3_key)

async def _upload_to_s3(self, s3_key: str, file_bytes: bytes) -> str:
    await storage.upload_photo(file_bytes, job_id, user_id)
    
    # Generate presigned URL for preview
    thumbnail = await storage.generate_thumbnail(file_bytes)
    await storage.upload_photo(thumbnail, job_id, user_id)
    
    return storage.generate_presigned_url(s3_key, expiration_hours=1)
"""
