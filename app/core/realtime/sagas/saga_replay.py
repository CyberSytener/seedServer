"""
Saga Replay Mechanism for Disaster Recovery
Re-execute sagas from saved states for recovery and testing.
"""

import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from enum import Enum
import json

logger = logging.getLogger(__name__)


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


# ============================================================================
# Data Models
# ============================================================================

class ReplayMode(Enum):
    """Saga replay modes."""
    FULL = "full"              # Replay entire saga from start
    FROM_STEP = "from_step"    # Replay from specific step
    FROM_CHECKPOINT = "from_checkpoint"  # Replay from checkpoint
    TEST = "test"              # Test replay without side effects


class ReplayStatus(Enum):
    """Replay execution status."""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    PAUSED = "paused"


@dataclass
class SagaSnapshot:
    """Snapshot of saga state at a point in time."""
    saga_id: str
    saga_type: str
    original_saga_id: Optional[str]  # If replay of another saga
    snapshot_time: str
    state: Dict[str, Any]  # Current state at snapshot time
    completed_steps: List[str]  # Steps completed up to snapshot
    input_data: Dict[str, Any]
    metadata: Dict[str, Any]


@dataclass
class ReplayExecution:
    """Record of a replay execution."""
    replay_id: str
    original_saga_id: str
    replay_mode: ReplayMode
    status: ReplayStatus
    started_at: str
    completed_at: Optional[str]
    from_step: Optional[str]
    steps_executed: List[str]
    steps_failed: List[str]
    error_message: Optional[str]
    result: Optional[Dict[str, Any]]


# ============================================================================
# Saga Snapshot Store
# ============================================================================

class SagaSnapshotStore:
    """Stores snapshots of saga states for replay."""
    
    def __init__(self):
        """Initialize snapshot store."""
        self._snapshots: Dict[str, List[SagaSnapshot]] = {}
        logger.info("Saga snapshot store initialized")
    
    def save_snapshot(self, snapshot: SagaSnapshot) -> None:
        """Save a saga snapshot."""
        saga_id = snapshot.saga_id
        if saga_id not in self._snapshots:
            self._snapshots[saga_id] = []
        
        self._snapshots[saga_id].append(snapshot)
        logger.info(f"Saved snapshot for saga {saga_id}")
    
    def get_latest_snapshot(self, saga_id: str) -> Optional[SagaSnapshot]:
        """Get latest snapshot for a saga."""
        if saga_id in self._snapshots and self._snapshots[saga_id]:
            return self._snapshots[saga_id][-1]
        return None
    
    def get_snapshot_at_step(
        self,
        saga_id: str,
        step_name: str
    ) -> Optional[SagaSnapshot]:
        """Get snapshot at specific step."""
        if saga_id not in self._snapshots:
            return None
        
        # Find snapshot where this step was just completed
        for snapshot in self._snapshots[saga_id]:
            if step_name in snapshot.completed_steps:
                return snapshot
        
        return None
    
    def get_snapshot_history(
        self,
        saga_id: str,
        limit: int = 100
    ) -> List[SagaSnapshot]:
        """Get snapshot history for a saga."""
        if saga_id not in self._snapshots:
            return []
        return self._snapshots[saga_id][-limit:]
    
    def get_snapshots_by_type(self, saga_type: str) -> List[SagaSnapshot]:
        """Get all snapshots for a saga type."""
        result = []
        for snapshots in self._snapshots.values():
            for snapshot in snapshots:
                if snapshot.saga_type == saga_type:
                    result.append(snapshot)
        return result


# ============================================================================
# Saga Replay Manager
# ============================================================================

class SagaReplayManager:
    """Manages saga replay for disaster recovery."""
    
    def __init__(self):
        """Initialize replay manager."""
        self._snapshot_store = SagaSnapshotStore()
        self._replay_executions: Dict[str, ReplayExecution] = {}
        self._replay_counter = 0
        logger.info("Saga replay manager initialized")
    
    # ========================================================================
    # Snapshot Management
    # ========================================================================
    
    def create_snapshot(
        self,
        saga_id: str,
        saga_type: str,
        state: Dict[str, Any],
        completed_steps: List[str],
        input_data: Dict[str, Any]
    ) -> SagaSnapshot:
        """Create and save a saga snapshot."""
        snapshot = SagaSnapshot(
            saga_id=saga_id,
            saga_type=saga_type,
            original_saga_id=None,
            snapshot_time=datetime.now(timezone.utc).isoformat(),
            state=state,
            completed_steps=completed_steps,
            input_data=input_data,
            metadata={
                "created_by": "automatic",
                "version": "1.0"
            }
        )
        
        self._snapshot_store.save_snapshot(snapshot)
        logger.info(f"Created snapshot for saga {saga_id}")
        return snapshot
    
    def get_snapshots_for_saga(self, saga_id: str) -> List[SagaSnapshot]:
        """Get all snapshots for a saga."""
        return self._snapshot_store.get_snapshot_history(saga_id)
    
    # ========================================================================
    # Replay Execution
    # ========================================================================
    
    def start_replay(
        self,
        original_saga_id: str,
        mode: ReplayMode = ReplayMode.FULL,
        from_step: Optional[str] = None
    ) -> str:
        """Start a saga replay.
        
        Returns:
            replay_id: Unique identifier for this replay execution
        """
        self._replay_counter += 1
        replay_id = f"replay-{original_saga_id}-{self._replay_counter}"
        
        snapshot = self._snapshot_store.get_latest_snapshot(original_saga_id)
        if not snapshot:
            logger.warning(f"No snapshot found for saga {original_saga_id}")
            return replay_id
        
        execution = ReplayExecution(
            replay_id=replay_id,
            original_saga_id=original_saga_id,
            replay_mode=mode,
            status=ReplayStatus.PENDING,
            started_at=datetime.now(timezone.utc).isoformat(),
            completed_at=None,
            from_step=from_step,
            steps_executed=[],
            steps_failed=[],
            error_message=None,
            result=None
        )
        
        self._replay_executions[replay_id] = execution
        logger.info(f"Started replay {replay_id} for saga {original_saga_id}")
        
        return replay_id
    
    def get_replay_status(self, replay_id: str) -> Optional[ReplayExecution]:
        """Get status of a replay execution."""
        return self._replay_executions.get(replay_id)
    
    def record_replay_step(
        self,
        replay_id: str,
        step_name: str,
        success: bool,
        error: Optional[str] = None
    ) -> None:
        """Record execution of a step in replay."""
        if replay_id not in self._replay_executions:
            return
        
        execution = self._replay_executions[replay_id]
        
        if success:
            execution.steps_executed.append(step_name)
            logger.debug(f"Replay {replay_id}: step {step_name} executed")
        else:
            execution.steps_failed.append(step_name)
            if error:
                execution.error_message = error
            logger.warning(f"Replay {replay_id}: step {step_name} failed: {error}")
    
    def complete_replay(
        self,
        replay_id: str,
        success: bool,
        result: Optional[Dict[str, Any]] = None
    ) -> None:
        """Mark replay as completed."""
        if replay_id not in self._replay_executions:
            return
        
        execution = self._replay_executions[replay_id]
        execution.status = ReplayStatus.SUCCESS if success else ReplayStatus.FAILED
        execution.completed_at = datetime.now(timezone.utc).isoformat()
        execution.result = result
        
        logger.info(f"Replay {replay_id} completed: {execution.status.value}")
    
    # ========================================================================
    # Replay Modes
    # ========================================================================
    
    def replay_full(self, saga_id: str) -> str:
        """Replay saga from the beginning.
        
        Used for: Recovering failed sagas, testing saga logic
        """
        return self.start_replay(saga_id, ReplayMode.FULL)
    
    def replay_from_step(self, saga_id: str, step_name: str) -> str:
        """Replay saga from a specific step.
        
        Used for: Recovering from partial failure, retrying specific steps
        """
        return self.start_replay(saga_id, ReplayMode.FROM_STEP, step_name)
    
    def replay_from_checkpoint(self, saga_id: str) -> str:
        """Replay from last checkpoint.
        
        Used for: Quick recovery from recent failures
        """
        return self.start_replay(saga_id, ReplayMode.FROM_CHECKPOINT)
    
    def test_replay(self, saga_id: str) -> str:
        """Test replay without executing side effects.
        
        Used for: Validating saga can be replayed before recovery
        """
        return self.start_replay(saga_id, ReplayMode.TEST)
    
    # ========================================================================
    # Replay Statistics and Reporting
    # ========================================================================
    
    def get_replay_statistics(self) -> Dict[str, Any]:
        """Get statistics about replay operations."""
        total = len(self._replay_executions)
        successful = len([
            r for r in self._replay_executions.values()
            if r.status == ReplayStatus.SUCCESS
        ])
        failed = len([
            r for r in self._replay_executions.values()
            if r.status == ReplayStatus.FAILED
        ])
        
        return {
            "total_replays": total,
            "successful": successful,
            "failed": failed,
            "success_rate": successful / total if total > 0 else 0.0,
            "by_mode": self._get_replays_by_mode(),
            "average_steps_executed": self._get_average_steps_executed()
        }
    
    def _get_replays_by_mode(self) -> Dict[str, int]:
        """Get count of replays by mode."""
        by_mode = {}
        for execution in self._replay_executions.values():
            mode = execution.replay_mode.value
            by_mode[mode] = by_mode.get(mode, 0) + 1
        return by_mode
    
    def _get_average_steps_executed(self) -> float:
        """Get average number of steps executed in replays."""
        if not self._replay_executions:
            return 0.0
        
        total_steps = sum(
            len(r.steps_executed) for r in self._replay_executions.values()
        )
        return total_steps / len(self._replay_executions)
    
    def get_replay_history(
        self,
        original_saga_id: str,
        limit: int = 10
    ) -> List[ReplayExecution]:
        """Get replay history for a saga."""
        replays = [
            r for r in self._replay_executions.values()
            if r.original_saga_id == original_saga_id
        ]
        return replays[-limit:]
    
    # ========================================================================
    # Recovery Scenarios
    # ========================================================================
    
    def recover_from_failure(
        self,
        saga_id: str,
        failure_step: str
    ) -> str:
        """Recover saga from a specific failure point.
        
        Strategy:
        1. Get snapshot before failure
        2. Restart from step after the failed one
        3. Continue execution
        """
        logger.info(f"Recovering saga {saga_id} from failure at step {failure_step}")
        
        # Find snapshot just before failure
        snapshot = self._snapshot_store.get_snapshot_at_step(saga_id, failure_step)
        if not snapshot:
            logger.warning(f"No snapshot found at step {failure_step}")
        
        # Start replay from the failed step
        replay_id = self.replay_from_step(saga_id, failure_step)
        logger.info(f"Started recovery replay: {replay_id}")
        
        return replay_id
    
    def disaster_recovery(self, saga_ids: List[str]) -> Dict[str, str]:
        """Recover multiple sagas after disaster.
        
        Replays multiple sagas in order.
        """
        results = {}
        for saga_id in saga_ids:
            replay_id = self.replay_full(saga_id)
            results[saga_id] = replay_id
            logger.info(f"Disaster recovery: replaying {saga_id} as {replay_id}")
        
        return results
    
    def verify_replay_capability(self, saga_id: str) -> bool:
        """Check if a saga can be replayed.
        
        Returns:
            True if saga has snapshots and can be replayed
        """
        snapshot = self._snapshot_store.get_latest_snapshot(saga_id)
        return snapshot is not None
    
    # ========================================================================
    # Export and Import
    # ========================================================================
    
    def export_snapshot(self, saga_id: str) -> Optional[str]:
        """Export snapshot as JSON for backup/transfer."""
        snapshot = self._snapshot_store.get_latest_snapshot(saga_id)
        if not snapshot:
            return None
        
        data = asdict(snapshot)
        return json.dumps(data, indent=2, default=str)
    
    def import_snapshot(self, snapshot_json: str) -> Optional[SagaSnapshot]:
        """Import snapshot from JSON."""
        try:
            data = json.loads(snapshot_json)
            snapshot = SagaSnapshot(**data)
            self._snapshot_store.save_snapshot(snapshot)
            logger.info(f"Imported snapshot for saga {snapshot.saga_id}")
            return snapshot
        except Exception as e:
            logger.error(f"Failed to import snapshot: {e}")
            return None
    
    def export_all_snapshots_for_saga(self, saga_id: str) -> Optional[str]:
        """Export all snapshots for a saga."""
        snapshots = self._snapshot_store.get_snapshot_history(saga_id)
        if not snapshots:
            return None
        
        data = [asdict(s) for s in snapshots]
        return json.dumps(data, indent=2, default=str)
    
    # ========================================================================
    # Cleanup
    # ========================================================================
    
    def cleanup_old_replays(self, keep_days: int = 30) -> int:
        """Remove old replay records.
        
        Returns:
            Number of records deleted
        """
        cutoff_time = datetime.now(timezone.utc).timestamp() - (keep_days * 86400)
        deleted = 0
        
        ids_to_delete = []
        for replay_id, execution in self._replay_executions.items():
            try:
                exec_time = _ensure_utc(
                    datetime.fromisoformat(execution.completed_at or execution.started_at)
                ).timestamp()
                if exec_time < cutoff_time:
                    ids_to_delete.append(replay_id)
                    deleted += 1
            except Exception as e:
                logger.debug(f"Error parsing time for {replay_id}: {e}")
        
        for replay_id in ids_to_delete:
            del self._replay_executions[replay_id]
        
        logger.info(f"Cleaned up {deleted} old replay records")
        return deleted


# ============================================================================
# Global Replay Manager Instance
# ============================================================================

_replay_manager_instance: Optional[SagaReplayManager] = None


def get_replay_manager() -> SagaReplayManager:
    """Get or create global replay manager."""
    global _replay_manager_instance
    if _replay_manager_instance is None:
        _replay_manager_instance = SagaReplayManager()
    return _replay_manager_instance
