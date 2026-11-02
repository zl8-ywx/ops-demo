"""数据库接入层。

三个设计要点（论文「系统设计」章节可以直接展开写）：
  1. 通过 DATABASE_URL 切换存储实现，本地默认 SQLite、线上 MySQL，
     同一份代码不因为环境不同而分叉。
  2. 连接池开启 pool_pre_ping + pool_recycle，
     解决 MySQL 默认 8 小时空闲断连后报 "MySQL server has gone away"。
  3. 建表失败不阻塞进程启动：记录错误后继续运行，
     由就绪检查把实例挡在流量之外，而不是让容器反复崩溃重启。
"""

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


def build_engine_options(uri: str) -> dict:
    """SQLite 与 MySQL 的引擎参数不通用，必须分开构造。

    SQLite 不接受 pool_size / max_overflow 这类参数，直接传会抛 TypeError。
    """
    if uri.startswith("sqlite"):
        return {
            # check_same_thread=False：gunicorn 多线程下连接会跨线程复用
            "connect_args": {"check_same_thread": False, "timeout": 15},
        }
    return {
        # 取连接前先 ping，断线自动重建，避免把失效连接交给业务
        "pool_pre_ping": True,
        # 小于 MySQL 的 wait_timeout（默认 28800s），主动回收旧连接
        "pool_recycle": 1800,
        "pool_size": 5,
        "max_overflow": 10,
        "pool_timeout": 10,
    }


def init_db(app) -> None:
    # 必须在 init_app 之前 import models，否则 create_all 拿不到表定义
    from . import models  # noqa: F401

    db.init_app(app)

    if not app.config["AUTO_CREATE_TABLES"]:
        return

    try:
        with app.app_context():
            db.create_all()
    except Exception:  # noqa: BLE001
        # 数据库可能还没就绪（比如应用比 MySQL 先起来）。
        # 这里不退出进程，交给就绪检查处理，避免容器反复崩溃重启。
        app.logger.exception("create_tables_failed")
