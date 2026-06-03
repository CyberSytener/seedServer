"""
Feature flags for STEP 4: Safe adapter rollout.

Allows gradual canary deployment of new adapters without full rollout.

Flags control:
- Adapter availability (on/off)
- Canary % (5%, 10%, 50%, 100%)
- Fallback behavior (mock vs real)
"""

import os
import json
import logging
from typing import Dict, Any, Optional
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class RolloutState(str, Enum):
    """Deployment state of adapter."""
    DISABLED = "disabled"        # Off, use mock
    CANARY = "canary"            # Small % traffic
    RAMPING = "ramping"          # Increasing %
    ENABLED = "enabled"          # Full rollout


@dataclass
class FeatureFlag:
    """Feature flag configuration."""
    adapter_type: str
    state: RolloutState = RolloutState.DISABLED
    canary_percentage: int = 0      # 0-100
    fallback_to_mock: bool = True   # If disabled or canary excluded, use mock
    metadata: Dict[str, Any] = None


class FeatureFlagManager:
    """
    Manage adapter feature flags for safe canary rollout.
    
    Sources: ENV vars, config file, or Redis for runtime changes.
    """
    
    def __init__(self):
        """Initialize from environment."""
        self.flags: Dict[str, FeatureFlag] = {}
        self._load_from_env()
    
    def _load_from_env(self):
        """Load flags from environment variables."""
        # Format: FEATURE_ADAPTER_<ADAPTER>_STATE=enabled|canary|disabled
        #         FEATURE_ADAPTER_<ADAPTER>_CANARY=50
        
        adapters = ["booking", "calendar", "payment", "email", "cv_generation"]
        
        for adapter in adapters:
            state_env = f"FEATURE_ADAPTER_{adapter.upper()}_STATE"
            canary_env = f"FEATURE_ADAPTER_{adapter.upper()}_CANARY"
            
            state_str = os.getenv(state_env, "disabled").lower()
            canary_pct = int(os.getenv(canary_env, "0"))
            
            try:
                state = RolloutState(state_str)
            except ValueError:
                state = RolloutState.DISABLED
                logger.warning(f"Invalid state for {adapter}: {state_str}, defaulting to disabled")
            
            flag = FeatureFlag(
                adapter_type=adapter,
                state=state,
                canary_percentage=canary_pct,
                fallback_to_mock=True,  # Always fallback for safety
            )
            
            self.flags[adapter] = flag
            
            logger.info(
                f"Feature flag: {adapter} = {state.value} "
                f"(canary: {canary_pct}%)"
            )
    
    def is_enabled(self, adapter_type: str, user_id: Optional[str] = None) -> bool:
        """
        Check if adapter is enabled for user.
        
        If canary: use hash(user_id) to determine if user is in canary group.
        
        Args:
            adapter_type: Name of adapter ("booking", "calendar", etc.)
            user_id: User ID (for canary bucket assignment)
            
        Returns:
            True if adapter should be used, False if mock should be used
        """
        flag = self.flags.get(adapter_type)
        if not flag:
            logger.warning(f"Unknown adapter: {adapter_type}")
            return False
        
        if flag.state == RolloutState.DISABLED:
            return False
        
        if flag.state == RolloutState.ENABLED:
            return True
        
        if flag.state == RolloutState.CANARY or flag.state == RolloutState.RAMPING:
            # Canary: use hash to determine if user is in canary group
            if not user_id:
                return False  # No user ID, exclude from canary
            
            # Deterministic hash to bucket users (use SHA256 for stability)
            import hashlib
            digest = hashlib.sha256(user_id.encode("utf-8")).hexdigest()
            user_hash = int(digest, 16) % 100
            return user_hash < flag.canary_percentage
        
        return False
    
    def get_adapter(
        self,
        adapter_type: str,
        real_adapter: Any,
        mock_adapter: Any,
        user_id: Optional[str] = None,
    ) -> Any:
        """
        Get adapter instance (real or mock) based on flags.
        
        Args:
            adapter_type: Name of adapter
            real_adapter: Real adapter instance
            mock_adapter: Mock adapter instance
            user_id: User ID (for canary decision)
            
        Returns:
            Adapter instance to use
        """
        if self.is_enabled(adapter_type, user_id):
            logger.info(f"Using real {adapter_type} adapter for user {user_id}")
            return real_adapter
        else:
            logger.info(f"Using mock {adapter_type} adapter for user {user_id}")
            return mock_adapter
    
    def set_state(self, adapter_type: str, state: RolloutState, canary_pct: int = 0, canary_percentage: int | None = None):
        """
        Update flag state at runtime (for testing/operations).
        
        Args:
            adapter_type: Name of adapter
            state: New rollout state
            canary_pct: Canary percentage (if ramping)
            canary_percentage: Alias for canary_pct to support tests using that keyword
        """
        if adapter_type not in self.flags:
            logger.warning(f"Unknown adapter: {adapter_type}")
            return
        
        # Prefer explicit canary_percentage when provided
        pct = canary_percentage if canary_percentage is not None else canary_pct
        self.flags[adapter_type].state = state
        self.flags[adapter_type].canary_percentage = pct
        
        logger.info(f"Feature flag updated: {adapter_type} = {state.value} (canary: {pct}%)")
    
    def get_status(self) -> Dict[str, Any]:
        """Get current flag status (for monitoring)."""
        return {
            adapter: {
                "state": flag.state.value,
                "canary_percentage": flag.canary_percentage,
                "fallback_to_mock": flag.fallback_to_mock,
            }
            for adapter, flag in self.flags.items()
        }


# Global instance
_flag_manager: Optional[FeatureFlagManager] = None


def get_flag_manager() -> FeatureFlagManager:
    """Lazy initialize flag manager."""
    global _flag_manager
    if _flag_manager is None:
        _flag_manager = FeatureFlagManager()
    return _flag_manager


# Example canary rollout strategy
"""
Day 1 - Launch:
  FEATURE_ADAPTER_BOOKING_STATE=disabled
  
Day 2 - Canary 5%:
  FEATURE_ADAPTER_BOOKING_STATE=canary
  FEATURE_ADAPTER_BOOKING_CANARY=5
  
Day 3 - Canary 25%:
  FEATURE_ADAPTER_BOOKING_CANARY=25
  
Day 4 - Ramp 50%:
  FEATURE_ADAPTER_BOOKING_STATE=ramping
  FEATURE_ADAPTER_BOOKING_CANARY=50
  
Day 5 - Full rollout:
  FEATURE_ADAPTER_BOOKING_STATE=enabled
  FEATURE_ADAPTER_BOOKING_CANARY=100
"""
