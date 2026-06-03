"""
Authorization and Access Control for Saga Orchestrator.
Implements role-based access control (RBAC) for saga operations.
"""

from enum import Enum
from typing import Optional, Dict, Set, List
from dataclasses import dataclass
from functools import wraps
import logging

logger = logging.getLogger(__name__)


class SagaRole(str, Enum):
    """Saga system roles."""
    ADMIN = "admin"              # Full access to all operations
    OPERATOR = "operator"        # Can resume, pause, monitor sagas
    VIEWER = "viewer"            # Read-only access
    SERVICE_ACCOUNT = "service"  # For programmatic access


class SagaPermission(str, Enum):
    """Saga system permissions."""
    # Saga lifecycle
    SAGA_START = "saga:start"
    SAGA_RESUME = "saga:resume"
    SAGA_PAUSE = "saga:pause"
    SAGA_CANCEL = "saga:cancel"
    SAGA_COMPENSATE = "saga:compensate"
    
    # Monitoring
    SAGA_VIEW = "saga:view"
    SAGA_VIEW_METRICS = "saga:view_metrics"
    SAGA_VIEW_AUDIT = "saga:view_audit"
    
    # DLQ Management
    DLQ_VIEW = "dlq:view"
    DLQ_RETRY = "dlq:retry"
    DLQ_DELETE = "dlq:delete"
    
    # System
    SYSTEM_ADMIN = "system:admin"
    SYSTEM_CONFIG = "system:config"


# Role to Permissions mapping
ROLE_PERMISSIONS: Dict[SagaRole, Set[SagaPermission]] = {
    SagaRole.ADMIN: {
        # Admin has all permissions
        SagaPermission.SAGA_START,
        SagaPermission.SAGA_RESUME,
        SagaPermission.SAGA_PAUSE,
        SagaPermission.SAGA_CANCEL,
        SagaPermission.SAGA_COMPENSATE,
        SagaPermission.SAGA_VIEW,
        SagaPermission.SAGA_VIEW_METRICS,
        SagaPermission.SAGA_VIEW_AUDIT,
        SagaPermission.DLQ_VIEW,
        SagaPermission.DLQ_RETRY,
        SagaPermission.DLQ_DELETE,
        SagaPermission.SYSTEM_ADMIN,
        SagaPermission.SYSTEM_CONFIG,
    },
    SagaRole.OPERATOR: {
        # Operator can manage saga lifecycle and view everything
        SagaPermission.SAGA_START,
        SagaPermission.SAGA_RESUME,
        SagaPermission.SAGA_PAUSE,
        SagaPermission.SAGA_CANCEL,
        SagaPermission.SAGA_COMPENSATE,
        SagaPermission.SAGA_VIEW,
        SagaPermission.SAGA_VIEW_METRICS,
        SagaPermission.SAGA_VIEW_AUDIT,
        SagaPermission.DLQ_VIEW,
        SagaPermission.DLQ_RETRY,
    },
    SagaRole.VIEWER: {
        # Viewer can only view
        SagaPermission.SAGA_VIEW,
        SagaPermission.SAGA_VIEW_METRICS,
        SagaPermission.SAGA_VIEW_AUDIT,
        SagaPermission.DLQ_VIEW,
    },
    SagaRole.SERVICE_ACCOUNT: {
        # Service account can start and resume sagas
        SagaPermission.SAGA_START,
        SagaPermission.SAGA_RESUME,
        SagaPermission.SAGA_VIEW,
        SagaPermission.SAGA_VIEW_METRICS,
    },
}


@dataclass
class SagaUser:
    """Represents a user/principal in the saga system."""
    user_id: str              # Unique user identifier
    username: str             # Username
    roles: List[SagaRole]     # Assigned roles
    groups: List[str]         # User groups
    
    def has_permission(self, permission: SagaPermission) -> bool:
        """Check if user has permission."""
        for role in self.roles:
            if permission in ROLE_PERMISSIONS.get(role, set()):
                return True
        return False
    
    def has_any_permission(self, permissions: List[SagaPermission]) -> bool:
        """Check if user has any of the given permissions."""
        return any(self.has_permission(p) for p in permissions)
    
    def has_all_permissions(self, permissions: List[SagaPermission]) -> bool:
        """Check if user has all of the given permissions."""
        return all(self.has_permission(p) for p in permissions)


class SagaAuthorizationError(Exception):
    """Raised when user lacks required permissions."""
    def __init__(self, user_id: str, permission: SagaPermission, resource: str = ""):
        self.user_id = user_id
        self.permission = permission
        self.resource = resource
        message = f"User {user_id} lacks permission {permission.value}"
        if resource:
            message += f" for {resource}"
        super().__init__(message)


class SagaAuthorizationManager:
    """Manages authorization checks for saga operations."""
    
    def __init__(self):
        """Initialize authorization manager."""
        self.current_user: Optional[SagaUser] = None
        self.audit_enabled = True
    
    def set_current_user(self, user: SagaUser) -> None:
        """Set the current user context."""
        self.current_user = user
        logger.debug(f"User context set: {user.username} (roles: {[r.value for r in user.roles]})")
    
    def check_permission(
        self,
        permission: SagaPermission,
        resource: str = "",
    ) -> bool:
        """
        Check if current user has required permission.
        
        Raises:
            SagaAuthorizationError: If user lacks permission
            RuntimeError: If no user context set
        """
        if self.current_user is None:
            raise RuntimeError("No user context set for authorization check")
        
        if not self.current_user.has_permission(permission):
            raise SagaAuthorizationError(
                self.current_user.user_id,
                permission,
                resource
            )
        
        logger.info(f"Authorization granted: {self.current_user.username} → {permission.value} on {resource}")
        return True
    
    def require_permission(self, permission: SagaPermission):
        """
        Decorator to require permission for a function.
        
        Usage:
            @auth_manager.require_permission(SagaPermission.SAGA_RESUME)
            async def resume_saga(saga_id: str):
                ...
        """
        def decorator(func):
            @wraps(func)
            async def async_wrapper(*args, **kwargs):
                self.check_permission(permission, resource=func.__name__)
                return await func(*args, **kwargs)
            
            @wraps(func)
            def sync_wrapper(*args, **kwargs):
                self.check_permission(permission, resource=func.__name__)
                return func(*args, **kwargs)
            
            # Return appropriate wrapper
            return async_wrapper if hasattr(func, "__await__") else sync_wrapper
        
        return decorator


class SagaRoleManager:
    """Manages user roles and permissions."""
    
    def __init__(self):
        """Initialize role manager."""
        self.user_roles: Dict[str, List[SagaRole]] = {}
        self.user_groups: Dict[str, List[str]] = {}
    
    def assign_role(self, user_id: str, role: SagaRole) -> None:
        """Assign role to user."""
        if user_id not in self.user_roles:
            self.user_roles[user_id] = []
        
        if role not in self.user_roles[user_id]:
            self.user_roles[user_id].append(role)
            logger.info(f"Role {role.value} assigned to user {user_id}")
    
    def revoke_role(self, user_id: str, role: SagaRole) -> None:
        """Revoke role from user."""
        if user_id in self.user_roles and role in self.user_roles[user_id]:
            self.user_roles[user_id].remove(role)
            logger.info(f"Role {role.value} revoked from user {user_id}")
    
    def add_group(self, user_id: str, group: str) -> None:
        """Add user to group."""
        if user_id not in self.user_groups:
            self.user_groups[user_id] = []
        
        if group not in self.user_groups[user_id]:
            self.user_groups[user_id].append(group)
            logger.info(f"User {user_id} added to group {group}")
    
    def get_user(self, user_id: str, username: str) -> SagaUser:
        """Get user object with assigned roles and groups."""
        roles = self.user_roles.get(user_id, [SagaRole.VIEWER])
        groups = self.user_groups.get(user_id, [])
        
        return SagaUser(
            user_id=user_id,
            username=username,
            roles=roles,
            groups=groups
        )


# Global instances
_auth_manager: Optional[SagaAuthorizationManager] = None
_role_manager: Optional[SagaRoleManager] = None


def get_authorization_manager() -> SagaAuthorizationManager:
    """Get or create global authorization manager."""
    global _auth_manager
    if _auth_manager is None:
        _auth_manager = SagaAuthorizationManager()
    return _auth_manager


def get_role_manager() -> SagaRoleManager:
    """Get or create global role manager."""
    global _role_manager
    if _role_manager is None:
        _role_manager = SagaRoleManager()
    return _role_manager


def require_permission(permission: SagaPermission):
    """
    Decorator to require permission for an endpoint.
    Use with FastAPI route handlers.
    
    Example:
        @app.post("/saga/resume")
        @require_permission(SagaPermission.SAGA_RESUME)
        async def resume_saga(saga_id: str):
            ...
    """
    def decorator(func):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            auth_mgr = get_authorization_manager()
            auth_mgr.check_permission(permission, resource=func.__name__)
            return await func(*args, **kwargs)
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            auth_mgr = get_authorization_manager()
            auth_mgr.check_permission(permission, resource=func.__name__)
            return func(*args, **kwargs)
        
        # Try to detect if async
        import inspect
        if inspect.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper
    
    return decorator
