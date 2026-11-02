"""基础接口与运维接口的功能测试。

可直接作为论文第 6 章「功能测试用例表」的素材，
每条用例对应一个验证点，答辩时能说清「我测了什么、怎么判定的」。
"""


def test_hello_returns_version(client):
    """正常业务接口应返回版本号，用于演示版本变更"""
    resp = client.get("/api/hello?name=ops")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["message"] == "hello, ops"
    assert body["version"] == "test-1.0.0"
    assert body["env"] == "test"


def test_error_injection_disabled(client):
    """rate=0 时不应产生错误"""
    for _ in range(30):
        assert client.get("/api/error?rate=0").status_code == 200


def test_error_injection_enabled(client):
    """rate=1 时必须全部失败，且返回结构化 JSON"""
    resp = client.get("/api/error?rate=1")
    assert resp.status_code == 500
    body = resp.get_json()
    assert body["status"] == 500
    assert body["path"] == "/api/error"


def test_error_injection_rejects_bad_rate(client):
    """非法参数应返回 400，而不是 500"""
    assert client.get("/api/error?rate=abc").status_code == 400
    assert client.get("/api/error?rate=1.5").status_code == 400


def test_slow_respects_upper_bound(client):
    """ms 超过上限时应被截断，避免把应用自己拖死"""
    resp = client.get("/api/slow?ms=999999")
    assert resp.status_code == 200
    assert resp.get_json()["slept_ms"] <= 10000


def test_cpu_rejects_negative(client):
    assert client.get("/api/cpu?ms=-1").status_code == 400


def test_healthz_always_ok(client):
    assert client.get("/healthz").status_code == 200


def test_readyz_ok_after_startup(client):
    """就绪探针在预热期结束后应返回 200"""
    assert client.get("/readyz").status_code == 200
    assert client.get("/readyz").get_json()["status"] == "ready"


def test_request_id_header(client):
    """未携带 X-Request-ID 时应自动生成，便于日志串联"""
    resp = client.get("/api/hello")
    assert resp.headers.get("X-Request-ID")

    resp2 = client.get("/api/hello", headers={"X-Request-ID": "abc123"})
    assert resp2.headers.get("X-Request-ID") == "abc123"


def test_metrics_exposed(client):
    """指标端点必须包含自定义指标，且 Prometheus 文本格式可解析"""
    client.get("/api/hello")
    resp = client.get("/metrics")
    assert resp.status_code == 200
    text = resp.data.decode("utf-8")
    assert "http_requests_total" in text
    assert "http_request_duration_seconds_bucket" in text
    assert "app_info" in text
    assert 'version="test-1.0.0"' in text


def test_unknown_path_returns_json_404(client):
    """404 也必须是 JSON，否则前端和告警解析会失败"""
    resp = client.get("/not-exist")
    assert resp.status_code == 404
    assert resp.get_json()["status"] == 404
