-- =============================================================================
-- ops-demo 数据库设计
--
-- 用途：
--   1) 论文「数据库设计」章节的图表来源；
--   2) 本地 / 容器环境初始化建库建表；
--   3) 备份、恢复、索引优化等运维演练的对象。
--
-- 字符集统一 utf8mb4：中文标题不会因为 3 字节编码被截断。
-- 时间统一存 UTC 的 DATETIME：跨时区部署时不会出现同一行记录时间对不上。
-- =============================================================================

CREATE DATABASE IF NOT EXISTS `ops_demo`
    DEFAULT CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE `ops_demo`;

CREATE TABLE IF NOT EXISTS `task` (
    `id`          INT          NOT NULL AUTO_INCREMENT COMMENT '主键',
    `title`       VARCHAR(128) NOT NULL                COMMENT '工单标题',
    `description` TEXT         NOT NULL                COMMENT '工单描述',
    `status`      VARCHAR(16)  NOT NULL DEFAULT 'pending'
        COMMENT '状态：pending / running / done / failed',
    `created_at`  DATETIME     NOT NULL                COMMENT '创建时间（UTC）',
    `updated_at`  DATETIME     NOT NULL                COMMENT '更新时间（UTC）',

    PRIMARY KEY (`id`),

    -- 列表页最常见查询是「按状态筛选 + 按 id 倒序分页」，
    -- 建复合索引后可以直接走索引完成过滤与排序，避免 filesort。
    KEY `idx_task_status_id` (`status`, `id`),

    -- 标题支持模糊搜索
    KEY `ix_task_title` (`title`)
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4
  COLLATE = utf8mb4_unicode_ci
  COMMENT = '运维工单';
