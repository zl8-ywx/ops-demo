"""运维工单接口的 CRUD 测试。

覆盖：正常增删改查、参数校验、分页、状态过滤、404、业务指标联动。
"""


def _create(client, title="巡检 node1", status=None):
    payload = {"title": title}
    if status:
        payload["status"] = status
    resp = client.post("/api/tasks", json=payload)
    assert resp.status_code == 201, resp.data
    return resp.get_json()


def test_create_and_get(client):
    task = _create(client, "重启 node1 上的 nginx")
    assert task["id"] > 0
    assert task["status"] == "pending"
    assert task["created_at"].endswith("Z")

    got = client.get("/api/tasks/{}".format(task["id"]))
    assert got.status_code == 200
    assert got.get_json()["title"] == "重启 node1 上的 nginx"


def test_create_rejects_empty_title(client):
    assert client.post("/api/tasks", json={"title": "   "}).status_code == 400
    assert client.post("/api/tasks", json={}).status_code == 400


def test_create_rejects_invalid_status(client):
    resp = client.post("/api/tasks", json={"title": "x", "status": "unknown"})
    assert resp.status_code == 400


def test_create_rejects_non_json_body(client):
    resp = client.post("/api/tasks", data="not-json", content_type="text/plain")
    assert resp.status_code == 400


def test_list_pagination(client):
    for i in range(25):
        _create(client, "任务-{:02d}".format(i))

    resp = client.get("/api/tasks?page=1&size=10")
    body = resp.get_json()
    assert body["total"] == 25
    assert body["pages"] == 3
    assert len(body["items"]) == 10
    # 按 id 倒序，第一页第一条应是最后创建的那条
    assert body["items"][0]["title"] == "任务-24"

    resp2 = client.get("/api/tasks?page=3&size=10")
    assert len(resp2.get_json()["items"]) == 5


def test_list_size_is_capped(client):
    """size 超过 100 时应被截断，防止一次拉全表"""
    _create(client)
    body = client.get("/api/tasks?size=99999").get_json()
    assert body["size"] == 100


def test_list_filter_by_status(client):
    _create(client, "a", status="pending")
    _create(client, "b", status="done")
    _create(client, "c", status="done")

    body = client.get("/api/tasks?status=done").get_json()
    assert body["total"] == 2

    assert client.get("/api/tasks?status=bad").status_code == 400


def test_update_status(client):
    task = _create(client)
    resp = client.patch(
        "/api/tasks/{}".format(task["id"]), json={"status": "running"}
    )
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "running"

    assert (
        client.patch(
            "/api/tasks/{}".format(task["id"]), json={"status": "bad"}
        ).status_code
        == 400
    )


def test_delete(client):
    task = _create(client)
    assert client.delete("/api/tasks/{}".format(task["id"])).status_code == 204
    assert client.get("/api/tasks/{}".format(task["id"])).status_code == 404


def test_not_found(client):
    assert client.get("/api/tasks/999999").status_code == 404
    assert client.patch("/api/tasks/999999", json={"status": "done"}).status_code == 404
    assert client.delete("/api/tasks/999999").status_code == 404


def test_stats(client):
    _create(client, "a", status="pending")
    _create(client, "b", status="done")
    _create(client, "c", status="done")

    body = client.get("/api/tasks/stats").get_json()
    assert body["pending"] == 1
    assert body["done"] == 2
    assert body["failed"] == 0
    assert body["running"] == 0


def test_business_metric_reflects_status(client):
    """业务指标必须和数据库真实状态一致，否则大盘会出现假数据"""
    _create(client, "a", status="failed")

    text = client.get("/metrics").data.decode("utf-8")
    assert 'tasks{status="failed"} 1.0' in text
