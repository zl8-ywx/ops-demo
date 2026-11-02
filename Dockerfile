# syntax=docker/dockerfile:1
# ---------------------------------------------------------------------------
# 多阶段构建：
#   阶段一 builder 只负责把依赖编译成 wheel，避免把编译器等构建期垃圾带进运行镜像
#   阶段二 runtime 只装 wheel，最终镜像约 140MB
#
# 与 pip install 直装相比的好处：
#   1. 镜像更小；2. 构建缓存更稳定；3. 运行镜像里没有 gcc，攻击面更小
# ---------------------------------------------------------------------------

FROM python:3.11-slim AS builder

WORKDIR /build
ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

COPY requirements.txt .
RUN pip wheel --wheel-dir=/wheels -r requirements.txt


FROM python:3.11-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Asia/Shanghai

# 固定 uid=1000，便于编排层用整数 UID 指定运行用户，
# 避免容器内用户与编排层的安全上下文不一致导致权限报错
RUN groupadd -r -g 1000 app \
 && useradd -r -u 1000 -g app -s /sbin/nologin app

WORKDIR /app

COPY --from=builder /wheels /wheels
COPY requirements.txt .
RUN pip install --no-index --find-links=/wheels -r requirements.txt \
 && rm -rf /wheels

COPY app/ ./app/
COPY wsgi.py .

USER 1000

EXPOSE 8080

# 容器自身的健康检查（编排层有各自的健康检查机制，这里是为了 docker run 场景）
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=2).status == 200 else 1)"

# 单进程多线程：规避 prometheus_client 多进程指标丢失问题（见 README 第八节）
# graceful-timeout 25s 留足余量，让编排层先把流量摘干净，再让进程退出
# 不开 --access-logfile：访问日志已由应用中间件以 JSON 形式输出，
# 再开 gunicorn 的会变成一行 JSON + 一行纯文本，检索时很难处理
CMD ["gunicorn", \
     "--bind", "0.0.0.0:8080", \
     "--workers", "1", \
     "--threads", "8", \
     "--graceful-timeout", "25", \
     "--error-logfile", "-", \
     "wsgi:app"]
