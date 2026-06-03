from app.core.realtime.orchestration.feature_flags import FeatureFlags, MailProvider


def test_rollout_deterministic_and_bounds():
    flags = FeatureFlags()

    # Set rollout to 50% and check consistency for same tenant
    flags.set_rollout_percent("mail_provider_gmail", 50)
    a = flags.is_enabled("mail_provider_gmail", "tenant_alpha")
    b = flags.is_enabled("mail_provider_gmail", "tenant_alpha")
    assert a == b

    # Out-of-bounds values should be clamped
    flags.set_rollout_percent("mail_provider_gmail", 200)
    assert flags.features["mail_provider_gmail"].rollout_percent == 100

    flags.set_rollout_percent("mail_provider_gmail", -50)
    assert flags.features["mail_provider_gmail"].rollout_percent == 0


def test_adapter_factory_falls_back_when_provider_disabled():
    flags = FeatureFlags()
    # Ensure Gmail is disabled
    flags.set_rollout_percent("mail_provider_gmail", 0)

    factory = __import__("app.core.realtime.orchestration.feature_flags", fromlist=["MailAdapterFactory"]).MailAdapterFactory(flags)
    adapter = factory.get_adapter("tenant_x", provider=MailProvider.GMAIL)
    # With Gmail disabled, factory should fall back to Outlook
    assert adapter == "OutlookEmailClient"

