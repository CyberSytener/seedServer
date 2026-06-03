"""
Billing & Credits Service for Photo Editing

Handles:
- Credit checking before processing
- Cost debit after completion
- Payment blocking on insufficient funds
- Watermarking for unpaid images
- Credit transaction history
"""

import logging
from datetime import datetime
from typing import Optional
from enum import Enum

from sqlalchemy import create_engine, Column, String, Float, DateTime, Text, Integer, Enum as SQLEnum
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

logger = logging.getLogger(__name__)

Base = declarative_base()


class TransactionType(str, Enum):
    """Types of credit transactions"""
    DEBIT = "debit"  # User spent credits
    REFUND = "refund"  # Refund for failed job
    CREDIT = "credit"  # Admin credit
    PURCHASE = "purchase"  # User purchased credits


class PhotoCreditTransaction(Base):
    """Database model for credit transactions"""
    __tablename__ = "photo_credit_transactions"

    id = Column(String(36), primary_key=True)
    user_id = Column(String(36), nullable=False, index=True)
    job_id = Column(String(36), nullable=True, index=True)
    amount = Column(Float, nullable=False)  # Credit amount (can be negative for debit)
    transaction_type = Column(SQLEnum(TransactionType), nullable=False)
    reason = Column(Text)
    balance_before = Column(Float)  # User's balance before transaction
    balance_after = Column(Float)  # User's balance after transaction
    api_cost_usd = Column(Float, nullable=True)  # Cost in USD (for reporting)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    def __repr__(self):
        return (
            f"PhotoCreditTransaction(user_id={self.user_id}, job_id={self.job_id}, "
            f"amount={self.amount}, type={self.transaction_type}, "
            f"balance_before={self.balance_before}, balance_after={self.balance_after})"
        )


class PhotoBillingService:
    """Manages photo editing billing and credits"""

    def __init__(self, seed_db_session, credits_price_per_dollar: float = 100.0):
        """
        Args:
            seed_db_session: SQLAlchemy session for transaction logging
            credits_price_per_dollar: How many credits = $1 USD
        """
        self.db_session = seed_db_session
        self.credits_per_dollar = credits_price_per_dollar

    def usd_to_credits(self, usd_amount: float) -> float:
        """Convert USD cost to credits"""
        return usd_amount * self.credits_per_dollar

    def credits_to_usd(self, credits: float) -> float:
        """Convert credits to USD"""
        return credits / self.credits_per_dollar

    async def check_user_credits(self, user_id: str) -> float:
        """
        Get current user credit balance.
        
        Fetches from Seed's existing user system.
        Returns: Credit balance (can be 0 or negative if overdrawn)
        """
        from app.services.photo.integration import get_seed_user_service

        try:
            user_service = get_seed_user_service()
            user = user_service.get_user(user_id)
            
            if not user:
                logger.warning(f"User not found: {user_id}")
                return 0.0
            
            # Assume Seed user has a 'credits' field or similar
            # Adjust based on actual Seed schema
            balance = getattr(user, "credits", 0.0)
            logger.info(f"User {user_id} credit balance: {balance}")
            return balance
            
        except Exception as e:
            logger.error(f"Failed to check user credits: {str(e)}")
            raise

    async def validate_can_afford(
        self,
        user_id: str,
        cost_usd: float,
        require_payment: bool = True,
    ) -> tuple[bool, str]:
        """
        Check if user can afford the job.
        
        Args:
            user_id: User ID
            cost_usd: Estimated cost in USD
            require_payment: If False, always allow (for free tier)
        
        Returns:
            (can_afford: bool, reason: str)
        """
        if not require_payment:
            logger.info(f"Payment not required (free tier or admin override)")
            return True, "Free tier"

        try:
            balance = await self.check_user_credits(user_id)
            required_credits = self.usd_to_credits(cost_usd)

            if balance < required_credits:
                reason = (
                    f"Insufficient credits. "
                    f"Required: {required_credits:.0f}, "
                    f"Available: {balance:.0f}"
                )
                logger.warning(f"User {user_id}: {reason}")
                return False, reason

            logger.info(
                f"User {user_id} can afford job (balance: {balance:.0f}, "
                f"required: {required_credits:.0f})"
            )
            return True, "OK"

        except Exception as e:
            error_msg = f"Failed to validate credits: {str(e)}"
            logger.error(error_msg)
            return False, error_msg

    async def debit_user_credits(
        self,
        user_id: str,
        cost_usd: float,
        job_id: str,
        reason: str = "Photo editing service",
    ) -> tuple[bool, float]:
        """
        Debit user credits for a completed job.
        
        Args:
            user_id: User ID
            cost_usd: Cost in USD
            job_id: Photo job ID (for tracking)
            reason: Transaction description
        
        Returns:
            (success: bool, new_balance: float)
        """
        try:
            credits_to_debit = self.usd_to_credits(cost_usd)
            
            # Get current balance before debit
            balance_before = await self.check_user_credits(user_id)
            
            # Update user credits in Seed system
            from app.services.photo.integration import get_seed_user_service
            
            user_service = get_seed_user_service()
            user = user_service.get_user(user_id)
            
            if not user:
                logger.error(f"User not found for debit: {user_id}")
                return False, 0.0
            
            # Update credits (negative for debit)
            new_balance = max(0.0, balance_before - credits_to_debit)  # Don't go below 0
            user.credits = new_balance
            user_service.update_user(user)
            
            # Log transaction
            self._log_transaction(
                user_id=user_id,
                job_id=job_id,
                amount=-credits_to_debit,
                transaction_type=TransactionType.DEBIT,
                reason=reason,
                balance_before=balance_before,
                balance_after=new_balance,
                api_cost_usd=cost_usd,
            )
            
            logger.info(
                f"Debited {credits_to_debit:.0f} credits from {user_id} "
                f"(${cost_usd:.2f}), new balance: {new_balance:.0f}"
            )
            return True, new_balance

        except Exception as e:
            logger.error(f"Failed to debit credits: {str(e)}")
            return False, 0.0

    async def refund_user_credits(
        self,
        user_id: str,
        cost_usd: float,
        job_id: str,
        reason: str = "Job failed - refund",
    ) -> tuple[bool, float]:
        """
        Refund credits if job fails after debit.
        
        Args:
            user_id: User ID
            cost_usd: Cost to refund in USD
            job_id: Photo job ID
            reason: Refund reason
        
        Returns:
            (success: bool, new_balance: float)
        """
        try:
            credits_to_refund = self.usd_to_credits(cost_usd)
            
            balance_before = await self.check_user_credits(user_id)
            
            from app.services.photo.integration import get_seed_user_service
            
            user_service = get_seed_user_service()
            user = user_service.get_user(user_id)
            
            if not user:
                logger.error(f"User not found for refund: {user_id}")
                return False, 0.0
            
            # Add credits back
            new_balance = balance_before + credits_to_refund
            user.credits = new_balance
            user_service.update_user(user)
            
            # Log transaction
            self._log_transaction(
                user_id=user_id,
                job_id=job_id,
                amount=credits_to_refund,
                transaction_type=TransactionType.REFUND,
                reason=reason,
                balance_before=balance_before,
                balance_after=new_balance,
                api_cost_usd=cost_usd,
            )
            
            logger.info(
                f"Refunded {credits_to_refund:.0f} credits to {user_id} "
                f"(${cost_usd:.2f}), new balance: {new_balance:.0f}"
            )
            return True, new_balance

        except Exception as e:
            logger.error(f"Failed to refund credits: {str(e)}")
            return False, 0.0

    def _log_transaction(
        self,
        user_id: str,
        job_id: Optional[str],
        amount: float,
        transaction_type: TransactionType,
        reason: Optional[str],
        balance_before: float,
        balance_after: float,
        api_cost_usd: Optional[float] = None,
    ):
        """Log credit transaction for audit trail"""
        import uuid
        
        try:
            transaction = PhotoCreditTransaction(
                id=str(uuid.uuid4()),
                user_id=user_id,
                job_id=job_id,
                amount=amount,
                transaction_type=transaction_type,
                reason=reason,
                balance_before=balance_before,
                balance_after=balance_after,
                api_cost_usd=api_cost_usd,
            )
            
            self.db_session.add(transaction)
            self.db_session.commit()
            
            logger.info(f"Logged transaction: {transaction}")
            
        except Exception as e:
            logger.error(f"Failed to log transaction: {str(e)}")
            self.db_session.rollback()

    def get_user_transaction_history(
        self,
        user_id: str,
        limit: int = 50,
    ) -> list:
        """Get user's credit transaction history"""
        try:
            transactions = (
                self.db_session.query(PhotoCreditTransaction)
                .filter_by(user_id=user_id)
                .order_by(PhotoCreditTransaction.created_at.desc())
                .limit(limit)
                .all()
            )
            
            return [
                {
                    "id": t.id,
                    "job_id": t.job_id,
                    "amount": t.amount,
                    "type": t.transaction_type.value,
                    "reason": t.reason,
                    "balance_before": t.balance_before,
                    "balance_after": t.balance_after,
                    "api_cost_usd": t.api_cost_usd,
                    "created_at": t.created_at.isoformat(),
                }
                for t in transactions
            ]
        except Exception as e:
            logger.error(f"Failed to get transaction history: {str(e)}")
            return []


class WatermarkService:
    """Adds watermarks to images when payment is pending"""

    @staticmethod
    def apply_watermark(
        image_bytes: bytes,
        watermark_text: str = "PREVIEW - Payment Pending",
    ) -> bytes:
        """
        Add watermark to image using PIL.
        
        Args:
            image_bytes: Original image data
            watermark_text: Watermark text
        
        Returns:
            Watermarked image bytes
        """
        try:
            from PIL import Image, ImageDraw, ImageFont
            import io

            # Open image
            img = Image.open(io.BytesIO(image_bytes)).convert("RGBA")

            # Create watermark layer
            watermark = Image.new("RGBA", img.size, (255, 255, 255, 0))
            draw = ImageDraw.Draw(watermark)

            # Try to use a nice font, fallback to default
            try:
                font = ImageFont.truetype("arial.ttf", 60)
            except Exception:
                font = ImageFont.load_default()

            # Calculate position (center with slight offset)
            text_bbox = draw.textbbox((0, 0), watermark_text, font=font)
            text_width = text_bbox[2] - text_bbox[0]
            text_height = text_bbox[3] - text_bbox[1]

            x = (img.width - text_width) // 2
            y = (img.height - text_height) // 2

            # Draw semi-transparent text
            draw.text(
                (x, y),
                watermark_text,
                fill=(255, 0, 0, 100),  # Red with 100/255 opacity
                font=font,
            )

            # Composite watermark onto image
            watermarked = Image.alpha_composite(img, watermark)

            # Convert back to RGB and save
            watermarked = watermarked.convert("RGB")
            output = io.BytesIO()
            watermarked.save(output, format="JPEG", quality=85)

            logger.info(f"Applied watermark to image ({len(image_bytes)} → {output.tell()} bytes)")
            return output.getvalue()

        except Exception as e:
            logger.error(f"Failed to apply watermark: {str(e)}")
            # Return original if watermark fails
            return image_bytes

    @staticmethod
    async def apply_watermark_if_unpaid(
        image_bytes: bytes,
        user_id: str,
        billing_service: PhotoBillingService,
    ) -> bytes:
        """
        Apply watermark if user hasn't paid for this job.
        
        Args:
            image_bytes: Image data
            user_id: User ID
            billing_service: Billing service instance
        
        Returns:
            Original or watermarked image bytes
        """
        try:
            from app.services.photo.settings import settings
            
            if not settings.PHOTO_WATERMARK_UNTIL_PAID:
                logger.info("Watermarking disabled")
                return image_bytes

            balance = await billing_service.check_user_credits(user_id)
            
            # Check if user is in credit
            if balance >= 0:
                logger.info(f"User {user_id} has paid (balance: {balance:.0f})")
                return image_bytes

            # Apply watermark
            logger.warning(
                f"User {user_id} balance negative ({balance:.0f}). "
                f"Applying watermark..."
            )
            return WatermarkService.apply_watermark(
                image_bytes,
                watermark_text="UNPAID - Complete Payment",
            )

        except Exception as e:
            logger.error(f"Error in apply_watermark_if_unpaid: {str(e)}")
            return image_bytes

