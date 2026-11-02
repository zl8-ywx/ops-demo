"""数据模型。

只保留一个实体「运维工单 Task」，理由：
  - 足够简单，不会喧宾夺主；
  - 状态流转（pending → running → done/failed）能自然映射到「业务指标」，
    可以做成 Grafana 业务大盘和告警规则；
  - 有增删改查，才有备份、恢复、数据一致性这些运维话题可写。
"""

from datetime import datetime, timezone

from .db import db

# 状态白名单放在这里，路由层与指标层共用同一份定义，避免两处漂移
ALLOWED_STATUS = ("pending", "running", "done", "failed")


def utcnow() -> datetime:
    """统一存 UTC 的 naive datetime。

    数据库里统一 UTC，展示时由前端或调用方换算时区，
    否则跨时区部署会出现「同一行记录时间对不上」的问题。
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Task(db.Model):
    __tablename__ = "task"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    title = db.Column(db.String(128), nullable=False, index=True)
    description = db.Column(db.Text, nullable=False, default="")
    status = db.Column(
        db.String(16),
        nullable=False,
        default="pending",
        index=True,
    )
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    updated_at = db.Column(
        db.DateTime, nullable=False, default=utcnow, onupdate=utcnow
    )

    __table_args__ = (
        # 复合索引：列表页最常见的查询是「按状态筛选 + 按 id 倒序分页」
        db.Index("idx_task_status_id", "status", "id"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description or "",
            "status": self.status,
            "created_at": self.created_at.isoformat() + "Z",
            "updated_at": self.updated_at.isoformat() + "Z",
        }

    def __repr__(self) -> str:  # pragma: no cover
        return "<Task id={} status={} title={!r}>".format(
            self.id, self.status, self.title
        )
