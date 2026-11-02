"""运维工单接口。

单独一个 Blueprint，路由用完整路径而不是 url_prefix，
原因是 url_prefix 拼接空字符串会得到 "/api/tasks/"，导致 /api/tasks 触发 308 跳转，
对 curl 和监控探针都不友好。
"""

from flask import Blueprint, abort, jsonify, request
from sqlalchemy import func

from . import metrics as m
from .db import db
from .models import ALLOWED_STATUS, Task

tasks = Blueprint("tasks", __name__)

MAX_TITLE_LEN = 128
MAX_DESC_LEN = 2000


# --------------------------------------------------------------------------
# 内部工具
# --------------------------------------------------------------------------
def _json_body() -> dict:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        abort(400, description="请求体必须是 JSON 对象，且 Content-Type 为 application/json")
    return data


def _clean_title(value) -> str:
    title = (value or "").strip()
    if not title:
        abort(400, description="title 不能为空")
    if len(title) > MAX_TITLE_LEN:
        abort(400, description="title 长度不能超过 {}".format(MAX_TITLE_LEN))
    return title


def _check_status(value) -> str:
    if value not in ALLOWED_STATUS:
        abort(400, description="status 必须是 {} 之一".format(" / ".join(ALLOWED_STATUS)))
    return value


def _refresh_task_gauge() -> None:
    """把各状态的任务数量同步到 Prometheus Gauge。

    这样 Grafana 的业务大盘可以直接查 tasks{status="failed"}，
    不需要额外接一个直连数据库的数据源。
    """
    rows = db.session.query(Task.status, func.count(Task.id)).group_by(Task.status).all()
    counts = {status: count for status, count in rows}
    for status in ALLOWED_STATUS:
        m.TASK_GAUGE.labels(status).set(counts.get(status, 0))


def init_task_gauge() -> None:
    """启动时先把所有状态标签注册为 0。

    带标签的 Gauge 只有在 .labels() 被调用后才会产生样本。
    如果不做这一步，在创建第一张工单之前，Grafana 面板会显示 "No data"，
    演示时很容易被误认为监控没配好。
    """
    for status in ALLOWED_STATUS:
        m.TASK_GAUGE.labels(status).set(0)


def _get_or_404(task_id: int) -> Task:
    task = db.session.get(Task, task_id)
    if task is None:
        abort(404, description="任务不存在：id={}".format(task_id))
    return task


# --------------------------------------------------------------------------
# 接口
# --------------------------------------------------------------------------
@tasks.get("/api/tasks")
def list_tasks():
    """分页查询，支持按状态过滤。

    page 从 1 开始，size 上限 100，防止有人传 size=100000 把内存打满。
    """
    try:
        page = max(int(request.args.get("page", 1)), 1)
        size = int(request.args.get("size", 20))
    except ValueError:
        abort(400, description="page / size 必须是整数")
    size = min(max(size, 1), 100)

    query = Task.query
    status = request.args.get("status")
    if status:
        query = query.filter_by(status=_check_status(status))

    pagination = query.order_by(Task.id.desc()).paginate(
        page=page, per_page=size, error_out=False
    )
    return jsonify(
        items=[task.to_dict() for task in pagination.items],
        total=pagination.total,
        page=page,
        size=size,
        pages=pagination.pages,
    )


@tasks.post("/api/tasks")
def create_task():
    data = _json_body()
    task = Task(
        title=_clean_title(data.get("title")),
        description=(data.get("description") or "")[:MAX_DESC_LEN],
        status=_check_status(data.get("status", "pending")),
    )
    db.session.add(task)
    db.session.commit()
    _refresh_task_gauge()
    return jsonify(task.to_dict()), 201


@tasks.get("/api/tasks/stats")
def task_stats():
    """各状态任务数量，供业务大盘和答辩演示使用。"""
    rows = db.session.query(Task.status, func.count(Task.id)).group_by(Task.status).all()
    counts = {status: 0 for status in ALLOWED_STATUS}
    for status, count in rows:
        counts[status] = count
    return jsonify(counts)


@tasks.get("/api/tasks/<int:task_id>")
def get_task(task_id: int):
    return jsonify(_get_or_404(task_id).to_dict())


@tasks.patch("/api/tasks/<int:task_id>")
def update_task(task_id: int):
    task = _get_or_404(task_id)
    data = _json_body()

    if "title" in data:
        task.title = _clean_title(data["title"])
    if "description" in data:
        task.description = (data["description"] or "")[:MAX_DESC_LEN]
    if "status" in data:
        task.status = _check_status(data["status"])

    db.session.commit()
    _refresh_task_gauge()
    return jsonify(task.to_dict())


@tasks.delete("/api/tasks/<int:task_id>")
def delete_task(task_id: int):
    db.session.delete(_get_or_404(task_id))
    db.session.commit()
    _refresh_task_gauge()
    return "", 204
