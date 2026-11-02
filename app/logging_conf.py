"""结构化日志。

统一输出 JSON 到 stdout，理由：
  1. 容器环境下 stdout 就是日志采集入口，不需要写文件、不需要 logrotate；
  2. JSON 便于后续接 Loki / ELK 做字段检索，而不是拿 grep 硬怼；
  3. 请求日志带 request_id，可以串起一次调用链。
"""

import json
import logging
import sys


class JsonFormatter(logging.Formatter):
    """把 LogRecord 序列化成单行 JSON。"""

    EXTRA_FIELDS = ("request_id", "path", "method", "status", "duration_ms")

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "time": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for field in self.EXTRA_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=False)


def setup_logging(app) -> None:
    """按配置初始化根 logger。幂等：重复调用不会叠加 handler。"""
    level = getattr(logging, str(app.config["LOG_LEVEL"]).upper(), logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    if app.config["JSON_LOGS"]:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
        )

    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(level)

    app.logger.setLevel(level)
    # 不让 Flask 再挂一个默认 handler，避免每条日志打两遍
    app.logger.propagate = True

    # 关掉 werkzeug 自带的访问日志：
    # 它格式不是 JSON，且和中间件里的 http_request 日志重复，
    # 混在一起会让日志检索变得不可用
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
