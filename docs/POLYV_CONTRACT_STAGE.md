# 12—17 小时阶段：POLYV 接入契约与报告交付

## 已实现

- 课堂记录 `polyv_channel_id`、`polyv_session_id`、`last_synced_at` 和明确的接入状态。
- 问题记录 `source`、`external_id`、`occurred_at`；数据库以 `(session_id, source, external_id)` 唯一约束阻止重复导入。
- 本地桥接端点 `POST /sessions/{id}/integrations/polyv/events` 仅接受 `environment=contract_test`，用于验证官方字段映射、去重、参与者建立和聚类流程。
- `PolyvQuestionAdapter.normalize_event()` 把候选官方载荷归一化为统一问题对象；真实网络传输继续显式禁用。
- 教师端可运行契约验证，并显示“契约已验证（未连接真实账号）”；问题详情展示来源和外部 ID。
- 报告页支持打印和 UTF-8 CSV 导出。

## 状态含义

| 状态 | 含义 |
|---|---|
| `not_configured` | 未配置或未获准联调 |
| `contract_verified` | 本地载荷契约和去重已通过，不能宣称真实连接 |
| `connected` | 预留给真实账号成功联调；本阶段不会写入此状态 |

## 本地验收

样例位于 `fixtures/polyv-contract-sample.json`。重复提交同一载荷时，第一次返回 `accepted=2`，第二次返回 `accepted=0, duplicates=2`，问题总数不增加。

真实联调时只替换适配器的传输层，并在成功读取一条官方数据后将状态置为 `connected`。密钥只放后端 `.env`，前端不接触签名信息。
