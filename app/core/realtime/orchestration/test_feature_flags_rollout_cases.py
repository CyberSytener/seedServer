from app.core.realtime.orchestration.feature_flags import FeatureFlags


def test_get_feature_status_unknown_returns_none():
    flags = FeatureFlags()
    assert flags.get_feature_status("no_such_feature") is None


def test_rollout_hashing_variety():
    flags = FeatureFlags()
    flags.set_rollout_percent("mail_provider_gmail", 30)

    results = set(flags.is_enabled("mail_provider_gmail", f"tenant_{i}") for i in range(20))
    # Expect both True and False across many tenants at 30% rollout
    assert True in results and False in results

