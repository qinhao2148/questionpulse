# QuestionPulse 接口契约（MVP）

版本：2026-10-20。本文锁定前后端并行开发所需的最小契约；路径均为 QuestionPulse 自有接口，不代表 POLYV 官方接口。

本地 POLYV 契约验证端点为 `POST /sessions/{id}/integrations/polyv/events`。它只接受 `environment=contract_test`，不会访问 POLYV；每条事件必须包含 `external_id`、`viewer_key`、`content`、`occurred_at` 和 `source`。相同课堂、来源和外部 ID 的重放会计入 `duplicates`，不会新增问题。

## 通用规则

- 前缀 `/api/v1`，JSON 使用 `snake_case`，时间为 UTC ISO 8601。
- 成功：`{"data": ..., "request_id": "uuid"}`；失败：`{"error":{"code":"...","message":"..."},"request_id":"uuid"}`。
- 学生与教师身份由 HttpOnly 会话确定，浏览器提交的身份和角色一律不可信。
- 写接口支持幂等；状态修改携带 `expected_version`，冲突返回 `409`。

## 核心对象

```ts
type ClusterStatus = 'open' | 'addressing' | 'awaiting_feedback' | 'closed'
type Source = 'questionpulse' | 'polyv_chat' | 'polyv_qa' | 'demo'

interface ClusterSummary {
  id: string
  title: string
  status: ClusterStatus
  version: number
  participant_count: number
  question_count: number
  first_question_at: string
  feedback_round: number
  feedback?: { targets: number; understood: number; still_confused: number }
}
```

状态修改必须携带当前 `version`。从讲解中进入等待反馈时，服务端增加 `feedback_round` 并冻结目标学生；反馈按 `(cluster_id, round, participant_id)` 唯一。

## HTTP

| 方法 | 路径 | 输入 | 关键输出/行为 |
|---|---|---|---|
| POST | `/sessions/{id}/join` | `{join_token, display_name?}` | 建立学生会话 |
| GET | `/sessions/{id}/snapshot` | — | 按角色返回课堂、连接状态、疑问簇 |
| POST | `/sessions/{id}/questions` | `{client_request_id, content}` | `202`；返回 `question_id` 与 `processing` |
| GET | `/sessions/{id}/questions/mine` | — | 本人的问题及匹配簇，不暴露他人原文 |
| GET | `/sessions/{id}/clusters/{cid}/questions` | — | 教师查看可追溯原文 |
| PATCH | `/sessions/{id}/clusters/{cid}/status` | `{status, expected_version}` | 推进或重新打开状态机 |
| POST | `/sessions/{id}/questions/{qid}/detach` | `{expected_cluster_version}` | 人工拆分误合并问题 |
| PUT | `/sessions/{id}/clusters/{cid}/feedback` | `{round, result}` | `understood` 或 `still_confused`，同轮覆盖更新 |
| GET | `/sessions/{id}/report` | — | 事实统计、未闭环清单及可选建议 |

反馈写入：`PUT /sessions/{id}/clusters/{cid}/feedback`，输入 `{participant_id, round, result}`。重复提交同一轮会更新原记录，不增加响应人数。

## 实时事件

连接 `/ws/v1/sessions/{id}`；断线后重新请求 snapshot，不依赖事件补齐全部状态。

```json
{
  "event": "cluster.updated",
  "event_id": "uuid",
  "session_id": "uuid",
  "occurred_at": "2026-10-20T12:00:00Z",
  "data": {"cluster_id": "uuid", "version": 4}
}
```

P0 事件：`question.accepted`、`question.clustered`、`cluster.created`、`cluster.updated`、`feedback.updated`、`integration.status_changed`。

## 验收样例

1. 同一 `client_request_id` 重放只产生一条问题。
2. 两名学生的同义问题形成一个簇，`participant_count=2`、`question_count=2`。
3. 旧 `expected_version` 修改返回 `409`，不会覆盖新状态。
4. 每名学生在同一反馈轮只计一次，修改反馈不增加 targets。
5. 学生 snapshot 不包含其他学生身份与原始问题。
