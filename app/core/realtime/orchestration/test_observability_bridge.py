from app.core.realtime import observability as obs


def test_observability_bridge_singleton_and_spans():
    mgr = obs.get_obs_manager("bridge-svc")
    # Should be initialized as singleton
    assert obs.get_obs_manager() is mgr

    # Use dummy span (no opentelemetry installed)
    with mgr.span("bridge.test") as s:
        s.set_attribute("k", "v")

    # Async dummy span
    async def _run():
        async with mgr.async_span("bridge.async") as s2:
            s2.set_attribute("a", 1)
    import asyncio
    asyncio.run(_run())
