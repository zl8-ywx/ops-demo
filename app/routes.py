"""业务接口 + 运维接口。

业务接口只有 hello 与 /api/tasks（在 tasks.py）；
这里其余三个是「故障注入接口」，
它们的存在是为了让监控大盘和告警规则有东西可抓、可演示。
"""

import random
import time

from flask import Blueprint, Response, abort, current_app, jsonify, request
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from .db import db

api = Blueprint("api", __name__)

# 进程启动时刻，用于模拟「启动预热」阶段的就绪探针失败
START_TS = time.time()


# --------------------------------------------------------------------------
# 业务接口
# --------------------------------------------------------------------------
@api.get("/api/hello")
def hello():
    name = request.args.get("name", "world")
    return jsonify(
        message="hello, {}".format(name),
        version=current_app.config["APP_VERSION"],
        env=current_app.config["ENV_NAME"],
    )


# --------------------------------------------------------------------------
# 故障注入接口：用于验证监控与告警
# --------------------------------------------------------------------------
@api.get("/api/error")
def inject_error():
    """按概率返回 500，用于制造错误率。

    /api/error?rate=1    -> 必失败
    /api/error?rate=0.3  -> 30% 失败
    """
    raw = request.args.get("rate", str(current_app.config["ERROR_RATE"]))
    try:
        rate = float(raw)
    except ValueError:
        abort(400, description="rate 必须是 0~1 之间的浮点数")
    if not 0.0 <= rate <= 1.0:
        abort(400, description="rate 必须是 0~1 之间的浮点数")

    if random.random() < rate:
        abort(500, description="模拟业务异常（故障注入）")

    return jsonify(ok=True, rate=rate)


@api.get("/api/slow")
def inject_slow():
    """睡眠指定毫秒，用于制造 P95/P99 延迟毛刺。"""
    limit = current_app.config["MAX_SLOW_MS"]
    raw = request.args.get("ms", "1000")
    try:
        ms = int(raw)
    except ValueError:
        abort(400, description="ms 必须是整数")
    if ms < 0:
        abort(400, description="ms 不能为负数")

    ms = min(ms, limit)
    time.sleep(ms / 1000.0)
    return jsonify(slept_ms=ms)


@api.get("/api/cpu")
def inject_cpu():
    """忙等指定毫秒，用于把 CPU 打上去，触发 HPA 扩容。"""
    limit = current_app.config["MAX_CPU_MS"]
    raw = request.args.get("ms", "500")
    try:
        ms = int(raw)
    except ValueError:
        abort(400, description="ms 必须是整数")
    if ms < 0:
        abort(400, description="ms 不能为负数")

    ms = min(ms, limit)
    deadline = time.perf_counter() + ms / 1000.0
    loops = 0
    while time.perf_counter() < deadline:
        loops += 1

    return jsonify(busy_ms=ms, loops=loops)


# --------------------------------------------------------------------------
# 运维接口
# --------------------------------------------------------------------------
@api.get("/healthz")
def healthz():
    """存活检查：只要进程还能处理请求，就算活着。

    这里刻意不检查数据库。原因见 README「为什么存活检查不查数据库」：
    数据库抖动时如果这里失败，会导致全部实例被同时重启，
    把一个「可恢复的依赖故障」放大成「雪崩」。
    """
    return jsonify(status="ok")


@api.get("/readyz")
def readyz():
    """就绪探针：启动预热期与依赖不可用时返回 503，让 Service 暂时不转发流量。"""
    elapsed = time.time() - START_TS
    delay = current_app.config["STARTUP_DELAY_SECONDS"]
    if elapsed < delay:
        return jsonify(status="starting", elapsed=round(elapsed, 2)), 503

    if current_app.config["READYZ_CHECK_DB"]:
        try:
            db.session.execute(text("SELECT 1"))
        except SQLAlchemyError:
            current_app.logger.warning("readiness_db_check_failed")
            return jsonify(status="db_unavailable", elapsed=round(elapsed, 2)), 503

    return jsonify(status="ready", elapsed=round(elapsed, 2))


@api.get("/metrics")
def metrics():
    """Prometheus 抓取端点。"""
    return Response(generate_latest(), mimetype=CONTENT_TYPE_LATEST)
