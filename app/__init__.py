"""应用工厂。

把「配置读取 / 日志 / 数据库 / 指标 / 中间件 / 错误处理」集中在一个地方，
好处是测试可以用 create_app({"TESTING": True}) 拿到干净实例，
而不必依赖模块级全局状态。
"""

import os
import tempfile
import time
import uuid
from typing import Optional

from flask import Flask, g, jsonify, request
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.exceptions import HTTPException

from . import metrics as m
from .db import build_engine_options, init_db
from .logging_conf import setup_logging
from .routes import api
from .tasks import init_task_gauge, tasks

# 这些端点的日志会被探针和 Prometheus 高频调用，只计指标不写日志，否则日志会被刷爆
LOG_EXCLUDED_ENDPOINTS = {
    "api.metrics",
    "api.healthz",
    "api.readyz",
}


def _default_sqlite_path() -> str:
    """跨平台的 SQLite 默认路径。

    tempfile.gettempdir() 在 Linux 返回 /tmp、在 Windows 返回 %TEMP%。
    统一把反斜杠换成斜杠，SQLAlchemy 的连接串才能正确解析：
      Linux   -> sqlite:////tmp/ops-demo.db
      Windows -> sqlite:///C:/Users/xxx/AppData/Local/Temp/ops-demo.db
    """
    return os.path.join(tempfile.gettempdir(), "ops-demo.db").replace("\\", "/")


def create_app(overrides: Optional[dict] = None) -> Flask:
    app = Flask(__name__)

    # ---------- 配置：全部来自环境变量，符合 12-Factor ----------
    app.config.update(
        APP_VERSION=os.getenv("APP_VERSION", "dev"),
        GIT_COMMIT=os.getenv("GIT_COMMIT", "unknown"),
        ENV_NAME=os.getenv("ENV_NAME", "local"),
        # 默认 SQLite，开箱即用；线上用 MySQL 只需换这一个变量。
        # 用系统临时目录而不是写死 /tmp：Windows 上没有 /tmp，
        # 会导致建表失败、就绪检查一直返回 503。
        DATABASE_URL=os.getenv(
            "DATABASE_URL", "sqlite:///" + _default_sqlite_path()
        ),
        AUTO_CREATE_TABLES=os.getenv("AUTO_CREATE_TABLES", "true").lower() == "true",
        # readiness 是否检查数据库。默认开启，生产环境建议保持开启见 README「设计权衡」
        READYZ_CHECK_DB=os.getenv("READYZ_CHECK_DB", "true").lower() == "true",
        ERROR_RATE=float(os.getenv("ERROR_RATE", "0.0")),
        STARTUP_DELAY_SECONDS=float(os.getenv("STARTUP_DELAY_SECONDS", "0")),
        MAX_SLOW_MS=int(os.getenv("MAX_SLOW_MS", "10000")),
        MAX_CPU_MS=int(os.getenv("MAX_CPU_MS", "5000")),
        LOG_LEVEL=os.getenv("LOG_LEVEL", "INFO"),
        JSON_LOGS=os.getenv("JSON_LOGS", "true").lower() == "true",
    )
    if overrides:
        app.config.update(overrides)

    # ---------- SQLAlchemy 需要单独的配置键，这里做一次映射 ----------
    uri = app.config["DATABASE_URL"]
    app.config["SQLALCHEMY_DATABASE_URI"] = uri
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = build_engine_options(uri)

    setup_logging(app)
    init_db(app)
    init_task_gauge()

    m.APP_INFO.info(
        {
            "version": app.config["APP_VERSION"],
            "commit": app.config["GIT_COMMIT"],
            "env": app.config["ENV_NAME"],
        }
    )

    app.register_blueprint(api)
    app.register_blueprint(tasks)
    _register_middleware(app)
    _register_error_handlers(app)

    return app


def _register_middleware(app: Flask) -> None:
    @app.before_request
    def _begin():
        g.start = time.perf_counter()
        g.request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:16]

    @app.after_request
    def _record(response):
        endpoint = request.endpoint or "unmatched"

        # 不统计 /metrics 自身，否则抓取频率会污染 QPS 曲线
        if endpoint == "api.metrics":
            return response

        duration = time.perf_counter() - getattr(g, "start", time.perf_counter())

        m.REQUEST_COUNT.labels(request.method, endpoint, response.status_code).inc()
        m.REQUEST_LATENCY.labels(request.method, endpoint).observe(duration)

        response.headers["X-Request-ID"] = g.get("request_id", "")

        if endpoint not in LOG_EXCLUDED_ENDPOINTS:
            app.logger.info(
                "http_request",
                extra={
                    "request_id": g.get("request_id", ""),
                    "path": request.path,
                    "method": request.method,
                    "status": response.status_code,
                    "duration_ms": round(duration * 1000, 2),
                },
            )
        return response


def _register_error_handlers(app: Flask) -> None:
    @app.errorhandler(HTTPException)
    def _http_error(err: HTTPException):
        """把 Flask 默认的 HTML 错误页换成 JSON，便于前端和告警系统解析。"""
        return (
            jsonify(
                status=err.code,
                error=err.name,
                message=err.description,
                path=request.path,
            ),
            err.code,
        )

    @app.errorhandler(SQLAlchemyError)
    def _db_error(err: SQLAlchemyError):
        """数据库异常统一返回 503 而不是 500。

        区别很重要：
          500 = 代码 bug，需要人改代码；
          503 = 依赖不可用，等它恢复就行，编排层也不应该重启实例。
        告警规则也应该按这两个语义分别配置。
        """
        db.session.rollback()
        app.logger.exception("database_error")
        return (
            jsonify(
                status=503,
                error="Service Unavailable",
                message="数据库暂不可用，请稍后重试",
                path=request.path,
            ),
            503,
        )

    @app.errorhandler(Exception)
    def _unhandled(err: Exception):
        app.logger.exception("unhandled_exception")
        return jsonify(status=500, error="Internal Server Error", message="服务内部错误"), 500
