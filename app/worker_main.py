"""
Photo Editing Worker Entry Point
Async job processor for handling photo editing tasks from Redis queue
"""
import asyncio
import logging
import sys
from typing import Optional

import redis.asyncio as redis
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from app.services.photo.worker import PhotoEditingWorker
from app.services.photo.storage import PhotoStorageService
from app.ai_adapters import OpenAIImageEditAdapter
from app.billing_service import PhotoBillingService
from app.services.photo.settings import PhotoSettings

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class WorkerService:
    """Manages worker lifecycle and dependencies"""
    
    def __init__(self):
        self.settings = PhotoSettings()
        self.redis_client: Optional[redis.Redis] = None
        self.db_engine = None
        self.db_session_maker = None
        self.storage_service = None
        self.ai_adapter = None
        self.billing_service = None
        self.worker = None
    
    async def initialize(self):
        """Initialize all services"""
        logger.info("Initializing worker services...")
        
        # Redis connection
        self.redis_client = await redis.from_url(
            self.settings.REDIS_URL,
            encoding="utf8",
            decode_responses=True
        )
        logger.info(f"Connected to Redis: {self.settings.REDIS_URL}")
        
        # Database connection
        engine_url = self.settings.DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://")
        self.db_engine = create_async_engine(engine_url, echo=False)
        self.db_session_maker = sessionmaker(
            self.db_engine,
            class_=AsyncSession,
            expire_on_commit=False
        )
        logger.info(f"Connected to database: {engine_url}")
        
        # Initialize services
        self.storage_service = PhotoStorageService(settings=self.settings)
        self.ai_adapter = OpenAIImageEditAdapter(settings=self.settings)
        self.billing_service = PhotoBillingService(
            session_factory=self.db_session_maker,
            settings=self.settings
        )
        
        # Create worker
        self.worker = PhotoEditingWorker(
            redis_client=self.redis_client,
            session_factory=self.db_session_maker,
            storage_service=self.storage_service,
            ai_adapter=self.ai_adapter,
            billing_service=self.billing_service,
            settings=self.settings
        )
        
        logger.info("Worker services initialized successfully")
    
    async def cleanup(self):
        """Clean up resources"""
        logger.info("Cleaning up worker services...")
        
        if self.redis_client:
            await self.redis_client.close()
        
        if self.db_engine:
            await self.db_engine.dispose()
        
        logger.info("Cleanup completed")
    
    async def run(self):
        """Run the worker"""
        try:
            await self.initialize()
            logger.info(
                f"Starting worker with {self.settings.WORKER_CONCURRENCY} concurrent jobs"
            )
            await self.worker.process_jobs(
                concurrency=self.settings.WORKER_CONCURRENCY
            )
        except KeyboardInterrupt:
            logger.info("Worker interrupted by user")
        except Exception as e:
            logger.error(f"Worker error: {e}", exc_info=True)
            sys.exit(1)
        finally:
            await self.cleanup()


async def main():
    """Main entry point"""
    service = WorkerService()
    await service.run()


if __name__ == "__main__":
    asyncio.run(main())

