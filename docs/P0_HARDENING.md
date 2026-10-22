# P0 演示强化与故障恢复

## 本阶段完成内容

- 教师可对疑问簇中的任意一条原始问题执行人工拆分；拆分后旧簇质心重算、版本递增，并记录 `question_detached` 审计事件。
- Embedding 处理失败的问题保留为 `pending`，教师端显示重试队列，可在服务恢复后重新处理。
- 教师可结束课堂。结束时间写入数据库，学生端停止接收新问题，报告显示课堂终态与结束时间。
- 快照明确返回 `mode=demo` 和 `integration_status=not_configured`，三端不把本地数据展示成真实 POLYV 数据。
- `app/integrations` 定义统一输入边界。`DemoQuestionAdapter` 可供本地演示使用；`PolyvQuestionAdapter` 当前只抛出“未配置”错误，不访问网络、不调用 POLYV API。

## 故障演练

1. 在测试中让 `embed()` 抛出异常，确认问题仍入库且状态为 `pending`。
2. 恢复 `embed()`，调用 `POST /sessions/{session_id}/questions/{question_id}/retry`。
3. 确认问题进入疑问簇、错误码清空，问题总数不增加。
4. 结束课堂后再次提交问题，应返回 `409 session_ended`；既有快照和报告仍可读取。

## POLYV 接入门槛

获得比赛提供的正式鉴权信息和允许调用的 API 清单后，再实现 `PolyvQuestionAdapter.fetch_questions()`。输入必须先转换为 `NormalizedQuestion`，再进入现有幂等、聚类、反馈和报告流程。未满足该条件时保持 `not_configured`，避免路演时误报连接成功。

## 验收命令

```powershell
cd backend
uv run alembic upgrade head
uv run ruff check .
uv run pytest -q

cd ../frontend
pnpm run typecheck
pnpm run build
```
