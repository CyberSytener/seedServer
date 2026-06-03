"""
Input validation and sanitization for Saga Orchestrator.
Validates and sanitizes all input data to prevent injection attacks and data corruption.
"""

from pydantic import BaseModel, Field, validator, root_validator
from typing import Optional, Dict, List, Any
import re
import logging

logger = logging.getLogger(__name__)


class SagaInputValidator:
    """Validates and sanitizes saga input."""
    
    # Regex patterns for validation
    ID_PATTERN = re.compile(r"^[a-zA-Z0-9_\-]{1,255}$")
    NAME_PATTERN = re.compile(r"^[a-zA-Z0-9_\-\s]{1,255}$")
    EMAIL_PATTERN = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")
    URL_PATTERN = re.compile(r"^https?://[a-zA-Z0-9\-._~:/?#\[\]@!$&'()*+,;=]+$")
    
    # XSS/Injection patterns
    DANGEROUS_PATTERNS = [
        re.compile(r"<script", re.IGNORECASE),
        re.compile(r"javascript:", re.IGNORECASE),
        re.compile(r"onerror=", re.IGNORECASE),
        re.compile(r"onclick=", re.IGNORECASE),
        re.compile(r"onload=", re.IGNORECASE),
        re.compile(r"eval\(", re.IGNORECASE),
        re.compile(r"__proto__", re.IGNORECASE),
        re.compile(r"constructor", re.IGNORECASE),
    ]
    
    @staticmethod
    def validate_saga_id(saga_id: str) -> str:
        """
        Validate saga ID format.
        
        Args:
            saga_id: Saga identifier to validate
            
        Returns:
            Sanitized saga ID
            
        Raises:
            ValueError: If invalid format
        """
        if not saga_id:
            raise ValueError("Saga ID cannot be empty")
        
        saga_id = saga_id.strip()
        
        if not SagaInputValidator.ID_PATTERN.match(saga_id):
            raise ValueError(
                f"Invalid saga ID format: {saga_id}. "
                "Must be alphanumeric with underscores/hyphens, max 255 chars"
            )
        
        return saga_id
    
    @staticmethod
    def validate_step_name(step_name: str) -> str:
        """Validate saga step name."""
        if not step_name:
            raise ValueError("Step name cannot be empty")
        
        step_name = step_name.strip()
        
        if not SagaInputValidator.NAME_PATTERN.match(step_name):
            raise ValueError(
                f"Invalid step name format: {step_name}. "
                "Must be alphanumeric with underscores/hyphens/spaces, max 255 chars"
            )
        
        return step_name
    
    @staticmethod
    def validate_adapter_name(adapter_name: str) -> str:
        """Validate adapter name."""
        if not adapter_name:
            raise ValueError("Adapter name cannot be empty")
        
        adapter_name = adapter_name.strip()
        
        if not SagaInputValidator.ID_PATTERN.match(adapter_name):
            raise ValueError(
                f"Invalid adapter name format: {adapter_name}. "
                "Must be alphanumeric with underscores/hyphens, max 255 chars"
            )
        
        return adapter_name
    
    @staticmethod
    def sanitize_string(value: str, max_length: int = 1000) -> str:
        """
        Sanitize string input.
        
        Args:
            value: String to sanitize
            max_length: Maximum allowed length
            
        Returns:
            Sanitized string
            
        Raises:
            ValueError: If contains dangerous patterns
        """
        if not isinstance(value, str):
            raise ValueError("Value must be string")
        
        # Trim whitespace
        value = value.strip()
        
        # Check length
        if len(value) > max_length:
            raise ValueError(f"String exceeds maximum length of {max_length}")
        
        # Check for dangerous patterns
        for pattern in SagaInputValidator.DANGEROUS_PATTERNS:
            if pattern.search(value):
                raise ValueError(f"String contains potentially dangerous content")
        
        # Remove null bytes
        if '\x00' in value:
            raise ValueError("String contains null bytes")
        
        return value
    
    @staticmethod
    def sanitize_dict(data: Dict[str, Any], max_depth: int = 5) -> Dict[str, Any]:
        """
        Recursively sanitize dictionary.
        
        Args:
            data: Dictionary to sanitize
            max_depth: Maximum nesting depth
            
        Returns:
            Sanitized dictionary
        """
        if max_depth <= 0:
            raise ValueError("Dictionary nesting too deep")
        
        if not isinstance(data, dict):
            raise ValueError("Expected dictionary")
        
        sanitized = {}
        
        for key, value in data.items():
            # Sanitize key
            if not isinstance(key, str):
                raise ValueError("Dictionary keys must be strings")
            
            sanitized_key = SagaInputValidator.sanitize_string(key, max_length=255)
            
            # Sanitize value
            if isinstance(value, str):
                sanitized[sanitized_key] = SagaInputValidator.sanitize_string(value)
            elif isinstance(value, dict):
                sanitized[sanitized_key] = SagaInputValidator.sanitize_dict(value, max_depth - 1)
            elif isinstance(value, (list, tuple)):
                sanitized[sanitized_key] = SagaInputValidator.sanitize_list(value, max_depth - 1)
            elif isinstance(value, (int, float, bool, type(None))):
                sanitized[sanitized_key] = value
            else:
                raise ValueError(f"Unsupported value type: {type(value)}")
        
        return sanitized
    
    @staticmethod
    def sanitize_list(data: List[Any], max_depth: int = 5) -> List[Any]:
        """Recursively sanitize list."""
        if max_depth <= 0:
            raise ValueError("List nesting too deep")
        
        if not isinstance(data, (list, tuple)):
            raise ValueError("Expected list or tuple")
        
        sanitized = []
        
        for item in data:
            if isinstance(item, str):
                sanitized.append(SagaInputValidator.sanitize_string(item))
            elif isinstance(item, dict):
                sanitized.append(SagaInputValidator.sanitize_dict(item, max_depth - 1))
            elif isinstance(item, (list, tuple)):
                sanitized.append(SagaInputValidator.sanitize_list(item, max_depth - 1))
            elif isinstance(item, (int, float, bool, type(None))):
                sanitized.append(item)
            else:
                raise ValueError(f"Unsupported list item type: {type(item)}")
        
        return sanitized
    
    @staticmethod
    def validate_email(email: str) -> str:
        """Validate email address."""
        if not email:
            raise ValueError("Email cannot be empty")
        
        email = email.strip().lower()
        
        if not SagaInputValidator.EMAIL_PATTERN.match(email):
            raise ValueError(f"Invalid email format: {email}")
        
        if len(email) > 254:  # RFC 5321
            raise ValueError("Email address too long")
        
        return email
    
    @staticmethod
    def validate_url(url: str) -> str:
        """Validate URL."""
        if not url:
            raise ValueError("URL cannot be empty")
        
        url = url.strip()
        
        if not SagaInputValidator.URL_PATTERN.match(url):
            raise ValueError(f"Invalid URL format: {url}")
        
        if len(url) > 2048:
            raise ValueError("URL too long")
        
        return url


# Pydantic models for validated request data

class ResumeSagaRequest(BaseModel):
    """Validated request to resume a saga."""
    saga_id: str = Field(..., min_length=1, max_length=255)
    step_name: Optional[str] = Field(None, max_length=255)
    retry_count: Optional[int] = Field(None, ge=0, le=10)
    
    @validator("saga_id")
    def validate_saga_id(cls, v):
        return SagaInputValidator.validate_saga_id(v)
    
    @validator("step_name")
    def validate_step(cls, v):
        if v is not None:
            return SagaInputValidator.validate_step_name(v)
        return v


class StartSagaRequest(BaseModel):
    """Validated request to start a saga."""
    saga_type: str = Field(..., min_length=1, max_length=255)
    saga_id: Optional[str] = Field(None, max_length=255)
    input_data: Optional[Dict[str, Any]] = Field(None)
    
    @validator("saga_type")
    def validate_type(cls, v):
        return SagaInputValidator.validate_step_name(v)
    
    @validator("saga_id")
    def validate_id(cls, v):
        if v is not None:
            return SagaInputValidator.validate_saga_id(v)
        return v
    
    @validator("input_data")
    def validate_input(cls, v):
        if v is not None:
            return SagaInputValidator.sanitize_dict(v)
        return v


class DLQRetryRequest(BaseModel):
    """Validated request to retry DLQ item."""
    dlq_id: str = Field(..., min_length=1, max_length=255)
    max_retries: Optional[int] = Field(5, ge=1, le=20)
    
    @validator("dlq_id")
    def validate_dlq_id(cls, v):
        return SagaInputValidator.validate_saga_id(v)


class ExecutorConfigRequest(BaseModel):
    """Validated executor configuration."""
    max_workers: int = Field(10, ge=1, le=100)
    timeout_seconds: int = Field(300, ge=10, le=3600)
    retry_count: int = Field(3, ge=0, le=10)
    
    @validator("max_workers")
    def validate_workers(cls, v):
        if v < 1 or v > 100:
            raise ValueError("max_workers must be between 1 and 100")
        return v


class SagaAdapterRequest(BaseModel):
    """Validated adapter registration request."""
    adapter_name: str = Field(..., min_length=1, max_length=255)
    adapter_type: str = Field(..., min_length=1, max_length=255)
    config: Optional[Dict[str, Any]] = Field(None)
    
    @validator("adapter_name")
    def validate_name(cls, v):
        return SagaInputValidator.validate_adapter_name(v)
    
    @validator("adapter_type")
    def validate_type(cls, v):
        return SagaInputValidator.validate_adapter_name(v)
    
    @validator("config")
    def validate_config(cls, v):
        if v is not None:
            return SagaInputValidator.sanitize_dict(v)
        return v
