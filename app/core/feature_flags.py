"""
Feature flags system for gradual rollout and A/B testing.
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Dict, Any

from app.core.interfaces.database import DatabaseProtocol


class RolloutStrategy(str, Enum):
    """Rollout strategy for features."""
    ALL = "all"              # All users
    NONE = "none"            # No users
    PERCENTAGE = "percentage"  # Percentage of users
    WHITELIST = "whitelist"  # Specific user IDs
    A_B_TEST = "a_b_test"    # A/B testing groups


@dataclass
class FeatureFlag:
    """Feature flag configuration."""
    name: str
    enabled: bool
    strategy: RolloutStrategy
    config: Dict[str, Any]  # Strategy-specific config
    description: str = ""


class FeatureFlagManager:
    """Manage feature flags for gradual rollout and testing."""
    
    def __init__(self, db: DatabaseProtocol):
        self.db = db
        self._ensure_tables()
        self._cache: Dict[str, FeatureFlag] = {}
        self._load_flags()
    
    def _ensure_tables(self):
        """Create feature flags table."""
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS feature_flags (
                name TEXT PRIMARY KEY,
                enabled INTEGER NOT NULL DEFAULT 0,
                strategy TEXT NOT NULL DEFAULT 'none',
                config TEXT NOT NULL DEFAULT '{}',
                description TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
    
    def _load_flags(self):
        """Load all flags from database into cache."""
        import json
        
        rows = self.db.fetchall("SELECT * FROM feature_flags")
        for row in rows:
            config = json.loads(row['config']) if row['config'] else {}
            self._cache[row['name']] = FeatureFlag(
                name=row['name'],
                enabled=bool(row['enabled']),
                strategy=RolloutStrategy(row['strategy']),
                config=config,
                description=row['description'] or ""
            )
    
    def create_flag(
        self,
        name: str,
        enabled: bool = False,
        strategy: RolloutStrategy = RolloutStrategy.NONE,
        config: Optional[Dict[str, Any]] = None,
        description: str = ""
    ):
        """Create a new feature flag."""
        import json
        
        config = config or {}
        config_json = json.dumps(config)
        
        self.db.execute("""
            INSERT INTO feature_flags (name, enabled, strategy, config, description)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                enabled = excluded.enabled,
                strategy = excluded.strategy,
                config = excluded.config,
                description = excluded.description,
                updated_at = CURRENT_TIMESTAMP
        """, (name, int(enabled), strategy.value, config_json, description))
        
        self._cache[name] = FeatureFlag(
            name=name,
            enabled=enabled,
            strategy=strategy,
            config=config,
            description=description
        )
    
    def is_enabled(self, flag_name: str, user_id: Optional[str] = None) -> bool:
        """
        Check if a feature flag is enabled for a user.
        
        Args:
            flag_name: Name of the feature flag
            user_id: User ID to check against
            
        Returns:
            True if feature is enabled for this user
        """
        flag = self._cache.get(flag_name)
        if not flag:
            return False  # Unknown flags default to disabled
        
        if not flag.enabled:
            return False
        
        # Strategy-based evaluation
        if flag.strategy == RolloutStrategy.ALL:
            return True
        
        if flag.strategy == RolloutStrategy.NONE:
            return False
        
        if flag.strategy == RolloutStrategy.WHITELIST:
            whitelist = flag.config.get('user_ids', [])
            return user_id in whitelist if user_id else False
        
        if flag.strategy == RolloutStrategy.PERCENTAGE:
            if not user_id:
                return False
            percentage = flag.config.get('percentage', 0)
            return self._hash_user(user_id, flag_name) < percentage
        
        if flag.strategy == RolloutStrategy.A_B_TEST:
            if not user_id:
                return False
            group = self._get_ab_group(user_id, flag_name)
            return group == 'B'  # Group B gets the feature
        
        return False
    
    def get_variant(self, flag_name: str, user_id: Optional[str] = None) -> str:
        """
        Get variant for A/B testing.
        
        Returns:
            'A' for control group, 'B' for treatment group, 'disabled' if not in test
        """
        flag = self._cache.get(flag_name)
        if not flag or not flag.enabled:
            return 'disabled'
        
        if flag.strategy != RolloutStrategy.A_B_TEST:
            return 'A' if not self.is_enabled(flag_name, user_id) else 'B'
        
        if not user_id:
            return 'disabled'
        
        return self._get_ab_group(user_id, flag_name)
    
    def _hash_user(self, user_id: str, flag_name: str) -> int:
        """Hash user ID to get consistent percentage (0-100)."""
        hash_input = f"{flag_name}:{user_id}".encode('utf-8')
        hash_value = int(hashlib.md5(hash_input).hexdigest()[:8], 16)
        return hash_value % 100
    
    def _get_ab_group(self, user_id: str, flag_name: str) -> str:
        """Get A/B test group for user (consistent hashing)."""
        flag = self._cache.get(flag_name)
        if not flag:
            return 'A'
        
        split_percentage = flag.config.get('split_percentage', 50)
        hash_value = self._hash_user(user_id, flag_name)
        
        return 'B' if hash_value < split_percentage else 'A'
    
    def get_all_flags(self) -> Dict[str, FeatureFlag]:
        """Get all feature flags."""
        return self._cache.copy()
    
    def update_flag(
        self,
        name: str,
        enabled: Optional[bool] = None,
        strategy: Optional[RolloutStrategy] = None,
        config: Optional[Dict[str, Any]] = None
    ):
        """Update an existing feature flag."""
        import json
        
        flag = self._cache.get(name)
        if not flag:
            raise ValueError(f"Feature flag '{name}' does not exist")
        
        # Update values
        if enabled is not None:
            flag.enabled = enabled
        if strategy is not None:
            flag.strategy = strategy
        if config is not None:
            flag.config = config
        
        # Save to database
        config_json = json.dumps(flag.config)
        self.db.execute("""
            UPDATE feature_flags 
            SET enabled = ?, strategy = ?, config = ?, updated_at = CURRENT_TIMESTAMP
            WHERE name = ?
        """, (int(flag.enabled), flag.strategy.value, config_json, name))
        
        self._cache[name] = flag


# Initialize default feature flags
DEFAULT_FLAGS = [
    FeatureFlag(
        name="optimized_prompt_v2",
        enabled=True,
        strategy=RolloutStrategy.ALL,
        config={},
        description="Use optimized prompt version 2 with 46% token reduction"
    ),
    FeatureFlag(
        name="optimized_parser_v2",
        enabled=True,
        strategy=RolloutStrategy.ALL,
        config={},
        description="Use optimized parser version 2 with 9% performance improvement"
    ),
    FeatureFlag(
        name="specialized_diagnostics",
        enabled=True,
        strategy=RolloutStrategy.ALL,
        config={},
        description="Enable specialized diagnostic tests (business, medical, etc.)"
    ),
    FeatureFlag(
        name="experimental_prompt_v3",
        enabled=False,
        strategy=RolloutStrategy.PERCENTAGE,
        config={"percentage": 10},
        description="Experimental prompt v3 - rollout to 10% of users"
    ),
    FeatureFlag(
        name="enhanced_validation",
        enabled=False,
        strategy=RolloutStrategy.A_B_TEST,
        config={"split_percentage": 50},
        description="Enhanced validation rules - A/B test with 50/50 split"
    )
]


def initialize_default_flags(db: DB):
    """Initialize default feature flags."""
    manager = FeatureFlagManager(db)
    for flag in DEFAULT_FLAGS:
        manager.create_flag(
            name=flag.name,
            enabled=flag.enabled,
            strategy=flag.strategy,
            config=flag.config,
            description=flag.description
        )
    logging.info(f"Initialized {len(DEFAULT_FLAGS)} default feature flags")


