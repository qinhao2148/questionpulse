# 0—5 小时开发成果：本地问题与聚类链路

完成日期：2026-10-20。此阶段没有调用或修改 POLYV。

## 已实现

- 创建本地课堂，学生以稳定 viewer key 加入。
- 问题使用 `session + participant + client_request_id` 幂等持久化。
- 离线中文语义向量 `questionpulse-zh-semantic-hash-v1`：概念归一化后进行固定维度特征哈希，输出 256 维单位向量。
- 余弦相似度达到 0.55 时自动归入已有簇，否则新建疑问簇。
- 保存向量模型、分配方式和相似度；模型异常时保留问题并标记 `pending`。
- 教师快照按独立参与者数和问题数排序，可查看原文并拆分误合并问题。
- Vue 学生端接入加入、提交和快照接口；教师端读取真实快照并执行人工拆分。

该离线向量模型是比赛现场的可复现保底实现。接入正式中文 Embedding 服务时，只替换 `app/services/embedding.py`，数据字段和聚类流程保持不变。

## 启动与演示

```powershell
docker compose up -d mysql
cd backend
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

另开终端：

```powershell
pnpm dev:frontend
cd backend
uv run python scripts/seed_demo.py
```

脚本输出本次课堂的学生端和教师端地址。也可以访问首页，点击“创建本地课堂”，再使用导航进入学生端。

## 当前边界

- 数据库生产配置为 MySQL 8；自动化测试使用隔离的内存 SQLite。
- MySQL 8.0.41 容器健康检查通过，Alembic 已从现有版本升级到 `20261020_0002 (head)`，FastAPI `/health/ready` 返回 database ok。
- 当前教师拆分操作会建立新簇并写入审计事件；旧簇质心重算属于下一阶段优化。
- 身份与教师权限仍为本地开发模式，正式展示前需要增加会话鉴权。
