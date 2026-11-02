# ops-demo

基于 Flask 的运维工单服务。提供工单管理、健康检查、Prometheus 指标与结构化日志。

## 技术栈

| 组件 | 版本 | 用途 |
| --- | --- | --- |
| Python | 3.11 | 运行时（镜像内固定） |
| Flask | 3.0 | Web 框架 |
| SQLAlchemy / Flask-SQLAlchemy | 2.0 / 3.1 | ORM |
| PyMySQL | 1.1 | MySQL 驱动 |
| gunicorn | 22.0 | WSGI 服务器 |
| prometheus-client | 0.20 | 指标暴露 |

存储默认用 SQLite，配置 `DATABASE_URL` 即切换到 MySQL，代码无需改动。

## 功能

- 工单增删改查，支持分页、按状态过滤、参数校验
- 存活检查 `/healthz` 与就绪检查 `/readyz`
- Prometheus 指标，含 HTTP 层指标和业务层指标
- JSON 结构化日志，每条日志带 `X-Request-ID`
- 连接池、优雅停机、统一错误响应
- 故障注入接口，用于压测和告警演练

## 目录结构

```
ops-demo/
├── app/
│   ├── __init__.py        应用工厂：配置 / 中间件 / 错误处理
│   ├── routes.py          业务接口 + 故障注入 + 健康检查 + 指标端点
│   ├── tasks.py           工单 CRUD
│   ├── models.py          数据模型
│   ├── db.py              数据库接入与连接池配置
│   ├── metrics.py         Prometheus 指标定义
│   └── logging_conf.py    JSON 结构化日志
├── tests/
│   ├── conftest.py        测试夹具（每个用例独立 SQLite）
│   ├── test_api.py        基础接口测试
│   └── test_tasks.py      工单 CRUD 测试
├── docs/
│   ├── api.md             接口文档（含 curl 示例）
│   └── schema.sql         MySQL 建表脚本
├── Dockerfile             多阶段构建，最终镜像约 150MB
├── docker-compose.yml     本地开发编排（app + MySQL）
├── .env.example
├── pytest.ini
└── requirements.txt
```

## 快速开始

### 方式 A：docker compose（app + MySQL 一起起）

```bash
docker compose up -d --build
docker compose logs -f app

curl http://localhost:8080/api/hello
curl http://localhost:8080/api/tasks/stats
```

首次启动 MySQL 需要 30 秒左右初始化，`depends_on` 已配置健康检查等待。

### 方式 B：只跑应用（默认 SQLite，零外部依赖）

```bash
docker build -t ops-demo:local .
docker run --rm -p 8080:8080 -e APP_VERSION=1.0.0 ops-demo:local
```

### 方式 C：本地 Python

需要 Python 3.8 以上（Flask 3.x 的要求）。

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
python wsgi.py
```

## 接口

完整文档见 [`docs/api.md`](docs/api.md)。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/hello` | 返回问候语与当前版本号 |
| GET | `/api/tasks` | 工单分页查询（`page` / `size` / `status`） |
| POST | `/api/tasks` | 创建工单 |
| GET | `/api/tasks/{id}` | 工单详情 |
| PATCH | `/api/tasks/{id}` | 局部更新 |
| DELETE | `/api/tasks/{id}` | 删除工单 |
| GET | `/api/tasks/stats` | 各状态数量 |
| GET | `/healthz` | 存活检查 |
| GET | `/readyz` | 就绪检查（含数据库检查） |
| GET | `/metrics` | Prometheus 指标 |

压测与告警演练用的辅助接口：

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/error?rate=` | 按概率返回 500 |
| GET | `/api/slow?ms=` | 睡眠指定毫秒 |
| GET | `/api/cpu?ms=` | 忙等指定毫秒，占用 CPU |

### 暴露的指标

| 指标 | 类型 | 标签 |
| --- | --- | --- |
| `http_requests_total` | Counter | method / endpoint / status |
| `http_request_duration_seconds` | Histogram | method / endpoint |
| `app_info` | Info | version / commit / env |
| `tasks` | Gauge | status |

## 配置项

全部通过环境变量注入，未设置时使用默认值。

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `APP_VERSION` | `dev` | 版本号，`/api/hello` 与 `app_info` 会返回 |
| `GIT_COMMIT` | `unknown` | 提交号，用于定位部署版本 |
| `ENV_NAME` | `local` | 环境标识 |
| `DATABASE_URL` | `sqlite:///<系统临时目录>/ops-demo.db` | 数据库连接串 |
| `AUTO_CREATE_TABLES` | `true` | 启动时自动建表 |
| `READYZ_CHECK_DB` | `true` | `/readyz` 是否检查数据库 |
| `ERROR_RATE` | `0.0` | `/api/error` 的默认错误率 |
| `STARTUP_DELAY_SECONDS` | `0` | 启动预热秒数，期间 `/readyz` 返回 503 |
| `MAX_SLOW_MS` | `10000` | `/api/slow` 的上限 |
| `MAX_CPU_MS` | `5000` | `/api/cpu` 的上限 |
| `LOG_LEVEL` | `INFO` | 日志级别 |
| `JSON_LOGS` | `true` | 是否输出 JSON 日志 |

## 数据库

表结构与索引说明见 [`docs/schema.sql`](docs/schema.sql)。

建表两种方式：

| 方式 | 配置 | 适用场景 |
| --- | --- | --- |
| 应用自动建表 | `AUTO_CREATE_TABLES=true` | 开发、演示 |
| 执行 DDL 脚本 | `AUTO_CREATE_TABLES=false` + `mysql < docs/schema.sql` | 生产，变更需评审 |

连接池参数在 `app/db.py` 中：

| 参数 | 值 | 说明 |
| --- | --- | --- |
| `pool_pre_ping` | True | 取连接前先 ping，断线自动重建 |
| `pool_recycle` | 1800s | 小于 MySQL 默认 `wait_timeout` 28800s，主动回收 |
| `pool_size` | 5 | 常驻连接数 |
| `max_overflow` | 10 | 峰值可临时扩到 15 |

容量规划时注意：`实例数 × (pool_size + max_overflow) < MySQL max_connections`。

## 测试

```bash
pip install -r requirements-dev.txt
pytest -v
```

共 23 条用例，覆盖：

- 业务接口与版本号返回
- 故障注入的概率、上限截断、非法参数
- 健康检查与就绪检查
- 请求 ID 透传
- 指标暴露与业务指标联动
- 工单 CRUD、分页、状态过滤、参数校验、404

## 设计说明

### 500 与 503 分开

| 码 | 语义 | 处理方式 |
| --- | --- | --- |
| 500 | 代码 bug | 需要人改代码 |
| 503 | 依赖不可用 | 等依赖恢复 |

混用会让告警无法区分「要人介入」和「自动恢复」。

### 存活检查不查数据库

`/healthz` 只判断进程能否响应。如果这里查库，数据库抖动会导致所有实例被同时重启，
把一个可恢复的依赖故障放大成雪崩。依赖检查放在 `/readyz` 里。

### 就绪检查查库的取舍

开启 `READYZ_CHECK_DB` 后，数据库不可用时所有实例都判定为不可用，服务完全拒绝流量。
这是可用性与正确性的取舍，可用该变量关闭。

### 单进程多线程

`prometheus_client` 的默认注册表是进程内的。gunicorn 开多个 worker 时，
`/metrics` 只会返回当前处理请求的那个 worker 的数据，其余全部丢失。
因此使用 `--workers 1 --threads 8`。

如需多进程，需要设置 `PROMETHEUS_MULTIPROC_DIR` 并改用 `MultiProcessCollector`，
代价是每次重启要清理目录，且 Counter 的聚合语义有差异。

### 业务指标进 Prometheus

`tasks{status=...}` 由应用在写操作后同步到 Prometheus，
而不是让 Grafana 直连 MySQL。原因：

- 避免 Grafana 持有数据库凭证
- 避免每次刷新大盘都压一次业务库
- 便于统一用 PromQL 做告警和历史对比

### 优雅停机

gunicorn 收到 SIGTERM 后停止接受新连接，等待正在处理的请求完成，
最多等待 `--graceful-timeout 25` 秒。

## 注意事项

- **Python 3.13+ 与 SQLAlchemy 2.0.30 不兼容**：会报
  `TypeError: Can't replace canonical symbol for '__firstlineno__'`。
  `requirements.txt` 已放宽到 `>=2.0.30,<2.1`，镜像固定 Python 3.11 不受影响。
- **Windows 下 curl 传 JSON**：PowerShell 会吃掉内层双引号，表现为一直返回 400。
  改用 `Invoke-RestMethod`，或把 JSON 写进文件再 `-d @file.json`。
- **Windows 换行符**：拷 `.sh` 到 Linux 会带 CRLF，bash 报 `$'\r': command not found`。
  项目已加 `.gitattributes` 强制 `eol=lf`。
- **带标签的 Gauge 初始不出现**：`Gauge` 只有调用过 `.labels()` 才会产生样本。
  启动时用 `init_task_gauge()` 把四个状态先置 0，避免监控面板显示 "No data"。
