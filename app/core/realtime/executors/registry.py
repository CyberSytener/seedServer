"""
Action Executors - Mock implementations for all 8 standard actions

Each action has a dedicated Executor class that:
1. Validates parameters
2. Handles state transitions
3. Returns consistent ActionResult
4. Provides mock data

NO external API calls in this layer - pure business logic.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
import uuid


# ============================================================================
# Base Executor Class
# ============================================================================

class ExecutorError(Exception):
    """Base exception for executor failures"""
    pass


class Executor(ABC):
    """
    Base class for all action executors.
    
    Subclasses implement execute() and validate() methods.
    """
    
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.created_at = datetime.now(timezone.utc)
    
    @abstractmethod
    def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute action with given parameters.
        
        Must return dict with:
        - status: "success" | "error"
        - data: execution result
        - error_message: (if status="error")
        - execution_id: unique ID for this execution
        """
        pass
    
    @abstractmethod
    def validate(self, params: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """
        Validate parameters.
        
        Returns: (is_valid, error_messages)
        """
        pass
    
    def _generate_execution_id(self) -> str:
        """Generate unique execution ID"""
        return f"exec_{uuid.uuid4().hex[:12]}"


# ============================================================================
# 1. Search Listings Executor
# ============================================================================

class SearchListingsExecutor(Executor):
    """Search properties by location, price, beds, keywords"""
    
    # Mock data - in-memory "database"
    MOCK_LISTINGS = [
        {
            "id": "lst_001",
            "title": "Modern 2BR in Frogner",
            "location": "Oslo",
            "price_nok": 450000,
            "beds": 2,
            "area_m2": 75,
            "description": "Newly renovated apartment with parking",
        },
        {
            "id": "lst_002",
            "title": "Cozy 1BR Studio Downtown",
            "location": "Oslo",
            "price_nok": 280000,
            "beds": 1,
            "area_m2": 45,
            "description": "Perfect for first-time buyers",
        },
        {
            "id": "lst_003",
            "title": "Spacious 3BR Family Home",
            "location": "Bergen",
            "price_nok": 550000,
            "beds": 3,
            "area_m2": 120,
            "description": "Large garden, near schools",
        },
        {
            "id": "lst_004",
            "title": "Luxe Penthouse with Fjord View",
            "location": "Oslo",
            "price_nok": 850000,
            "beds": 3,
            "area_m2": 150,
            "description": "Premium location, top floor",
        },
        {
            "id": "lst_005",
            "title": "Budget 1BR in Grünerløkka",
            "location": "Oslo",
            "price_nok": 220000,
            "beds": 1,
            "area_m2": 38,
            "description": "Trendy neighborhood, walkable",
        },
    ]
    
    def validate(self, params: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """Validate search parameters"""
        errors = []
        
        if not params.get("location"):
            errors.append("location is required")
        
        price_min = params.get("price_min")
        price_max = params.get("price_max")
        
        if price_min is not None:
            if not isinstance(price_min, (int, float)) or price_min < 0:
                errors.append("price_min must be non-negative number")
        
        if price_max is not None:
            if not isinstance(price_max, (int, float)) or price_max < 0:
                errors.append("price_max must be non-negative number")
        
        if price_min and price_max and price_min > price_max:
            errors.append("price_min cannot be greater than price_max")
        
        beds_min = params.get("beds_min")
        if beds_min is not None:
            if not isinstance(beds_min, int) or beds_min < 0:
                errors.append("beds_min must be non-negative integer")
        
        return len(errors) == 0, errors
    
    def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Search listings with filters"""
        try:
            location = params.get("location", "").lower()
            price_min = params.get("price_min", 0)
            price_max = params.get("price_max", float("inf"))
            beds_min = params.get("beds_min", 0)
            keywords = params.get("keywords", "").lower()
            
            results = []
            for listing in self.MOCK_LISTINGS:
                # Filter by location
                if listing["location"].lower() != location:
                    continue
                
                # Filter by price
                if not (price_min <= listing["price_nok"] <= price_max):
                    continue
                
                # Filter by beds
                if listing["beds"] < beds_min:
                    continue
                
                # Filter by keywords
                if keywords and keywords not in listing["description"].lower():
                    continue
                
                results.append(listing)
            
            return {
                "status": "success",
                "data": {
                    "results": results,
                    "count": len(results),
                    "search_params": {
                        "location": location,
                        "price_min": price_min,
                        "price_max": price_max,
                        "beds_min": beds_min,
                    },
                },
                "execution_id": self._generate_execution_id(),
            }
        
        except Exception as e:
            return {
                "status": "error",
                "data": {},
                "error_message": str(e),
                "execution_id": self._generate_execution_id(),
            }


# ============================================================================
# 2. Get Listing Details Executor
# ============================================================================

class GetListingDetailsExecutor(Executor):
    """Fetch full details for a specific listing"""
    
    # Mock extended data
    MOCK_DETAILS = {
        "lst_001": {
            "id": "lst_001",
            "title": "Modern 2BR in Frogner",
            "location": "Oslo",
            "address": "Bygdøy Allé 42, Oslo",
            "price_nok": 450000,
            "beds": 2,
            "baths": 1,
            "area_m2": 75,
            "year_built": 1995,
            "description": "Newly renovated apartment with parking",
            "features": ["Parking", "Renovated", "Near metro", "Gym in building"],
            "images": ["img_001_1.jpg", "img_001_2.jpg"],
            "agent": {"name": "Anna Bergström", "phone": "+47 900 12345"},
            "available_from": "2026-02-15",
        },
        "lst_002": {
            "id": "lst_002",
            "title": "Cozy 1BR Studio Downtown",
            "location": "Oslo",
            "address": "Karl Johans Gate 15, Oslo",
            "price_nok": 280000,
            "beds": 1,
            "baths": 1,
            "area_m2": 45,
            "year_built": 2015,
            "description": "Perfect for first-time buyers",
            "features": ["Modern", "City center", "Furnished"],
            "images": ["img_002_1.jpg"],
            "agent": {"name": "Per Larsen", "phone": "+47 900 54321"},
            "available_from": "2026-03-01",
        },
    }
    
    def validate(self, params: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """Validate listing_id exists"""
        errors = []
        
        listing_id = params.get("listing_id")
        if not listing_id:
            errors.append("listing_id is required")
        elif listing_id not in self.MOCK_DETAILS:
            errors.append(f"listing_id {listing_id} not found")
        
        return len(errors) == 0, errors
    
    def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get full listing details"""
        try:
            listing_id = params.get("listing_id")
            
            if listing_id not in self.MOCK_DETAILS:
                return {
                    "status": "error",
                    "data": {},
                    "error_message": f"Listing {listing_id} not found",
                    "execution_id": self._generate_execution_id(),
                }
            
            details = self.MOCK_DETAILS[listing_id]
            
            return {
                "status": "success",
                "data": details,
                "execution_id": self._generate_execution_id(),
            }
        
        except Exception as e:
            return {
                "status": "error",
                "data": {},
                "error_message": str(e),
                "execution_id": self._generate_execution_id(),
            }


# ============================================================================
# 3. Book Viewing Executor (STATE MANAGEMENT)
# ============================================================================

class BookViewingExecutor(Executor):
    """Book viewing for a property - tracks state transitions"""
    
    # In-memory storage for bookings
    BOOKINGS: Dict[str, Dict[str, Any]] = {}
    
    def validate(self, params: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """Validate booking parameters"""
        errors = []
        
        if not params.get("listing_id"):
            errors.append("listing_id is required")
        
        if not params.get("preferred_windows"):
            errors.append("preferred_windows (list of date strings) is required")
        elif not isinstance(params["preferred_windows"], list):
            errors.append("preferred_windows must be a list")
        
        return len(errors) == 0, errors
    
    def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Book viewing for property.
        
        State flow: pending → user_confirms → scheduled → completed
        
        At this layer: only goes to "pending" state
        Actual scheduling happens after user confirmation
        """
        try:
            listing_id = params.get("listing_id")
            preferred_windows = params.get("preferred_windows", [])
            
            # Create booking record
            booking_id = f"bkg_{uuid.uuid4().hex[:12]}"
            booking = {
                "id": booking_id,
                "listing_id": listing_id,
                "status": "pending",  # waiting for user confirmation
                "preferred_windows": preferred_windows,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "confirmed_at": None,
                "confirmed_time": None,
                "user_name": params.get("user_name", "Anonymous"),
                "user_phone": params.get("user_phone", ""),
            }
            
            self.BOOKINGS[booking_id] = booking
            
            return {
                "status": "success",
                "data": {
                    "booking_id": booking_id,
                    "state": "pending",
                    "message": "Booking created. Awaiting user confirmation.",
                    "next_action": "client.action.confirm",
                    "action_id_to_confirm": booking_id,  # Model will include this in confirm message
                },
                "execution_id": self._generate_execution_id(),
            }
        
        except Exception as e:
            return {
                "status": "error",
                "data": {},
                "error_message": str(e),
                "execution_id": self._generate_execution_id(),
            }
    
    @classmethod
    def confirm_booking(cls, booking_id: str, confirmed_time: str) -> Tuple[bool, str]:
        """
        Called when user confirms booking via ClientActionConfirm.
        
        Returns: (success, message)
        """
        if booking_id not in cls.BOOKINGS:
            return False, f"Booking {booking_id} not found"
        
        booking = cls.BOOKINGS[booking_id]
        
        if booking["status"] != "pending":
            return False, f"Booking already {booking['status']}"
        
        # Transition state
        booking["status"] = "confirmed"
        booking["confirmed_at"] = datetime.now(timezone.utc).isoformat()
        booking["confirmed_time"] = confirmed_time
        
        return True, f"Booking {booking_id} confirmed for {confirmed_time}"
    
    @classmethod
    def get_booking(cls, booking_id: str) -> Optional[Dict[str, Any]]:
        """Get booking details"""
        return cls.BOOKINGS.get(booking_id)
    
    @classmethod
    def list_bookings(cls, session_id: str = None) -> List[Dict[str, Any]]:
        """List all bookings (optionally filtered by session)"""
        return list(cls.BOOKINGS.values())


# ============================================================================
# 4. Create or Update CV Executor
# ============================================================================

class CreateOrUpdateCVExecutor(Executor):
    """Generate or update CV from data"""
    
    # Mock CV storage
    USER_CVS: Dict[str, Dict[str, Any]] = {}
    
    def validate(self, params: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """Validate CV parameters"""
        errors = []
        
        if not params.get("full_name"):
            errors.append("full_name is required")
        
        sections = params.get("sections", {})
        if not isinstance(sections, dict):
            errors.append("sections must be a dict")
        
        return len(errors) == 0, errors
    
    def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Create or update CV"""
        try:
            full_name = params.get("full_name")
            sections = params.get("sections", {})
            user_id = self.session_id
            
            cv_id = f"cv_{uuid.uuid4().hex[:12]}"
            cv = {
                "id": cv_id,
                "user_id": user_id,
                "full_name": full_name,
                "sections": sections,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "version": 1,
            }
            
            self.USER_CVS[cv_id] = cv
            
            # Generate mock markdown CV
            cv_markdown = self._generate_markdown(cv)
            
            return {
                "status": "success",
                "data": {
                    "cv_id": cv_id,
                    "full_name": full_name,
                    "sections": sections,
                    "preview": cv_markdown[:500] + "..." if len(cv_markdown) > 500 else cv_markdown,
                    "download_url": f"/api/cv/{cv_id}/download",
                },
                "execution_id": self._generate_execution_id(),
            }
        
        except Exception as e:
            return {
                "status": "error",
                "data": {},
                "error_message": str(e),
                "execution_id": self._generate_execution_id(),
            }
    
    @staticmethod
    def _generate_markdown(cv: Dict[str, Any]) -> str:
        """Generate markdown CV from structured data"""
        lines = [
            f"# {cv['full_name']}",
            "",
        ]
        
        for section_name, section_data in cv["sections"].items():
            lines.append(f"## {section_name.replace('_', ' ').title()}")
            if isinstance(section_data, str):
                lines.append(section_data)
            elif isinstance(section_data, list):
                for item in section_data:
                    lines.append(f"- {item}")
            lines.append("")
        
        return "\n".join(lines)


# ============================================================================
# 5. Schedule Lesson Executor
# ============================================================================

class ScheduleLessonExecutor(Executor):
    """Schedule language lesson with tutor"""
    
    # Mock lessons
    LESSONS: Dict[str, Dict[str, Any]] = {}
    
    def validate(self, params: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """Validate lesson parameters"""
        errors = []
        
        if not params.get("tutor_id"):
            errors.append("tutor_id is required")
        
        if not params.get("scheduled_time"):
            errors.append("scheduled_time is required")
        
        duration = params.get("duration_minutes")
        if duration is None:
            errors.append("duration_minutes is required")
        elif not isinstance(duration, int) or duration <= 0:
            errors.append("duration_minutes must be positive integer")
        
        return len(errors) == 0, errors
    
    def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Schedule lesson"""
        try:
            lesson_id = f"les_{uuid.uuid4().hex[:12]}"
            lesson = {
                "id": lesson_id,
                "student_id": self.session_id,
                "tutor_id": params.get("tutor_id"),
                "scheduled_time": params.get("scheduled_time"),
                "duration_minutes": params.get("duration_minutes"),
                "status": "pending",
                "level": params.get("level", "intermediate"),
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            
            self.LESSONS[lesson_id] = lesson
            
            return {
                "status": "success",
                "data": {
                    "lesson_id": lesson_id,
                    "scheduled_time": lesson["scheduled_time"],
                    "tutor_id": params.get("tutor_id"),
                    "duration_minutes": params.get("duration_minutes"),
                    "status": "pending",
                },
                "execution_id": self._generate_execution_id(),
            }
        
        except Exception as e:
            return {
                "status": "error",
                "data": {},
                "error_message": str(e),
                "execution_id": self._generate_execution_id(),
            }


# ============================================================================
# 6. Record Practice Executor
# ============================================================================

class RecordPracticeExecutor(Executor):
    """Log language practice session"""
    
    # Mock practice log
    PRACTICE_LOG: Dict[str, List[Dict[str, Any]]] = {}
    
    def validate(self, params: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """Validate practice parameters"""
        errors = []
        
        if not params.get("duration_minutes"):
            errors.append("duration_minutes is required")
        
        if not params.get("activity"):
            errors.append("activity is required (speaking|writing|reading|listening)")
        
        return len(errors) == 0, errors
    
    def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Record practice session"""
        try:
            user_id = self.session_id
            
            if user_id not in self.PRACTICE_LOG:
                self.PRACTICE_LOG[user_id] = []
            
            practice = {
                "id": f"prac_{uuid.uuid4().hex[:12]}",
                "duration_minutes": params.get("duration_minutes"),
                "activity": params.get("activity"),
                "language": params.get("language", "Norwegian"),
                "notes": params.get("notes", ""),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            
            self.PRACTICE_LOG[user_id].append(practice)
            
            # Calculate stats
            total_minutes = sum(p["duration_minutes"] for p in self.PRACTICE_LOG[user_id])
            
            return {
                "status": "success",
                "data": {
                    "practice_id": practice["id"],
                    "recorded_at": practice["timestamp"],
                    "duration_minutes": practice["duration_minutes"],
                    "session_total_minutes": total_minutes,
                    "sessions_count": len(self.PRACTICE_LOG[user_id]),
                },
                "execution_id": self._generate_execution_id(),
            }
        
        except Exception as e:
            return {
                "status": "error",
                "data": {},
                "error_message": str(e),
                "execution_id": self._generate_execution_id(),
            }


# ============================================================================
# 7. Send Email Executor
# ============================================================================

class SendEmailExecutor(Executor):
    """Send email (mock - no real SMTP)"""
    
    # Mock email log
    EMAIL_LOG: Dict[str, List[Dict[str, Any]]] = {}
    
    def validate(self, params: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """Validate email parameters"""
        errors = []
        
        if not params.get("to"):
            errors.append("to (recipient email) is required")
        
        if not params.get("subject"):
            errors.append("subject is required")
        
        if not params.get("body"):
            errors.append("body is required")
        
        # Validate email format (basic)
        to_email = params.get("to", "")
        if "@" not in to_email or "." not in to_email:
            errors.append("to must be valid email format")
        
        return len(errors) == 0, errors
    
    def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Send email"""
        try:
            email_id = f"email_{uuid.uuid4().hex[:12]}"
            email = {
                "id": email_id,
                "from": "noreply@seed.ai",
                "to": params.get("to"),
                "subject": params.get("subject"),
                "body": params.get("body"),
                "sent_at": datetime.now(timezone.utc).isoformat(),
                "status": "sent",
            }
            
            # Log email
            if self.session_id not in self.EMAIL_LOG:
                self.EMAIL_LOG[self.session_id] = []
            self.EMAIL_LOG[self.session_id].append(email)
            
            return {
                "status": "success",
                "data": {
                    "email_id": email_id,
                    "to": email["to"],
                    "sent_at": email["sent_at"],
                    "status": "sent",
                },
                "execution_id": self._generate_execution_id(),
            }
        
        except Exception as e:
            return {
                "status": "error",
                "data": {},
                "error_message": str(e),
                "execution_id": self._generate_execution_id(),
            }


# ============================================================================
# 8. Send SMS Executor
# ============================================================================

class SendSMSExecutor(Executor):
    """Send SMS (mock - no real Twilio)"""
    
    # Mock SMS log
    SMS_LOG: Dict[str, List[Dict[str, Any]]] = {}
    
    def validate(self, params: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """Validate SMS parameters"""
        errors = []
        
        if not params.get("phone"):
            errors.append("phone is required (E.164 format)")
        
        if not params.get("message"):
            errors.append("message is required")
        
        message = params.get("message", "")
        if len(message) > 160:
            errors.append("message must be 160 chars or less (SMS limit)")
        
        return len(errors) == 0, errors
    
    def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Send SMS"""
        try:
            sms_id = f"sms_{uuid.uuid4().hex[:12]}"
            sms = {
                "id": sms_id,
                "phone": params.get("phone"),
                "message": params.get("message"),
                "sent_at": datetime.now(timezone.utc).isoformat(),
                "status": "sent",
            }
            
            # Log SMS
            if self.session_id not in self.SMS_LOG:
                self.SMS_LOG[self.session_id] = []
            self.SMS_LOG[self.session_id].append(sms)
            
            return {
                "status": "success",
                "data": {
                    "sms_id": sms_id,
                    "phone": sms["phone"],
                    "sent_at": sms["sent_at"],
                    "status": "sent",
                },
                "execution_id": self._generate_execution_id(),
            }
        
        except Exception as e:
            return {
                "status": "error",
                "data": {},
                "error_message": str(e),
                "execution_id": self._generate_execution_id(),
            }


# ============================================================================
# Executor Registry
# ============================================================================

EXECUTOR_MAP = {
    "search_listings": SearchListingsExecutor,
    "get_listing_details": GetListingDetailsExecutor,
    "book_viewing": BookViewingExecutor,
    "create_or_update_cv": CreateOrUpdateCVExecutor,
    "schedule_lesson": ScheduleLessonExecutor,
    "record_practice": RecordPracticeExecutor,
    "send_email": SendEmailExecutor,
    "send_sms": SendSMSExecutor,
}


def get_executor(action_name: str, session_id: str) -> Optional[Executor]:
    """Get executor for action"""
    executor_class = EXECUTOR_MAP.get(action_name)
    if executor_class:
        return executor_class(session_id)
    return None
