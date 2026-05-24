"""
Retry utilities for handling transient failures.

Provides decorators for automatic retries with exponential backoff,
essential for resilient API interactions with Todoist and Notion.
"""

import logging
import time
from functools import wraps
from typing import Callable, TypeVar, Optional, Tuple, Type

logger = logging.getLogger(__name__)

# Type variable for generic function return type
T = TypeVar('T')


def retry_on_failure(
    max_retries: int = 3,
    backoff_base: float = 2.0,
    backoff_max: float = 60.0,
    exceptions: Tuple[Type[Exception], ...] = (Exception,)
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """
    Decorator for automatic retries with exponential backoff.
    
    Retries a function when it raises specified exceptions, with exponentially
    increasing wait times between attempts.
    
    Args:
        max_retries: Maximum number of retry attempts (default: 3)
        backoff_base: Base for exponential backoff calculation (default: 2.0)
        backoff_max: Maximum wait time between retries in seconds (default: 60.0)
        exceptions: Tuple of exception types to catch and retry (default: all)
    
    Returns:
        Decorated function with retry logic
    
    Example:
        @retry_on_failure(max_retries=3, backoff_base=2.0)
        def update_task(task_id, data):
            return api.update_task(task_id, data)
    
    Retry Schedule (with backoff_base=2.0):
        Attempt 1: Immediate
        Attempt 2: Wait 2.0s  (2^0 * 2.0)
        Attempt 3: Wait 4.0s  (2^1 * 2.0)
        Attempt 4: Wait 8.0s  (2^2 * 2.0)
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args, **kwargs) -> T:
            last_exception: Optional[Exception] = None
            
            for attempt in range(max_retries + 1):  # +1 for initial attempt
                try:
                    result = func(*args, **kwargs)
                    
                    # Log success if this was a retry
                    if attempt > 0:
                        logger.info(
                            f"✅ Success on attempt {attempt + 1}/{max_retries + 1} "
                            f"for {func.__name__}"
                        )
                    
                    return result
                    
                except exceptions as e:
                    last_exception = e
                    
                    # If this was the last attempt, raise the exception
                    if attempt == max_retries:
                        logger.error(
                            f"❌ Failed after {max_retries + 1} attempts: "
                            f"{func.__name__} - {str(e)}"
                        )
                        raise
                    
                    # Calculate wait time with exponential backoff
                    wait_time = min(backoff_base ** attempt, backoff_max)
                    
                    logger.warning(
                        f"⚠️  Attempt {attempt + 1}/{max_retries + 1} failed for "
                        f"{func.__name__}: {str(e)}"
                    )
                    logger.info(f"⏳ Retrying in {wait_time:.1f}s...")
                    
                    time.sleep(wait_time)
            
            # This should never be reached, but just in case
            if last_exception:
                raise last_exception
            
        return wrapper
    return decorator


class RateLimiter:
    """
    Token bucket rate limiter for API calls.
    
    Prevents exceeding API rate limits by controlling request frequency.
    
    Example:
        limiter = RateLimiter(max_calls=10, time_window=60)
        
        with limiter:
            api.update_task(task_id, data)
    """
    
    def __init__(self, max_calls: int = 60, time_window: float = 60.0):
        """
        Initialize rate limiter.
        
        Args:
            max_calls: Maximum number of calls allowed in time window
            time_window: Time window in seconds
        """
        self.max_calls = max_calls
        self.time_window = time_window
        self.calls = []
    
    def __enter__(self):
        """Wait if rate limit would be exceeded."""
        now = time.time()
        
        # Remove calls outside the time window
        self.calls = [call_time for call_time in self.calls 
                      if now - call_time < self.time_window]
        
        # If at limit, wait until oldest call expires
        if len(self.calls) >= self.max_calls:
            sleep_time = self.time_window - (now - self.calls[0]) + 0.1
            if sleep_time > 0:
                logger.debug(f"Rate limit reached, waiting {sleep_time:.1f}s")
                time.sleep(sleep_time)
                # Remove expired calls again
                now = time.time()
                self.calls = [call_time for call_time in self.calls 
                              if now - call_time < self.time_window]
        
        # Record this call
        self.calls.append(now)
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        pass


# Pre-configured decorators for common use cases
retry_api_call = retry_on_failure(max_retries=3, backoff_base=2.0)
retry_db_operation = retry_on_failure(max_retries=5, backoff_base=1.0)
retry_network_request = retry_on_failure(max_retries=3, backoff_base=1.5)
