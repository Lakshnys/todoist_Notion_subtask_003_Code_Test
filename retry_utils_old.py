"""
Retry utilities for handling transient failures.
Implements exponential backoff with configurable retry limits.
"""

import logging
import time
from functools import wraps
from typing import Callable, TypeVar, Any

logger = logging.getLogger(__name__)

T = TypeVar('T')


def retry_on_failure(
    max_retries: int = 3,
    backoff_base: float = 2.0,
    exceptions: tuple = (Exception,)
):
    """
    Decorator to retry a function on failure with exponential backoff.
    
    Args:
        max_retries: Maximum number of retry attempts
        backoff_base: Base for exponential backoff (seconds)
        exceptions: Tuple of exceptions to catch and retry
        
    Example:
        @retry_on_failure(max_retries=3, backoff_base=2.0)
        def api_call():
            return requests.get("https://api.example.com/data")
            
        # Will retry up to 3 times with delays: 2s, 4s, 8s
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            last_exception = None
            
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                    
                except exceptions as e:
                    last_exception = e
                    
                    # Don't retry on last attempt
                    if attempt == max_retries - 1:
                        logger.error(
                            f"{func.__name__} failed after {max_retries} attempts: {e}"
                        )
                        raise
                    
                    # Calculate backoff delay
                    wait_time = backoff_base ** attempt
                    
                    logger.warning(
                        f"{func.__name__} failed (attempt {attempt + 1}/{max_retries}): {e}"
                    )
                    logger.info(f"Retrying in {wait_time:.1f} seconds...")
                    
                    time.sleep(wait_time)
            
            # Should never reach here, but just in case
            raise last_exception
            
        return wrapper
    return decorator


def retry_with_context(
    max_retries: int = 3,
    backoff_base: float = 2.0,
    exceptions: tuple = (Exception,),
    context_message: str = ""
):
    """
    Retry decorator with additional context in error messages.
    
    Useful for providing specific context about what was being attempted.
    
    Example:
        @retry_with_context(context_message="Updating Notion task ABC123")
        def update_notion_task(task_id, data):
            return notion_api.update(task_id, data)
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            context = context_message or func.__name__
            last_exception = None
            
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                    
                except exceptions as e:
                    last_exception = e
                    
                    if attempt == max_retries - 1:
                        logger.error(f"Failed {context} after {max_retries} attempts: {e}")
                        raise
                    
                    wait_time = backoff_base ** attempt
                    logger.warning(f"Failed {context} (attempt {attempt + 1}/{max_retries}): {e}")
                    logger.info(f"Retrying in {wait_time:.1f} seconds...")
                    time.sleep(wait_time)
            
            raise last_exception
            
        return wrapper
    return decorator


class RateLimiter:
    """
    Simple token bucket rate limiter.
    
    Prevents exceeding API rate limits by controlling request frequency.
    
    Example:
        limiter = RateLimiter(requests_per_second=10)
        
        for task in tasks:
            with limiter:
                api.update_task(task)
    """
    
    def __init__(self, requests_per_second: float = 10.0):
        """
        Initialize rate limiter.
        
        Args:
            requests_per_second: Maximum requests allowed per second
        """
        self.requests_per_second = requests_per_second
        self.min_interval = 1.0 / requests_per_second
        self.last_request_time = 0.0
    
    def __enter__(self):
        """Wait if necessary before allowing request."""
        current_time = time.time()
        elapsed = current_time - self.last_request_time
        
        if elapsed < self.min_interval:
            wait_time = self.min_interval - elapsed
            time.sleep(wait_time)
        
        self.last_request_time = time.time()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        return False


# Predefined retry configurations for common use cases

def retry_api_call(func: Callable[..., T]) -> Callable[..., T]:
    """
    Retry decorator optimized for API calls.
    Handles common API failures with reasonable defaults.
    """
    return retry_on_failure(
        max_retries=3,
        backoff_base=2.0,
        exceptions=(ConnectionError, TimeoutError, Exception)
    )(func)


def retry_database_operation(func: Callable[..., T]) -> Callable[..., T]:
    """
    Retry decorator optimized for database operations.
    Faster retry with more attempts for transient DB issues.
    """
    return retry_on_failure(
        max_retries=5,
        backoff_base=1.5,
        exceptions=(Exception,)
    )(func)


# Example usage:
if __name__ == "__main__":
    # Configure logging for demo
    logging.basicConfig(level=logging.INFO)
    
    # Example 1: Basic retry
    @retry_on_failure(max_retries=3)
    def flaky_function():
        import random
        if random.random() < 0.7:  # 70% failure rate
            raise ConnectionError("Network error")
        return "Success!"
    
    # Example 2: Rate limiting
    limiter = RateLimiter(requests_per_second=2)
    
    print("Testing rate limiter (max 2 requests/second):")
    for i in range(5):
        with limiter:
            print(f"Request {i+1} at {time.time():.2f}")
    
    print("\nTesting retry logic:")
    try:
        result = flaky_function()
        print(f"Result: {result}")
    except Exception as e:
        print(f"Failed: {e}")
