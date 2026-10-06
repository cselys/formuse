#!/usr/bin/env python
import sys

with open(r'C:\Git\AI\Claude\SectorRadar\tests\test_finnhub_provider.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. test_schedule_215_symbols - update docstring and assertion
old1 = '''def test_schedule_215_symbols(fake_now):
    """215 symbols at 60/min @ 0.8 -> delay=1.395s, 5 batches, ~300 s cycle."""
    from data.collector import CollectionConfig, build_universe, derive_schedule
    from utils.config import load_settings, load_themes

    settings = load_settings()["data"]
    coll = settings.get("data", {})
    cfg = CollectionConfig(**coll)
    themes = load_themes()
    universe = build_universe(cfg, themes)
    assert len(universe) == 215, f"expected 215, got {len(universe)}"'''

new1 = '''def test_schedule_214_symbols(fake_now):
    """214 symbols at 60/min @ 0.8 -> delay=1.402s, 5 batches, ~300 s cycle."""
    from data.collector import CollectionConfig, build_universe, derive_schedule
    from utils.config import load_settings, load_themes

    settings = load_settings()["data"]
    coll = settings.get("data", {})
    cfg = CollectionConfig(**coll)
    themes = load_themes()
    universe = build_universe(cfg, themes)
    assert len(universe) == 214, f"expected 214, got {len(universe)}'''

content = content.replace(old1, new1)

# 2. test_collector_respects_inter_request_delay - update assertion
old2 = '''def test_collector_respects_inter_request_delay(tmpdb):
    """A full 215-symbol cycle sleeps the derived delay before each request;
    it never bursts all requests in ~0 seconds."""
    from data.collector import CollectionConfig, build_universe, derive_schedule
    from utils.config import load_settings, load_themes

    settings = load_settings()["data"]
    coll = settings.get("data", {})
    cfg = CollectionConfig(**coll)
    themes = load_themes()
    universe = build_universe(cfg, themes)
    schedule = derive_schedule(len(universe), cfg)
    expected_delay = schedule.inter_request_delay
    assert math.isclose(expected_delay, 300.0 / 215.0, rel_tol=1e-9)'''

new2 = '''def test_collector_respects_inter_request_delay(tmpdb):
    """A full 214-symbol cycle sleeps the derived delay before each request;
    it never bursts all requests in ~0 seconds."""
    from data.collector import CollectionConfig, build_universe, derive_schedule
    from utils.config import load_settings, load_themes

    settings = load_settings()["data"]
    coll = settings.get("data", {})
    cfg = CollectionConfig(**coll)
    themes = load_themes()
    universe = build_universe(cfg, themes)
    schedule = derive_schedule(len(universe), cfg)
    expected_delay = schedule.inter_request_delay
    assert math.isclose(expected_delay, 300.0 / 214.0, rel_tol=1e-9)'''

content = content.replace(old2, new2)

# 3. test_collector_215_regression_no_burst_or_spin - update all 215 references
old3 = '''def test_collector_215_regression_no_burst_or_spin(tmpdb):
    """Regression for the live burst (215 requests in 12 s, 155x 429):
    a 215-symbol cycle at 60/min must not burst, must not spin on 429,
    and must complete the full cycle."""
    from data.collector import CollectionConfig, build_universe, derive_schedule, _RateLimitState
    from utils.config import load_settings, load_themes

    settings = load_settings()
    coll = settings["data"].get("collection", {})
    cfg = CollectionConfig(**coll)
    themes = load_themes()
    universe = build_universe(cfg, themes)
    schedule = derive_schedule(len(universe), cfg)
    expected_delay = schedule.inter_request_delay

    client = FakeFinnhubClient()
    ts = datetime(2026, 10, 5, 14, 0, 0, tzinfo=timezone.utc).timestamp()
    for sym in universe:
        client.set_quotes({sym: {"c": 100.0 + hash(sym) % 100, "pc": 100.0,
                                 "o": 100.5, "h": 102.0, "l": 99.5, "t": ts}})
    # Force a 429 on the first request (like Finnhub did in the live burst).
    client.rate_limit()

    os.environ["FINNHUB_API_KEY"] = "dummy"  # real config expects FINNHUB_API_KEY
    collector = FinnhubCollector(settings)
    collector.provider._transport = client
    collector.store = SnapshotStore(tmpdb)

    with mock.patch("data.collector.time.sleep") as mock_sleep, \
            mock.patch.object(_RateLimitState, "wait_after_429", return_value=0.0):
        summary = collector.run_cycle(universe)

    # The cycle completes: the first symbol is suppressed, the rest succeed.
    assert summary.n_symbols == 215
    assert summary.n_succeeded == 214
    assert summary.n_failed == 0
    assert summary.n_rate_limited == 1'''

new3 = '''def test_collector_214_regression_no_burst_or_spin(tmpdb):
    """Regression for the live burst (214 requests in ~12 s, ~155x 429):
    a 214-symbol cycle at 60/min must not burst, must not spin on 429,
    and must complete the full cycle."""
    from data.collector import CollectionConfig, build_universe, derive_schedule, _RateLimitState
    from utils.config import load_settings, load_themes

    settings = load_settings()
    coll = settings["data"].get("collection", {})
    cfg = CollectionConfig(**coll)
    themes = load_themes()
    universe = build_universe(cfg, themes)
    schedule = derive_schedule(len(universe), cfg)
    expected_delay = schedule.inter_request_delay

    client = FakeFinnhubClient()
    ts = datetime(2026, 10, 5, 14, 0, 0, tzinfo=timezone.utc).timestamp()
    for sym in universe:
        client.set_quotes({sym: {"c": 100.0 + hash(sym) % 100, "pc": 100.0,
                                 "o": 100.5, "h": 102.0, "l": 99.5, "t": ts}})
    # Force a 429 on the first request (like Finnhub did in the live burst).
    client.rate_limit()

    os.environ["FINNHUB_API_KEY"] = "dummy"  # real config expects FINNHUB_API_KEY
    collector = FinnhubCollector(settings)
    collector.provider._transport = client
    collector.store = SnapshotStore(tmpdb)

    with mock.patch("data.collector.time.sleep") as mock_sleep, \
            mock.patch.object(_RateLimitState, "wait_after_429", return_value=0.0):
        summary = collector.run_cycle(universe)

    # The cycle completes: the first symbol is suppressed, the rest succeed.
    assert summary.n_symbols == 214
    assert summary.n_succeeded == 213
    assert summary.n_failed == 0
    assert summary.n_rate_limited == 1'''

content = content.replace(old3, new3)

# Also update the sleep-related assertions
old4 = '''# The cycle completes: the first symbol is suppressed, the rest succeed.
    assert summary.n_symbols == 214
    assert summary.n_succeeded == 213
    assert summary.n_failed == 0
    assert summary.n_rate_limited == 1
    # 215 symbols + (batches - 1) pauses for sleep mock calls.
    assert len(sleep_args) == 215 + schedule.batches - 1,
    # Each symbol should sleep at least once.
    assert all(s >= 0 for s in sleep_args)
    # Check that we never burst: the first symbol's sleep should be
    # at least the inter-request delay.
    first_sleep = sleep_args[0]
    assert first_sleep >= schedule.inter_request_delay'''

new4 = '''# The cycle completes: the first symbol is suppressed, the rest succeed.
    assert summary.n_symbols == 214
    assert summary.n_succeeded == 213
    assert summary.n_failed == 0
    assert summary.n_rate_limited == 1
    # 214 symbols + (batches - 1) pauses for sleep mock calls.
    assert len(sleep_args) == 214 + schedule.batches - 1,
    # Each symbol should sleep at least once.
    assert all(s >= 0 for s in sleep_args)
    # Check that we never burst: the first symbol's sleep should be
    # at least the inter-request delay.
    first_sleep = sleep_args[0]
    assert first_sleep >= schedule.inter_request_delay'''

content = content.replace(old4, new4)

with open(r'C:\Git\AI\Claude\SectorRadar\tests\test_finnhub_provider.py', 'w', encoding='utf-8') as f:
    f.write(content)

print('Test file updated successfully')
PYEOF