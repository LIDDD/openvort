# Alembic 迁移指南

OpenVort 使用 Alembic 管理数据库 schema 演进。

## 快速参考

```bash
# 查看当前迁移状态
~/.virtualenvs/openvort/bin/alembic current

# 应用所有未执行迁移到最新版本
~/.virtualenvs/openvort/bin/alembic upgrade head

# 基于 ORM 变更自动生成迁移脚本
~/.virtualenvs/openvort/bin/alembic revision --autogenerate -m "add new_field to flow_stories"

# 回滚到上一个版本
~/.virtualenvs/openvort/bin/alembic downgrade -1

# 查看迁移历史
~/.virtualenvs/openvort/bin/alembic history
```

## 工作流

### 修改 ORM 模型后

1. 在 `src/openvort/.../models.py` 里加新字段 / 改字段类型 / 新建表
2. 运行 `alembic revision --autogenerate -m "<简短描述>"` 生成迁移脚本
3. **必须人工 review** `alembic/versions/*.py`:
   - 检查是否符合预期(autogenerate 不是 100% 准确)
   - 不要的 op 直接删,需要的补上
   - 类型变更要确认数据兼容(比如 `String → Integer` 需要数据迁移)
4. 运行 `alembic upgrade head` 应用迁移
5. 重启服务验证

### 现有环境首次接入

如果你的本地数据库是从老版本启动的(没有 `alembic_version` 表):

```bash
~/.virtualenvs/openvort/bin/alembic stamp head  # 标记为已应用 baseline,不实际执行
```

之后再跑迁移会从下一个版本继续。

## 数据库地址

env.py 自动读取 `OPENVORT_DATABASE_URL` 环境变量;**不要**在 `alembic.ini` 里硬编码。

## 注意事项

- `db/engine.py` 仍保留历史 `ALTER TABLE` 语句作为兼容性兜底,新部署可平滑迁移到 Alembic。
  新增 schema 变更**必须走 Alembic**,不要再往 engine.py 里加 ALTER。
- autogenerate 对 `index=True` / FK / unique 约束的检测准确,但对类型变更(如 String 长度)
  和默认值变更可能有遗漏,review 时要重点检查。
- 不要手动改已合并的 migration 文件,要修改请生成新 migration。
