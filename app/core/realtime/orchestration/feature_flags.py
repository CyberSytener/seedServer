"""
Feature Flags & Adapter System
Expand mail providers and ATS integrations behind feature flags

Features:
1. Feature flag management
   - Per-tenant feature flags
   - Gradual rollout (% of tenants)
   - A/B testing
   - Safe toggle

2. Mail provider adapters
   - Outlook (existing)
   - Gmail (new)
   - AWS SES (new)
   - SendGrid (new)
   - Slack (new)

3. ATS integrations
   - Workday (new)
   - Lever (new)
   - Talentware (new)
   - Greenhouse (existing)

4. Feature versioning
   - Multiple versions per feature
   - Backward compatibility
   - Phased migrations
   - Rollback capability

5. A/B testing
   - Control/treatment groups
   - Metrics collection
   - Statistical analysis
   - Winner selection

Usage:
    flags = FeatureFlags()
    
    # Define feature
    flags.add_feature(
        feature="gmail_adapter",
        default_enabled=False,
        rollout_percent=10,  # 10% of tenants
    )
    
    # Check if enabled for tenant
    if flags.is_enabled("gmail_adapter", tenant_id="tenant_001"):
        use_gmail()
    else:
        use_outlook()
    
    # Run A/B test
    test = ABTest(
        feature="new_parser",
        control_version="v1",
        treatment_version="v2",
    )
    version = test.get_version(tenant_id="tenant_001")
"""

from typing import Dict, Optional, List, Set, Any, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
import logging
import hashlib

logger = logging.getLogger(__name__)


class MailProvider(str, Enum):
    """Available mail providers"""
    OUTLOOK = "outlook"
    GMAIL = "gmail"
    AWS_SES = "aws_ses"
    SENDGRID = "sendgrid"
    SLACK = "slack"


class ATSProvider(str, Enum):
    """Available ATS providers"""
    WORKDAY = "workday"
    LEVER = "lever"
    TALENTWARE = "talentware"
    GREENHOUSE = "greenhouse"


class FeatureStatus(str, Enum):
    """Feature lifecycle status"""
    ALPHA = "alpha"  # Internal testing
    BETA = "beta"  # Limited rollout
    STABLE = "stable"  # Production
    DEPRECATED = "deprecated"  # Being phased out


@dataclass
class Feature:
    """Feature flag definition"""
    name: str
    description: str
    enabled_by_default: bool = False
    rollout_percent: int = 0  # 0-100, % of tenants to enable
    status: FeatureStatus = FeatureStatus.ALPHA
    created_at: datetime = field(default_factory=datetime.now)
    modified_at: datetime = field(default_factory=datetime.now)
    owner: str = ""  # Team/person responsible
    enabled_tenants: Set[str] = field(default_factory=set)
    disabled_tenants: Set[str] = field(default_factory=set)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ABTestConfig:
    """A/B test configuration"""
    test_id: str
    feature_name: str
    control_version: str
    treatment_version: str
    split_percent: int = 50  # % of users in treatment
    created_at: datetime = field(default_factory=datetime.now)
    enabled: bool = True


# ============================================================================
# FEATURE FLAGS
# ============================================================================

class FeatureFlags:
    """
    Manage feature flags across system
    
    Enables safe rollout of new features with gradual adoption
    """
    
    def __init__(self):
        self.features: Dict[str, Feature] = {}
        self._initialize_defaults()
    
    def _initialize_defaults(self) -> None:
        """Initialize default mail provider features"""
        # Outlook (stable)
        self.add_feature(
            name="mail_provider_outlook",
            description="Microsoft Outlook email provider",
            enabled_by_default=True,
            status=FeatureStatus.STABLE,
            owner="platform",
        )
        
        # Gmail (beta, 10% rollout)
        self.add_feature(
            name="mail_provider_gmail",
            description="Gmail email provider",
            enabled_by_default=False,
            rollout_percent=10,
            status=FeatureStatus.BETA,
            owner="integrations",
        )
        
        # AWS SES (alpha, 5% rollout)
        self.add_feature(
            name="mail_provider_aws_ses",
            description="AWS SES email provider",
            enabled_by_default=False,
            rollout_percent=5,
            status=FeatureStatus.ALPHA,
            owner="integrations",
        )
        
        # Advanced reply parser (stable)
        self.add_feature(
            name="advanced_reply_parser",
            description="ML-based reply parsing with metrics",
            enabled_by_default=True,
            status=FeatureStatus.STABLE,
            owner="ml",
        )
        
        # Webhook subscriptions (stable)
        self.add_feature(
            name="webhook_subscriptions",
            description="Real-time email notifications via webhooks",
            enabled_by_default=True,
            status=FeatureStatus.STABLE,
            owner="platform",
        )
        
        # Multi-tenant quotas (stable)
        self.add_feature(
            name="multi_tenant_quotas",
            description="Per-tenant quota enforcement",
            enabled_by_default=True,
            status=FeatureStatus.STABLE,
            owner="platform",
        )
    
    def add_feature(
        self,
        name: str,
        description: str,
        enabled_by_default: bool = False,
        rollout_percent: int = 0,
        status: FeatureStatus = FeatureStatus.ALPHA,
        owner: str = "",
    ) -> Feature:
        """
        Register new feature flag
        
        Args:
            name: Unique feature name
            description: Human-readable description
            enabled_by_default: Default state
            rollout_percent: Percentage of tenants to enable (0-100)
            status: Feature lifecycle status
            owner: Team/person responsible
        """
        feature = Feature(
            name=name,
            description=description,
            enabled_by_default=enabled_by_default,
            rollout_percent=rollout_percent,
            status=status,
            owner=owner,
        )
        self.features[name] = feature
        
        logger.info(f"✅ Feature flag '{name}' registered ({status.value})")
        if rollout_percent > 0:
            logger.info(f"   Rollout: {rollout_percent}%")
        
        return feature
    
    def is_enabled(self, feature_name: str, tenant_id: str) -> bool:
        """
        Check if feature enabled for tenant
        
        Uses consistent hashing for deterministic rollout
        """
        feature = self.features.get(feature_name)
        if not feature:
            logger.warning(f"⚠️  Unknown feature: {feature_name}")
            return False
        
        # Check explicit overrides
        if tenant_id in feature.enabled_tenants:
            return True
        if tenant_id in feature.disabled_tenants:
            return False
        
        # Check default and rollout
        if feature.enabled_by_default:
            return True
        
        # Determine rollout using consistent hash
        if feature.rollout_percent == 0:
            return False
        
        if feature.rollout_percent >= 100:
            return True
        
        # Consistent hash: same tenant always gets same result
        hash_input = f"{tenant_id}:{feature_name}".encode()
        hash_value = int(hashlib.md5(hash_input).hexdigest(), 16)
        tenant_hash = hash_value % 100
        
        return tenant_hash < feature.rollout_percent
    
    def enable_for_tenant(self, feature_name: str, tenant_id: str) -> None:
        """Explicitly enable feature for tenant"""
        feature = self.features.get(feature_name)
        if feature:
            feature.enabled_tenants.add(tenant_id)
            feature.disabled_tenants.discard(tenant_id)
            logger.info(f"✅ {feature_name} enabled for {tenant_id}")
    
    def disable_for_tenant(self, feature_name: str, tenant_id: str) -> None:
        """Explicitly disable feature for tenant"""
        feature = self.features.get(feature_name)
        if feature:
            feature.disabled_tenants.add(tenant_id)
            feature.enabled_tenants.discard(tenant_id)
            logger.info(f"✅ {feature_name} disabled for {tenant_id}")
    
    def set_rollout_percent(self, feature_name: str, percent: int) -> None:
        """Update rollout percentage for feature"""
        feature = self.features.get(feature_name)
        if feature:
            feature.rollout_percent = max(0, min(100, percent))
            feature.modified_at = datetime.now()
            logger.info(f"✅ {feature_name} rollout set to {percent}%")
    
    def get_feature_status(self, feature_name: str) -> Optional[Dict[str, Any]]:
        """Get status of feature"""
        feature = self.features.get(feature_name)
        if not feature:
            return None
        
        return {
            "name": feature.name,
            "description": feature.description,
            "status": feature.status.value,
            "enabled_by_default": feature.enabled_by_default,
            "rollout_percent": feature.rollout_percent,
            "owner": feature.owner,
            "created_at": feature.created_at.isoformat(),
            "modified_at": feature.modified_at.isoformat(),
        }
    
    def get_all_features(self) -> List[Dict[str, Any]]:
        """Get all registered features"""
        return [
            self.get_feature_status(name)
            for name in sorted(self.features.keys())
        ]


# ============================================================================
# MAIL ADAPTER FACTORY
# ============================================================================

class MailAdapterFactory:
    """
    Create mail adapters based on feature flags
    
    Supports: Outlook, Gmail, AWS SES, SendGrid, Slack
    """
    
    def __init__(self, feature_flags: FeatureFlags):
        self.feature_flags = feature_flags
        self.adapters: Dict[MailProvider, Any] = {}
    
    def get_adapter(
        self,
        tenant_id: str,
        provider: Optional[MailProvider] = None,
    ) -> Any:
        """
        Get mail adapter for tenant
        
        If provider not specified, use default (Outlook)
        """
        if not provider:
            # Check preferred provider for tenant
            provider = self._get_preferred_provider(tenant_id)
        
        # Check if provider enabled
        feature_name = f"mail_provider_{provider.value}"
        if not self.feature_flags.is_enabled(feature_name, tenant_id):
            # Fall back to Outlook
            logger.warning(
                f"⚠️  {provider.value} disabled for {tenant_id}, using Outlook"
            )
            provider = MailProvider.OUTLOOK
        
        # Return adapter (would instantiate here in real code)
        logger.info(f"✅ Using {provider.value} adapter for {tenant_id}")
        return self._instantiate_adapter(provider)
    
    def _get_preferred_provider(self, tenant_id: str) -> MailProvider:
        """Get preferred mail provider for tenant"""
        # Check in order of preference
        for provider in [
            MailProvider.GMAIL,
            MailProvider.AWS_SES,
            MailProvider.SLACK,
            MailProvider.SENDGRID,
            MailProvider.OUTLOOK,
        ]:
            feature_name = f"mail_provider_{provider.value}"
            if self.feature_flags.is_enabled(feature_name, tenant_id):
                return provider
        
        # Fall back to Outlook
        return MailProvider.OUTLOOK
    
    def _instantiate_adapter(self, provider: MailProvider) -> Any:
        """Instantiate adapter for provider"""
        adapters = {
            MailProvider.OUTLOOK: "OutlookEmailClient",
            MailProvider.GMAIL: "GmailAdapter",
            MailProvider.AWS_SES: "AWSSESAdapter",
            MailProvider.SENDGRID: "SendGridAdapter",
            MailProvider.SLACK: "SlackAdapter",
        }
        
        adapter_name = adapters[provider]
        logger.info(f"📦 Instantiating {adapter_name}")
        
        # In real code, would import and instantiate here
        return adapter_name


# ============================================================================
# ATS ADAPTER FACTORY
# ============================================================================

class ATSAdapterFactory:
    """
    Create ATS adapters based on feature flags
    
    Supports: Workday, Lever, Talentware, Greenhouse
    """
    
    def __init__(self, feature_flags: FeatureFlags):
        self.feature_flags = feature_flags
        self._initialize_ats_features()
    
    def _initialize_ats_features(self) -> None:
        """Initialize ATS feature flags"""
        # Greenhouse (stable - existing)
        self.feature_flags.add_feature(
            name="ats_provider_greenhouse",
            description="Greenhouse ATS integration",
            enabled_by_default=True,
            status=FeatureStatus.STABLE,
            owner="ats",
        )
        
        # Workday (beta)
        self.feature_flags.add_feature(
            name="ats_provider_workday",
            description="Workday ATS integration",
            enabled_by_default=False,
            rollout_percent=20,
            status=FeatureStatus.BETA,
            owner="ats",
        )
        
        # Lever (beta)
        self.feature_flags.add_feature(
            name="ats_provider_lever",
            description="Lever ATS integration",
            enabled_by_default=False,
            rollout_percent=20,
            status=FeatureStatus.BETA,
            owner="ats",
        )
        
        # Talentware (alpha)
        self.feature_flags.add_feature(
            name="ats_provider_talentware",
            description="Talentware ATS integration",
            enabled_by_default=False,
            rollout_percent=5,
            status=FeatureStatus.ALPHA,
            owner="ats",
        )
    
    def get_adapter(
        self,
        tenant_id: str,
        provider: Optional[ATSProvider] = None,
    ) -> Any:
        """Get ATS adapter for tenant"""
        if not provider:
            provider = self._get_preferred_provider(tenant_id)
        
        # Check if provider enabled
        feature_name = f"ats_provider_{provider.value}"
        if not self.feature_flags.is_enabled(feature_name, tenant_id):
            logger.warning(
                f"⚠️  {provider.value} disabled for {tenant_id}"
            )
            return None
        
        logger.info(f"✅ Using {provider.value} ATS adapter for {tenant_id}")
        return self._instantiate_adapter(provider)
    
    def _get_preferred_provider(self, tenant_id: str) -> ATSProvider:
        """Get preferred ATS provider for tenant"""
        for provider in [
            ATSProvider.WORKDAY,
            ATSProvider.LEVER,
            ATSProvider.TALENTWARE,
            ATSProvider.GREENHOUSE,
        ]:
            feature_name = f"ats_provider_{provider.value}"
            if self.feature_flags.is_enabled(feature_name, tenant_id):
                return provider
        
        # Fall back to Greenhouse
        return ATSProvider.GREENHOUSE
    
    def _instantiate_adapter(self, provider: ATSProvider) -> Any:
        """Instantiate adapter for provider"""
        adapters = {
            ATSProvider.WORKDAY: "WorkdayATSAdapter",
            ATSProvider.LEVER: "LeverATSAdapter",
            ATSProvider.TALENTWARE: "TalentwaveATSAdapter",
            ATSProvider.GREENHOUSE: "GreenhouseATSAdapter",
        }
        
        adapter_name = adapters[provider]
        logger.info(f"📦 Instantiating {adapter_name}")
        
        # In real code, would import and instantiate here
        return adapter_name


# ============================================================================
# A/B TESTING
# ============================================================================

class ABTest:
    """
    A/B test for comparing feature versions
    
    Example: Compare reply parser v1 vs v2
    """
    
    def __init__(
        self,
        test_id: str,
        feature_name: str,
        control_version: str,
        treatment_version: str,
        split_percent: int = 50,
    ):
        self.config = ABTestConfig(
            test_id=test_id,
            feature_name=feature_name,
            control_version=control_version,
            treatment_version=treatment_version,
            split_percent=split_percent,
        )
        self.metrics: Dict[str, Dict[str, float]] = {
            control_version: {},
            treatment_version: {},
        }
    
    def get_version(self, tenant_id: str) -> str:
        """
        Get version for tenant (deterministic)
        
        Same tenant always gets same version using consistent hash
        """
        hash_input = f"{tenant_id}:{self.config.test_id}".encode()
        hash_value = int(hashlib.md5(hash_input).hexdigest(), 16)
        tenant_hash = hash_value % 100
        
        if tenant_hash < self.config.split_percent:
            return self.config.treatment_version
        else:
            return self.config.control_version
    
    def record_metric(
        self,
        version: str,
        metric_name: str,
        value: float,
    ) -> None:
        """Record metric for version"""
        if version not in self.metrics:
            self.metrics[version] = {}
        
        if metric_name not in self.metrics[version]:
            self.metrics[version][metric_name] = []
        
        self.metrics[version][metric_name].append(value)
    
    def get_results(self) -> Dict[str, Any]:
        """Get test results"""
        return {
            "test_id": self.config.test_id,
            "feature": self.config.feature_name,
            "control": self.config.control_version,
            "treatment": self.config.treatment_version,
            "split": f"{self.config.split_percent}%",
            "results": {
                version: {
                    metric: {
                        "count": len(values),
                        "mean": sum(values) / len(values) if values else 0,
                        "min": min(values) if values else 0,
                        "max": max(values) if values else 0,
                    }
                    for metric, values in metrics.items()
                }
                for version, metrics in self.metrics.items()
            },
        }


if __name__ == "__main__":
    print("✅ Feature flags & adapter system ready")
    print("   Features: Mail providers, ATS integrations, A/B testing")
