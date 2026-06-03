"""
Integration tests for authentication flows.
Tests both Bearer token and legacy X-User-ID authentication.
"""
import os
import unittest
from datetime import datetime, timezone
from unittest.mock import Mock

from app.infrastructure.db.sqlite import DB
from app.core.auth import authenticate, issue_api_key, _hash_key, issue_key_for_user


class TestAuthFlows(unittest.TestCase):
    """Test authentication flows and user creation."""
    
    def setUp(self):
        """Set up test database and ensure admin key present for unittest contexts."""
        import os
        # Ensure admin key is present and non-empty for unittest tests
        os.environ['SEED_ADMIN_KEY'] = os.environ.get('SEED_ADMIN_KEY') or 'test_admin_key_pytest'
        self.db = DB(':memory:')
        
        # Create users table with all required columns
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                api_key_hash TEXT,
                api_key_last4 TEXT,
                api_key_created_at TEXT,
                is_admin INTEGER DEFAULT 0,
                is_banned INTEGER DEFAULT 0
            )
        """)
        
        # Note: Environment variables are automatically set by conftest.py mock_environment fixture
        # No need to manually set SEED_ADMIN_KEY or other env vars
    
    def tearDown(self):
        """Clean up."""
        self.db.close()
    
    def test_bearer_token_auth_valid_key(self):
        """Test authentication with valid Bearer token."""
        # Create user with API key
        user_id = "test_user_1"
        now = datetime.now(timezone.utc).isoformat()
        self.db.execute(
            "INSERT INTO users(id, created_at) VALUES(?, ?)",
            (user_id, now)
        )
        
        api_key = issue_api_key()
        key_hash = _hash_key(api_key)
        self.db.execute(
            "UPDATE users SET api_key_hash = ? WHERE id = ?",
            (key_hash, user_id)
        )
        
        # Mock request with Bearer token
        request = Mock()
        request.headers = {"Authorization": f"Bearer {api_key}"}
        request.client.host = "127.0.0.1"
        request.url.path = "/test"
        
        # Authenticate
        auth_ctx = authenticate(request, self.db)
        
        self.assertEqual(auth_ctx.user_id, user_id)
        self.assertFalse(auth_ctx.is_admin)
    
    def test_bearer_token_auth_invalid_key(self):
        """Test authentication with invalid Bearer token."""
        request = Mock()
        request.headers = {"Authorization": "Bearer invalid_key_12345"}
        request.client.host = "127.0.0.1"
        request.url.path = "/test"
        
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as ctx:
            authenticate(request, self.db)
        
        self.assertEqual(ctx.exception.status_code, 401)
        self.assertEqual(ctx.exception.detail, "invalid api key")
    
    def test_x_api_key_header_auth(self):
        """Test authentication with X-API-Key header (backward compat)."""
        # Create user with API key
        user_id = "test_user_2"
        now = datetime.now(timezone.utc).isoformat()
        self.db.execute(
            "INSERT INTO users(id, created_at) VALUES(?, ?)",
            (user_id, now)
        )
        
        api_key = issue_api_key()
        key_hash = _hash_key(api_key)
        self.db.execute(
            "UPDATE users SET api_key_hash = ? WHERE id = ?",
            (key_hash, user_id)
        )
        
        # Mock request with X-API-Key header
        request = Mock()
        request.headers = {"X-API-Key": api_key}
        request.client.host = "127.0.0.1"
        request.url.path = "/test"
        
        # Authenticate
        auth_ctx = authenticate(request, self.db)
        
        self.assertEqual(auth_ctx.user_id, user_id)
        self.assertFalse(auth_ctx.is_admin)
    
    def test_legacy_x_user_id_requires_existing_user(self):
        """Test legacy X-User-ID rejects unknown users (no auto-creation)."""
        from fastapi import HTTPException
        user_id = "legacy_user_test"
        
        # Verify user doesn't exist
        existing = self.db.fetchone("SELECT id FROM users WHERE id = ?", (user_id,))
        self.assertIsNone(existing)
        
        # Mock request with X-User-ID
        request = Mock()
        request.headers = {"X-User-ID": user_id}
        request.client.host = "127.0.0.1"
        request.url.path = "/test"
        
        # Authenticate should reject unknown user
        with self.assertRaises(HTTPException) as ctx:
            authenticate(request, self.db)
        self.assertEqual(ctx.exception.status_code, 401)
        self.assertEqual(ctx.exception.detail, "unknown user")

    def test_legacy_x_user_id_returns_existing_user(self):
        """Test legacy X-User-ID authenticates pre-existing user."""
        user_id = "legacy_user_test"
        now = datetime.now(timezone.utc).isoformat()
        self.db.execute(
            "INSERT INTO users(id, created_at) VALUES(?, ?)",
            (user_id, now)
        )
        
        request = Mock()
        request.headers = {"X-User-ID": user_id}
        request.client.host = "127.0.0.1"
        request.url.path = "/test"
        
        auth_ctx = authenticate(request, self.db)
        self.assertEqual(auth_ctx.user_id, user_id)
        self.assertFalse(auth_ctx.is_admin)
    
    def test_legacy_x_user_id_invalid_format(self):
        """Test legacy X-User-ID rejects invalid format."""
        invalid_ids = [
            "user with spaces",
            "user@email.com",
            "user/slash",
            "x" * 101,  # Too long
            "",  # Empty
        ]
        
        from fastapi import HTTPException
        for invalid_id in invalid_ids:
            request = Mock()
            request.headers = {"X-User-ID": invalid_id}
            request.client.host = "127.0.0.1"
            request.url.path = "/test"
            
            with self.assertRaises(HTTPException) as ctx:
                authenticate(request, self.db)
            
            # Invalid format returns 400, empty string returns 401 (missing)
            self.assertIn(ctx.exception.status_code, [400, 401])
    
    def test_admin_key_auth(self):
        """Test admin authentication."""
        # Use admin key from environment (set by conftest.py)
        admin_key = os.environ.get('SEED_ADMIN_KEY', 'test_admin_key_pytest')
        
        # Ensure environment explicitly set for unittest context
        os.environ['SEED_ADMIN_KEY'] = admin_key

        request = Mock()
        request.headers = {"X-Admin-Key": admin_key}
        request.client.host = "127.0.0.1"
        request.url.path = "/admin"
        
        auth_ctx = authenticate(request, self.db)
        
        self.assertEqual(auth_ctx.user_id, "admin")
        self.assertTrue(auth_ctx.is_admin)
    
    def test_banned_user(self):
        """Test banned user cannot authenticate."""
        user_id = "banned_user"
        now = datetime.now(timezone.utc).isoformat()
        self.db.execute(
            "INSERT INTO users(id, created_at, is_banned) VALUES(?, ?, 1)",
            (user_id, now)
        )
        
        api_key = issue_api_key()
        key_hash = _hash_key(api_key)
        self.db.execute(
            "UPDATE users SET api_key_hash = ? WHERE id = ?",
            (key_hash, user_id)
        )
        
        request = Mock()
        request.headers = {"Authorization": f"Bearer {api_key}"}
        request.client.host = "127.0.0.1"
        request.url.path = "/test"
        
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as ctx:
            authenticate(request, self.db)
        
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertEqual(ctx.exception.detail, "banned")
    
    def test_missing_auth(self):
        """Test request with no authentication fails."""
        # Disable legacy mode
        old_val = os.environ.get('SEED_ENABLE_LEGACY_X_USER_ID')
        os.environ['SEED_ENABLE_LEGACY_X_USER_ID'] = '0'
        try:
            request = Mock()
            request.headers = {}
            request.client.host = "127.0.0.1"
            request.url.path = "/test"
            
            from fastapi import HTTPException
            with self.assertRaises(HTTPException) as ctx:
                authenticate(request, self.db)
            
            self.assertEqual(ctx.exception.status_code, 401)
            self.assertEqual(ctx.exception.detail, "missing api key")
        finally:
            if old_val is not None:
                os.environ['SEED_ENABLE_LEGACY_X_USER_ID'] = old_val
            else:
                os.environ.pop('SEED_ENABLE_LEGACY_X_USER_ID', None)
    
    def test_issue_key_for_existing_user(self):
        """Test issuing API key for existing user."""
        user_id = "existing_user"
        now = datetime.now(timezone.utc).isoformat()
        self.db.execute(
            "INSERT INTO users(id, created_at) VALUES(?, ?)",
            (user_id, now)
        )
        
        # Issue key
        api_key = issue_key_for_user(self.db, user_id)
        
        self.assertIsNotNone(api_key)
        self.assertTrue(api_key.startswith("seed_"))
        
        # Verify key hash is stored
        key_hash = _hash_key(api_key)
        user = self.db.fetchone("SELECT api_key_hash FROM users WHERE id = ?", (user_id,))
        self.assertEqual(user['api_key_hash'], key_hash)
    
    def test_issue_key_for_nonexistent_user(self):
        """Test issuing API key for non-existent user fails."""
        with self.assertRaises(ValueError):
            issue_key_for_user(self.db, "nonexistent_user")
    
    def test_legacy_user_rejects_nonexistent_user(self):
        """Test legacy X-User-ID rejects nonexistent user (no auto-creation)."""
        from fastapi import HTTPException
        user_id = "safe_defaults_user"
        
        request = Mock()
        request.headers = {"X-User-ID": user_id}
        request.client.host = "127.0.0.1"
        request.url.path = "/test"
        
        with self.assertRaises(HTTPException) as ctx:
            authenticate(request, self.db)
        self.assertEqual(ctx.exception.status_code, 401)
    
    def test_null_banned_field_handled_safely(self):
        """Test NULL is_banned field is treated as not banned."""
        user_id = "null_banned_user"
        now = datetime.now(timezone.utc).isoformat()
        
        # Create user with NULL is_banned
        self.db.execute(
            "INSERT INTO users(id, created_at, is_banned) VALUES(?, ?, NULL)",
            (user_id, now)
        )
        
        api_key = issue_api_key()
        key_hash = _hash_key(api_key)
        self.db.execute(
            "UPDATE users SET api_key_hash = ? WHERE id = ?",
            (key_hash, user_id)
        )
        
        request = Mock()
        request.headers = {"Authorization": f"Bearer {api_key}"}
        request.client.host = "127.0.0.1"
        request.url.path = "/test"
        
        # Should not raise exception despite NULL is_banned
        auth_ctx = authenticate(request, self.db)
        self.assertEqual(auth_ctx.user_id, user_id)
        self.assertFalse(auth_ctx.is_admin)
    
    def test_repeated_legacy_auth_with_existing_user(self):
        """Test repeated legacy X-User-ID auth with pre-existing user."""
        user_id = "concurrent_user"
        now = datetime.now(timezone.utc).isoformat()
        self.db.execute(
            "INSERT INTO users(id, created_at) VALUES(?, ?)",
            (user_id, now)
        )
        
        request = Mock()
        request.headers = {"X-User-ID": user_id}
        request.client.host = "127.0.0.1"
        request.url.path = "/test"
        
        # First auth
        auth_ctx1 = authenticate(request, self.db)
        self.assertEqual(auth_ctx1.user_id, user_id)
        
        # Second auth with same user_id should work fine
        auth_ctx2 = authenticate(request, self.db)
        self.assertEqual(auth_ctx2.user_id, user_id)
        
        # Verify still one user
        count = self.db.fetchone(
            "SELECT COUNT(*) as cnt FROM users WHERE id = ?", 
            (user_id,)
        )
        self.assertEqual(count['cnt'], 1)


if __name__ == '__main__':
    unittest.main()

