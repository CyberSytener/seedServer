"""
Retry + Exponential Backoff for Executor Actions

Provides automatic retry with exponential backoff for transient failures.
Max retries: 3 (configurable per executor)
Backoff formula: 2^attempt * base_delay (e.g., 1s, 2s, 4s)
"""

import asyncio
import logging
import time
from typing import Callable, Dict, Any
from functools import wraps

logger = logging.getLogger(__name__)


class RetryableExecutor:
    """
    Mixin for executors that should support automatic retries.
    Use with retry_wrapper() decorator.
    """
    
    max_retries: int = 3
    base_delay: float = 0.5  # seconds
    
    @staticmethod
    def retry_wrapper(
        func: Callable,
        max_retries: int = 3,
        base_delay: float = 0.5,
        retriable_errors: tuple = (Exception,)
    ):
        """
        Decorator for automatic retry with exponential backoff.
        
        Produces an **async** wrapper that uses ``asyncio.sleep`` so it
        never blocks the event loop.  If *func* is synchronous it is
        still called normally — only the sleep between retries is async.
        
        Args:
            func: Function to wrap
            max_retries: Maximum retry attempts (default 3)
            base_delay: Base delay in seconds (default 0.5s)
            retriable_errors: Tuple of exceptions to retry on
        
        Returns:
            Wrapped async function with retry logic
        """
        @wraps(func)
        async def wrapper(*args, **kwargs):
            last_error = None
            
            for attempt in range(max_retries + 1):
                try:
                    logger.debug(f"Attempt {attempt + 1}/{max_retries + 1}: {func.__name__}")
                    result = func(*args, **kwargs)
                    
                    if attempt > 0:
                        logger.info(f"Succeeded after {attempt} retries: {func.__name__}")
                    
                    return result
                
                except retriable_errors as e:
                    last_error = e
                    
                    if attempt < max_retries:
                        # Exponential backoff: 2^attempt * base_delay
                        delay = (2 ** attempt) * base_delay
                        logger.warning(
                            f"Attempt {attempt + 1} failed: {e}. "
                            f"Retrying in {delay:.1f}s..."
                        )
                        await asyncio.sleep(delay)
                    else:
                        logger.error(f"All {max_retries + 1} attempts failed: {e}")
            
            # All retries exhausted
            raise last_error or Exception("Unknown error")
        
        return wrapper

    @staticmethod
    def retry_wrapper_sync(
        func: Callable,
        max_retries: int = 3,
        base_delay: float = 0.5,
        retriable_errors: tuple = (Exception,)
    ):
        """Synchronous retry wrapper using ``time.sleep`` — for non-async code only."""
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_error = None
            for attempt in range(max_retries + 1):
                try:
                    result = func(*args, **kwargs)
                    if attempt > 0:
                        logger.info(f"Succeeded after {attempt} retries: {func.__name__}")
                    return result
                except retriable_errors as e:
                    last_error = e
                    if attempt < max_retries:
                        delay = (2 ** attempt) * base_delay
                        logger.warning(
                            f"Attempt {attempt + 1} failed: {e}. "
                            f"Retrying in {delay:.1f}s..."
                        )
                        time.sleep(delay)
                    else:
                        logger.error(f"All {max_retries + 1} attempts failed: {e}")
            raise last_error or Exception("Unknown error")
        return wrapper


def with_retry(max_retries: int = 3, base_delay: float = 0.5, retriable_errors: tuple = (Exception,)):
    """
    Decorator factory for adding retry logic to any function.
    
    Usage:
        @with_retry(max_retries=3, base_delay=0.5)
        def my_executor_method(params):
            ...
    """
    def decorator(func):
        return RetryableExecutor.retry_wrapper(
            func,
            max_retries=max_retries,
            base_delay=base_delay,
            retriable_errors=retriable_errors
        )
    return decorator


# Example: Retriable exception types
class TransientError(Exception):
    """Temporary failure - safe to retry"""
    pass


class PermanentError(Exception):
    """Permanent failure - do not retry"""
    pass


# ============================================================================
# Integration with Executors
# ============================================================================

def wrap_executor_execute_with_retry(executor_class, max_retries=3):
    """
    Wrap an executor's execute() method with retry logic.
    
    Usage:
        SearchListingsExecutor = wrap_executor_execute_with_retry(
            SearchListingsExecutor,
            max_retries=3
        )
    """
    original_execute = executor_class.execute
    
    @with_retry(max_retries=max_retries, retriable_errors=(TransientError, TimeoutError))
    def execute_with_retry(self, params: Dict[str, Any]) -> Dict[str, Any]:
        return original_execute(self, params)
    
    executor_class.execute = execute_with_retry
    return executor_class


# ============================================================================
# Backoff Strategies (for future use)
# ============================================================================

class BackoffStrategy:
    """Base class for backoff strategies"""
    
    def get_delay(self, attempt: int) -> float:
        """Get delay for given attempt (0-indexed)"""
        raise NotImplementedError


class ExponentialBackoff(BackoffStrategy):
    """2^attempt * base_delay"""
    
    def __init__(self, base_delay: float = 0.5, max_delay: float = 60):
        self.base_delay = base_delay
        self.max_delay = max_delay
    
    def get_delay(self, attempt: int) -> float:
        delay = (2 ** attempt) * self.base_delay
        return min(delay, self.max_delay)


class LinearBackoff(BackoffStrategy):
    """attempt * base_delay"""
    
    def __init__(self, base_delay: float = 1, max_delay: float = 60):
        self.base_delay = base_delay
        self.max_delay = max_delay
    
    def get_delay(self, attempt: int) -> float:
        delay = attempt * self.base_delay
        return min(delay, self.max_delay)


class JitterBackoff(BackoffStrategy):
    """Exponential + random jitter to prevent thundering herd"""
    
    def __init__(self, base_delay: float = 0.5, max_delay: float = 60):
        import random
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.random = random
    
    def get_delay(self, attempt: int) -> float:
        exponential = (2 ** attempt) * self.base_delay
        max_jitter = min(exponential, self.max_delay)
        # Add random jitter up to max
        delay = self.random.uniform(0, max_jitter)
        return delay
