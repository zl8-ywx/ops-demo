"""Prometheus 指标定义。

指标命名遵循 Prometheus 官方约定：
  - 后缀 _total 表示单调递增的 Counter
  - 后缀 _seconds 表示单位统一的 Histogram
  - Gauge 用业务名词（tasks）而不是 xxx_total，避免被当成计数器做 rate()
  - 标签基数必须可控，所以 endpoint 用路由名（如 tasks.list_tasks），不用原始 URL。
"""

from prometheus_client import Counter, Gauge, Histogram, Info

REQUEST_COUNT = Counter(
    "http_requests_total",
    "HTTP 请求总数",
    ["method", "endpoint", "status"],
)

REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP 请求耗时（秒）",
    ["method", "endpoint"],
    # 分桶按本项目实际量级设定，避免全落在 +Inf 里导致 P95 失真
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

APP_INFO = Info(
    "app",
    "应用构建信息，暴露为 app_info{version,commit,env}，可用于对比部署前后版本",
)

TASK_GAUGE = Gauge(
    "tasks",
    "各状态的运维工单数量（业务指标）",
    ["status"],
)
