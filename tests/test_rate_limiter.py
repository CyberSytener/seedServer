"""
Tests for rate limiter functionality.

Note: These test the *deprecated* sync SQLite rate limiter (app.core.rate_limiter).
Production code now uses the async Redis rate limiter (app.core.rate_limit).
"""
import unittest
import time
import warnings
from unittest.mock import Mock

from app.infrastructure.db.sqlite import DB
from app.core.rate_limiter import RateLimiter, RateLimitConfig, rate_limit_middleware, DEFAULT_LIMITS
from fastapi import HTTPException


class TestRateLimiter(unittest.TestCase):
    """Test rate limiting functionality."""
    
    def setUp(self):
        """Set up test database and rate limiter."""
        self.db = DB(':memory:')
        self.limiter = RateLimiter(self.db)
    
    def tearDown(self):
        """Clean up."""
        self.db.close()
    
    def test_first_request_allowed(self):
        """Test first request is always allowed."""
        result = self.limiter.check_rate_limit(
            user_id="test_user",
            endpoint_category="standard_api"
        )
        self.assertTrue(result)
    
    def test_within_limit_allowed(self):
        """Test requests within limit are allowed."""
        user_id = "test_user"
        category = "standard_api"
        config = RateLimitConfig(max_requests=5, window_seconds=60)
        
        # Make 5 requests (should all succeed)
        for i in range(5):
            result = self.limiter.check_rate_limit(user_id, category, config)
            self.assertTrue(result)
    
    def test_exceed_limit_raises_exception(self):
        """Test exceeding rate limit raises HTTPException."""
        user_id = "test_user_limited"
        category = "test_category"
        config = RateLimitConfig(max_requests=3, window_seconds=60, burst_allowance=0)
        
        # Make 3 requests (should succeed)
        for i in range(3):
            self.limiter.check_rate_limit(user_id, category, config)
        
        # 4th request should fail
        with self.assertRaises(HTTPException) as ctx:
            self.limiter.check_rate_limit(user_id, category, config)
        
        self.assertEqual(ctx.exception.status_code, 429)
        self.assertIn("Retry-After", ctx.exception.headers)
    
    def test_burst_allowance(self):
        """Test burst allowance allows extra requests."""
        user_id = "burst_user"
        category = "burst_test"
        config = RateLimitConfig(max_requests=5, window_seconds=60, burst_allowance=2)
        
        # Should allow 5 + 2 = 7 requests
        for i in range(7):
            result = self.limiter.check_rate_limit(user_id, category, config)
            self.assertTrue(result)
        
        # 8th should fail
        with self.assertRaises(HTTPException):
            self.limiter.check_rate_limit(user_id, category, config)
    
    def test_different_users_independent_limits(self):
        """Test different users have independent rate limits."""
        config = RateLimitConfig(max_requests=2, window_seconds=60)
        
        # User 1 uses their limit
        self.limiter.check_rate_limit("user1", "test", config)
        self.limiter.check_rate_limit("user1", "test", config)
        
        # User 2 should still be able to make requests
        result = self.limiter.check_rate_limit("user2", "test", config)
        self.assertTrue(result)
    
    def test_different_categories_independent_limits(self):
        """Test different endpoint categories have independent limits."""
        user_id = "test_user"
        config = RateLimitConfig(max_requests=2, window_seconds=60)
        
        # Use limit for category1
        self.limiter.check_rate_limit(user_id, "category1", config)
        self.limiter.check_rate_limit(user_id, "category1", config)
        
        # category2 should still be available
        result = self.limiter.check_rate_limit(user_id, "category2", config)
        self.assertTrue(result)
    
    def test_get_user_limits(self):
        """Test getting current user limits."""
        user_id = "status_user"
        config = RateLimitConfig(max_requests=10, window_seconds=60)
        
        # Make some requests
        self.limiter.check_rate_limit(user_id, "test_category", config)
        self.limiter.check_rate_limit(user_id, "test_category", config)
        self.limiter.check_rate_limit(user_id, "test_category", config)
        
        # Get status
        status = self.limiter.get_user_limits(user_id)
        
        self.assertIn("test_category", status)
        self.assertEqual(status["test_category"]["current_count"], 3)
        # Note: get_user_limits uses DEFAULT_LIMITS, not custom config
        # So it will show standard_api limit (100) not our custom 10
        self.assertGreater(status["test_category"]["max_requests"], 0)
        self.assertGreater(status["test_category"]["remaining"], 0)
    
    def test_reset_user_limits(self):
        """Test resetting user limits."""
        user_id = "reset_user"
        config = RateLimitConfig(max_requests=2, window_seconds=60)
        
        # Use up limit
        self.limiter.check_rate_limit(user_id, "test", config)
        self.limiter.check_rate_limit(user_id, "test", config)
        
        # Should be rate limited
        with self.assertRaises(HTTPException):
            self.limiter.check_rate_limit(user_id, "test", config)
        
        # Reset limits
        self.limiter.reset_user_limits(user_id)
        
        # Should be able to make requests again
        result = self.limiter.check_rate_limit(user_id, "test", config)
        self.assertTrue(result)
    
    def test_reset_specific_category(self):
        """Test resetting specific category limits."""
        user_id = "category_reset_user"
        config = RateLimitConfig(max_requests=1, window_seconds=60)
        
        # Use up limits for two categories
        self.limiter.check_rate_limit(user_id, "cat1", config)
        self.limiter.check_rate_limit(user_id, "cat2", config)
        
        # Reset only cat1
        self.limiter.reset_user_limits(user_id, "cat1")
        
        # cat1 should work, cat2 should still be limited
        result = self.limiter.check_rate_limit(user_id, "cat1", config)
        self.assertTrue(result)
        
        with self.assertRaises(HTTPException):
            self.limiter.check_rate_limit(user_id, "cat2", config)
    
    def test_cleanup_old_windows(self):
        """Test cleanup of old rate limit windows."""
        user_id = "cleanup_user"
        
        # Create some rate limit entries
        self.limiter.check_rate_limit(user_id, "test", None)
        
        # Clean up (with cutoff of 0 seconds should delete everything)
        self.limiter.cleanup_old_windows(older_than_seconds=0)
        
        # Verify cleanup happened
        status = self.limiter.get_user_limits(user_id)
        self.assertEqual(len(status), 0)
    
    def test_rate_limit_middleware_integration(self):
        """Test rate limit middleware function."""
        user_id = "middleware_user"
        config = RateLimitConfig(max_requests=2, window_seconds=60)
        
        # Mock request
        request = Mock()
        
        # Should succeed twice
        rate_limit_middleware(request, user_id, "test", self.db, config)
        rate_limit_middleware(request, user_id, "test", self.db, config)
        
        # Third should fail
        with self.assertRaises(HTTPException):
            rate_limit_middleware(request, user_id, "test", self.db, config)
    
    def test_default_limits_used(self):
        """Test default limits are applied when no config provided."""
        user_id = "default_user"
        
        # Use diagnostic_generation which has limit of 10 + 2 burst = 12
        for i in range(12):
            result = self.limiter.check_rate_limit(user_id, "diagnostic_generation")
            self.assertTrue(result)
        
        # 13th should fail
        with self.assertRaises(HTTPException):
            self.limiter.check_rate_limit(user_id, "diagnostic_generation")
    
    def test_admin_api_higher_limits(self):
        """Test admin API has higher limits than standard."""
        user_id = "admin_user"
        
        admin_limit = DEFAULT_LIMITS["admin_api"].max_requests
        standard_limit = DEFAULT_LIMITS["standard_api"].max_requests
        
        # Admin should have higher limit
        self.assertGreater(admin_limit, standard_limit)
    
    def test_retry_after_header_present(self):
        """Test Retry-After header is included in 429 response."""
        user_id = "retry_after_user"
        config = RateLimitConfig(max_requests=1, window_seconds=60)
        
        # Use up limit
        self.limiter.check_rate_limit(user_id, "test", config)
        
        # Next request should include Retry-After
        try:
            self.limiter.check_rate_limit(user_id, "test", config)
            self.fail("Should have raised HTTPException")
        except HTTPException as e:
            self.assertEqual(e.status_code, 429)
            self.assertIn("Retry-After", e.headers)
            retry_after = int(e.headers["Retry-After"])
            self.assertGreater(retry_after, 0)
            self.assertLessEqual(retry_after, 60)


if __name__ == '__main__':
    unittest.main()

