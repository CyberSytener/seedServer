from app.core.realtime.orchestration.feature_flags import FeatureFlags, MailAdapterFactory, MailProvider


def test_feature_defaults_and_overrides():
    flags = FeatureFlags()

    # Default Outlook provider is enabled by default
    assert flags.is_enabled("mail_provider_outlook", "tenant1") is True

    # Gmail not enabled by default; set rollout to 100% and confirm deterministic enable
    flags.set_rollout_percent("mail_provider_gmail", 100)
    assert flags.is_enabled("mail_provider_gmail", "tenant1") is True

    # Explicit enable/disable overrides
    flags.disable_for_tenant("mail_provider_outlook", "tenant_a")
    assert flags.is_enabled("mail_provider_outlook", "tenant_a") is False

    flags.enable_for_tenant("mail_provider_gmail", "tenant_b")
    assert flags.is_enabled("mail_provider_gmail", "tenant_b") is True


def test_get_feature_status_and_all_features():
    flags = FeatureFlags()
    status = flags.get_feature_status("advanced_reply_parser")
    assert status is not None
    assert status["name"] == "advanced_reply_parser"

    all_feats = flags.get_all_features()
    assert isinstance(all_feats, list)


def test_mail_adapter_factory_prefers_enabled_provider():
    flags = FeatureFlags()
    # By default only Outlook and advanced features are enabled; ensure factory returns Outlook adapter
    factory = MailAdapterFactory(flags)
    adapter = factory.get_adapter("tenant_x", provider=MailProvider.OUTLOOK)
    assert adapter == "OutlookEmailClient"

    # Enable Gmail and verify factory chooses Gmail when requested
    flags.set_rollout_percent("mail_provider_gmail", 100)
    adapter2 = factory.get_adapter("tenant_x", provider=MailProvider.GMAIL)
    assert adapter2 == "GmailAdapter"
