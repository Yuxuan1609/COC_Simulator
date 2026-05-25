"""PipelineMonitor tests — LLMSensor + AgentMonitor + PipelineHealth."""
from monitor.sensor import LLMSensor, LLMCallRecord, AgentStats


def test_sensor_record_and_retrieval():
    s = LLMSensor(enabled=True, history_size=5, slow_threshold_ms=1000)
    s.record(label="Keeper Parse", model="deepseek-v4-pro", duration_ms=500, ok=True,
             json_mode=True, json_valid=True, response_len=100, http_status=200)
    s.record(label="Keeper Enrich", model="deepseek-v4-pro", duration_ms=3000, ok=True,
             json_mode=True, json_valid=True, response_len=200, http_status=200)
    s.record(label="Narrator", model="deepseek-v4-pro", duration_ms=200, ok=False,
             json_mode=True, json_valid=False, response_len=0, http_status=500)

    assert len(s.history) == 3
    assert len(s.get_records("Keeper")) == 2
    assert len(s.get_records("Narrator")) == 1
    assert s.consecutive_failures == 1


def test_sensor_disabled_zero_overhead():
    s = LLMSensor(enabled=False)
    s.record(label="test", duration_ms=100)
    assert len(s.history) == 0


def test_sensor_ring_buffer():
    s = LLMSensor(enabled=True, history_size=3)
    for i in range(5):
        s.record(label=f"call_{i}", duration_ms=100, ok=True)
    assert len(s.history) == 3


def test_agent_stats():
    s = LLMSensor(enabled=True, slow_threshold_ms=1000)
    for _ in range(5):
        s.record(label="Keeper Parse", duration_ms=500, ok=True, json_mode=True,
                 json_valid=True, response_len=100, http_status=200)
    for _ in range(3):
        s.record(label="Keeper Parse", duration_ms=2000, ok=True, json_mode=True,
                 json_valid=True, response_len=100, http_status=200)
    for _ in range(2):
        s.record(label="Keeper Parse", duration_ms=100, ok=False, json_mode=True,
                 json_valid=False, response_len=0, http_status=500)

    stats = s.get_stats("Keeper")
    assert stats.total_calls == 10
    assert stats.total_failures == 2
    assert stats.total_slow_calls == 3


def test_consecutive_failures():
    s = LLMSensor(enabled=True)
    s.record(label="test", duration_ms=100, ok=True)
    s.record(label="test", duration_ms=100, ok=False)
    s.record(label="test", duration_ms=100, ok=False)
    assert s.consecutive_failures == 2
    s.record(label="test", duration_ms=100, ok=True)
    assert s.consecutive_failures == 0


def test_recent_slow_rate():
    s = LLMSensor(enabled=True, slow_threshold_ms=1000)
    for _ in range(6):
        s.record(label="test", duration_ms=500, ok=True)
    for _ in range(4):
        s.record(label="test", duration_ms=2000, ok=True)
    assert s.recent_slow_rate == 0.4


def test_degrade_policies_load_from_config():
    from monitor.policies import KeeperPolicy, NarratorPolicy, AuthorPolicy
    kp = KeeperPolicy()
    assert kp.on_degrade()["skip_enrich"] is True
    np = NarratorPolicy()
    assert np.on_degrade()["thinking"] is False
    ap = AuthorPolicy()
    assert ap.on_degrade()["reject_all_structural"] is True


def test_pipeline_health_snapshot():
    from monitor.health import PipelineHealth
    s = LLMSensor(enabled=True)
    s.record(label="Keeper Parse", duration_ms=100, ok=True, json_mode=True,
             json_valid=True, response_len=50, http_status=200, model="deepseek-v4-pro")
    s.record(label="Narrator", duration_ms=200, ok=True, json_mode=True,
             json_valid=True, response_len=80, http_status=200, model="deepseek-v4-pro")

    health = PipelineHealth(s)
    snap = health.snapshot()
    assert snap["total_calls"] == 2
    assert snap["total_failures"] == 0
    assert "Keeper" in snap["agents"]
    assert "Narrator" in snap["agents"]
