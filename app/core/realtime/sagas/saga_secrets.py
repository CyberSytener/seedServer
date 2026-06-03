"""
Secret Management for Saga Orchestrator.
Manages credentials, API keys, and sensitive configuration without hardcoding.
"""

import os
from typing import Optional, Dict
import logging
from dataclasses import dataclass
from functools import lru_cache

logger = logging.getLogger(__name__)


class SecretNotFoundError(Exception):
    """Raised when a required secret is not found."""
    def __init__(self, secret_name: str):
        super().__init__(f"Secret not found: {secret_name}")
        self.secret_name = secret_name


class SecretManager:
    """Manages application secrets and sensitive configuration."""
    
    # Supported secret sources (in order of priority)
    SOURCES = ["vault", "env", "file"]
    
    # Default secret names and their required flag
    DEFAULT_SECRETS = {
        # Database
        "saga_db_url": True,
        "saga_db_user": False,
        "saga_db_password": False,
        
        # Redis
        "saga_redis_url": True,
        "saga_redis_password": False,
        
        # Messaging
        "saga_kafka_brokers": False,
        "saga_kafka_username": False,
        "saga_kafka_password": False,
        
        # Notifications
        "slack_webhook_url": False,
        "pagerduty_service_key": False,
        "smtp_host": False,
        "smtp_port": False,
        "smtp_user": False,
        "smtp_password": False,
        
        # Security
        "jwt_secret": False,
        "api_key_secret": False,
        "encryption_key": False,
        
        # Monitoring
        "prometheus_url": False,
        "grafana_api_key": False,
    }
    
    def __init__(self, use_vault: bool = False, vault_addr: Optional[str] = None):
        """
        Initialize secret manager.
        
        Args:
            use_vault: Whether to use HashiCorp Vault
            vault_addr: Vault server address (if using Vault)
        """
        self.use_vault = use_vault
        self.vault_addr = vault_addr or os.getenv("VAULT_ADDR", "http://localhost:8200")
        self.vault_token = os.getenv("VAULT_TOKEN")
        self._secrets_cache: Dict[str, str] = {}
        
        logger.info(f"SecretManager initialized (use_vault={use_vault})")
    
    def get_secret(
        self,
        secret_name: str,
        required: bool = True,
        default: Optional[str] = None,
    ) -> Optional[str]:
        """
        Get a secret value.
        
        Tries sources in order: Vault → Environment → Default
        
        Args:
            secret_name: Name of the secret
            required: Whether secret is required
            default: Default value if not found
            
        Returns:
            Secret value or None
            
        Raises:
            SecretNotFoundError: If required secret not found
        """
        # Check cache first
        if secret_name in self._secrets_cache:
            return self._secrets_cache[secret_name]
        
        # Try to get from Vault
        if self.use_vault and self.vault_token:
            try:
                value = self._get_from_vault(secret_name)
                if value is not None:
                    self._secrets_cache[secret_name] = value
                    return value
            except Exception as e:
                logger.warning(f"Failed to get secret from Vault: {e}")
        
        # Try environment variable (uppercase with SAGA_ prefix)
        env_key = f"SAGA_{secret_name.upper()}"
        value = os.getenv(env_key)
        if value:
            self._secrets_cache[secret_name] = value
            return value
        
        # Try without prefix
        value = os.getenv(secret_name.upper())
        if value:
            self._secrets_cache[secret_name] = value
            return value
        
        # Return default or raise error
        if default is not None:
            return default
        
        if required:
            raise SecretNotFoundError(secret_name)
        
        return None
    
    def _get_from_vault(self, secret_name: str) -> Optional[str]:
        """Get secret from HashiCorp Vault."""
        try:
            import hvac
        except ImportError:
            logger.warning("hvac package not installed, skipping Vault")
            return None
        
        try:
            client = hvac.Client(url=self.vault_addr, token=self.vault_token)
            
            # Assuming secret is stored at /saga/data/{secret_name}
            path = f"saga/data/{secret_name}"
            response = client.secrets.kv.read_secret_version(path=path)
            
            secret_value = response["data"]["data"].get("value")
            logger.debug(f"Secret retrieved from Vault: {secret_name}")
            return secret_value
        
        except Exception as e:
            logger.error(f"Error retrieving secret from Vault: {e}")
            return None
    
    def validate_required_secrets(self) -> bool:
        """
        Validate that all required secrets are available.
        
        Returns:
            True if all required secrets found
            
        Raises:
            SecretNotFoundError: If any required secret missing
        """
        missing_secrets = []
        
        for secret_name, required in self.DEFAULT_SECRETS.items():
            if required:
                try:
                    self.get_secret(secret_name, required=True)
                    logger.debug(f"✓ Secret found: {secret_name}")
                except SecretNotFoundError:
                    missing_secrets.append(secret_name)
                    logger.error(f"✗ Missing required secret: {secret_name}")
        
        if missing_secrets:
            raise SecretNotFoundError(f"Missing {len(missing_secrets)} required secrets: {missing_secrets}")
        
        logger.info("✓ All required secrets validated")
        return True
    
    def get_database_url(self) -> str:
        """Get database connection URL."""
        return self.get_secret("saga_db_url", required=True)
    
    def get_redis_url(self) -> str:
        """Get Redis connection URL."""
        return self.get_secret("saga_redis_url", required=True)
    
    def get_slack_webhook(self) -> Optional[str]:
        """Get Slack webhook URL."""
        return self.get_secret("slack_webhook_url", required=False)
    
    def get_pagerduty_key(self) -> Optional[str]:
        """Get PagerDuty service key."""
        return self.get_secret("pagerduty_service_key", required=False)
    
    def get_smtp_credentials(self) -> Dict[str, str]:
        """Get SMTP credentials."""
        return {
            "host": self.get_secret("smtp_host", required=False, default="localhost"),
            "port": self.get_secret("smtp_port", required=False, default="587"),
            "user": self.get_secret("smtp_user", required=False),
            "password": self.get_secret("smtp_password", required=False),
        }
    
    def get_jwt_secret(self) -> Optional[str]:
        """Get JWT signing secret."""
        return self.get_secret("jwt_secret", required=False)
    
    def get_api_key_secret(self) -> Optional[str]:
        """Get API key secret for hashing."""
        return self.get_secret("api_key_secret", required=False)
    
    def get_encryption_key(self) -> Optional[str]:
        """Get encryption key for sensitive data."""
        return self.get_secret("encryption_key", required=False)
    
    def clear_cache(self) -> None:
        """Clear secret cache."""
        self._secrets_cache.clear()
        logger.info("Secret cache cleared")


@dataclass
class SagaSecretConfig:
    """Configuration loaded from secrets."""
    db_url: str
    redis_url: str
    slack_webhook: Optional[str]
    pagerduty_key: Optional[str]
    jwt_secret: Optional[str]
    encryption_key: Optional[str]


class SecureConfig:
    """Loads all configuration from secrets."""
    
    def __init__(self, secret_manager: Optional[SecretManager] = None):
        """
        Initialize secure config.
        
        Args:
            secret_manager: SecretManager instance (creates default if None)
        """
        self.secret_manager = secret_manager or SecretManager()
    
    def load_saga_config(self) -> SagaSecretConfig:
        """Load Saga configuration from secrets."""
        return SagaSecretConfig(
            db_url=self.secret_manager.get_database_url(),
            redis_url=self.secret_manager.get_redis_url(),
            slack_webhook=self.secret_manager.get_slack_webhook(),
            pagerduty_key=self.secret_manager.get_pagerduty_key(),
            jwt_secret=self.secret_manager.get_jwt_secret(),
            encryption_key=self.secret_manager.get_encryption_key(),
        )
    
    @staticmethod
    def from_environment() -> SagaSecretConfig:
        """Create config loading from environment variables."""
        config = SecureConfig()
        config.secret_manager.validate_required_secrets()
        return config.load_saga_config()


# Global secret manager instance
_secret_manager: Optional[SecretManager] = None


def get_secret_manager(use_vault: bool = False) -> SecretManager:
    """Get or create global secret manager."""
    global _secret_manager
    
    if _secret_manager is None:
        # Check if Vault should be used
        use_vault = use_vault or os.getenv("USE_VAULT", "false").lower() == "true"
        _secret_manager = SecretManager(use_vault=use_vault)
    
    return _secret_manager


# Convenience functions
def get_secret(
    secret_name: str,
    required: bool = True,
    default: Optional[str] = None,
) -> Optional[str]:
    """
    Get a secret using the global secret manager.
    
    Example:
        api_key = get_secret("api_key_secret")
        slack_url = get_secret("slack_webhook", required=False)
    """
    manager = get_secret_manager()
    return manager.get_secret(secret_name, required=required, default=default)


def validate_secrets() -> bool:
    """Validate all required secrets are available."""
    manager = get_secret_manager()
    return manager.validate_required_secrets()


def load_config() -> SagaSecretConfig:
    """Load complete Saga configuration from secrets."""
    config = SecureConfig()
    return config.load_saga_config()
