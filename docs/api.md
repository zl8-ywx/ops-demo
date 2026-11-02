# ops-demo 接口文档

Base URL：`http://<host>:8080`

统一约定：

- 请求体一律 `Content-Type: application/json`
- 响应一律 JSON（包括 4xx/5xx，不会返回 HTML 错误页）
- 每个响应头都带 `X-Request-ID`，可用来在日志里定位这一条请求
- 时间字段为 ISO 8601 UTC，以 `Z` 结尾

## 状态码语义

| 状态码 | 含义 | 谁的责任 |
| --- | --- | --- |
| 400 | 参数校验失败 | 调用方改请求 |
| 404 | 资源不存在 | 调用方 |
| 500 | 代码异常（也用于故障注入） | 开发改代码 |
| 503 | 依赖不可用（数据库挂了 / 未就绪） | 等恢复，**不要重启实例** |

> 500 与 503 的区分不是形式主义：告警规则要按这两类分别配置，
> 500 触发「需要人介入」的工单，503 只做「依赖健康度」提示。

---

## 一、业务接口

### 1. GET /api/hello

| 参数 | 位置 | 必填 | 说明 |
| --- | --- | --- | --- |
| name | query | 否 | 默认 `world` |

```bash
curl http://localhost:8080/api/hello?name=ops
```

```json
{"message": "hello, ops", "version": "1.0.0", "env": "prod"}
```

> `version` 来自环境变量 `APP_VERSION`，流水线里注入，
> 答辩时用它证明「部署的确实是新版本」。

### 2. GET /api/tasks

分页查询工单。

| 参数 | 位置 | 必填 | 说明 |
| --- | --- | --- | --- |
| page | query | 否 | 从 1 开始，默认 1 |
| size | query | 否 | 默认 20，上限 100（超出自动截断） |
| status | query | 否 | pending / running / done / failed |

```bash
curl "http://localhost:8080/api/tasks?status=done&page=1&size=20"
```

```json
{
  "items": [
    {
      "id": 3,
      "title": "重启 node1 上的 nginx",
      "description": "",
      "status": "done",
      "created_at": "2026-11-02T12:33:54.545853Z",
      "updated_at": "2026-11-02T13:01:02.113847Z"
    }
  ],
  "total": 1,
  "page": 1,
  "size": 20,
  "pages": 1
}
```

### 3. POST /api/tasks

创建工单。

| 字段 | 类型 | 必填 | 约束 |
| --- | --- | --- | --- |
| title | string | 是 | 去空格后非空，长度 ≤ 128 |
| description | string | 否 | 超过 2000 字符自动截断 |
| status | string | 否 | 默认 pending，必须是四种状态之一 |

```bash
curl -X POST http://localhost:8080/api/tasks \
  -H "Content-Type: application/json" \
  -d '{"title": "重启 node1 上的 nginx", "status": "pending"}'
```

返回 `201` 与完整对象。

> Windows 上用 `curl.exe` 加 `-d '{"a":"b"}'` 时，PowerShell 会吃掉内层双引号，
> 表现为服务端一直返回 400。改用 `Invoke-RestMethod` 或把 JSON 写进文件再 `-d @file.json`。

### 4. GET /api/tasks/{id}

```bash
curl http://localhost:8080/api/tasks/1
```

不存在返回 `404`。

### 5. PATCH /api/tasks/{id}

局部更新，只改传了的字段。

```bash
curl -X PATCH http://localhost:8080/api/tasks/1 \
  -H "Content-Type: application/json" \
  -d '{"status": "done"}'
```

### 6. DELETE /api/tasks/{id}

```bash
curl -X DELETE -i http://localhost:8080/api/tasks/1
```

成功返回 `204`，无响应体。

### 7. GET /api/tasks/stats

```json
{"pending": 0, "running": 1, "done": 2, "failed": 0}
```

---

## 二、故障注入接口（仅用于演练）

| 接口 | 参数 | 用途 |
| --- | --- | --- |
| GET /api/error | `rate` 0~1 | 按概率返回 500，制造错误率 |
| GET /api/slow | `ms` | 睡眠指定毫秒，制造延迟毛刺 |
| GET /api/cpu | `ms` | 忙等指定毫秒，打高 CPU 触发 HPA |

```bash
curl "http://localhost:8080/api/error?rate=1"     # 必返 500
curl "http://localhost:8080/api/slow?ms=3000"     # 慢 3 秒
curl "http://localhost:8080/api/cpu?ms=1000"      # 占用 CPU 1 秒
```

参数非法返回 `400`，超过上限自动截断（`MAX_SLOW_MS` / `MAX_CPU_MS`）。

---

## 三、运维接口

### GET /healthz

存活探针。只要进程能响应就返回 200，**不检查数据库**。

### GET /readyz

就绪探针。返回 200 表示可以接流量：

| 情况 | 状态码 | 响应 |
| --- | --- | --- |
| 启动预热期内 | 503 | `{"status": "starting"}` |
| 数据库不可用 | 503 | `{"status": "db_unavailable"}` |
| 正常 | 200 | `{"status": "ready"}` |

### GET /metrics

Prometheus 文本格式。

自定义指标：

| 指标 | 类型 | 标签 |
| --- | --- | --- |
| `http_requests_total` | Counter | method / endpoint / status |
| `http_request_duration_seconds` | Histogram | method / endpoint |
| `app_info` | Info | version / commit / env |
| `tasks` | Gauge | status |

`tasks` 是业务指标，把数据库里的工单状态同步到监控系统，
Grafana 的业务大盘直接查它，不需要再配一个数据库数据源。

```bash
curl -s http://localhost:8080/metrics | grep -E '^(app_info|tasks)'
```

```
app_info{commit="a1b2c3d",env="prod",version="1.0.0"} 1.0
tasks{status="done"} 2.0
tasks{status="failed"} 0.0
tasks{status="pending"} 5.0
tasks{status="running"} 1.0
```
