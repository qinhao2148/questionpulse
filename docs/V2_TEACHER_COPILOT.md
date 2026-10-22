# QuestionPulse V2：教师悬浮助手与 DeepSeek 语义分析

规划日期：2026-10-22

## 1. 产品重新定位

QuestionPulse V2 是运行在 POLYV 网页开播台上的教师智能助手。教师无需离开直播页面，悬浮助手持续展示全班疑问、受影响人数、理解反馈和教学建议。

核心价值从“独立教师看板”升级为：

> 在教师原有 POLYV 开播流程中，实时理解学生问题、识别群体困惑，并帮助教师完成讲解与反馈闭环。

## 2. 用户工作流

```text
教师打开 POLYV 网页开播台
          ↓
QuestionPulse 浏览器扩展注入悬浮助手
          ↓
学生在 QuestionPulse/POLYV 中提问
          ↓
问题先幂等保存到 MySQL
          ↓
DeepSeek 批量分析意图并聚类
          ↓
悬浮助手显示 Top 疑问和教学建议
          ↓
教师确认“开始讲解/结束讲解”
          ↓
学生反馈“已理解/仍困惑”
          ↓
数据库生成事实报告，DeepSeek 生成教学总结
```

## 3. 设计原则

### DeepSeek 负责语义

- 理解学生问题意图。
- 判断新问题加入已有疑问簇还是创建新簇。
- 生成疑问簇标题和摘要。
- 提供合并、拆分建议。
- 生成讲解提纲和检查理解问题。
- 根据事实报告生成课后教学建议。

### QuestionPulse 负责事实

- 保存原始问题。
- 按客户端请求和 POLYV 官方 ID 幂等去重。
- 计算问题数、独立学生数、反馈覆盖率和仍困惑人数。
- 维护课堂、疑问簇和反馈状态机。
- 验证 DeepSeek 返回的 ID、结构和操作范围。
- 保存 AI 决策的模型、置信度、理由和版本。

模型不直接生成最终统计数字，也不能未经教师确认结束课堂、关闭疑问或修改历史数据。

## 4. 系统分层

```text
┌─────────────────────────────────────────────┐
│ POLYV 网页开播台                             │
│  └─ QuestionPulse Teacher Copilot 悬浮助手  │
└──────────────────────┬──────────────────────┘
                       │ HTTPS
┌──────────────────────▼──────────────────────┐
│ FastAPI                                     │
│  ├─ Classroom API                           │
│  ├─ Assistant API                           │
│  ├─ AI Orchestrator                         │
│  ├─ DeepSeek Provider                       │
│  └─ Local Semantic Fallback                 │
└──────────────┬──────────────────┬───────────┘
               │                  │
        ┌──────▼──────┐    ┌──────▼─────────┐
        │ MySQL 事实层 │    │ DeepSeek API   │
        └─────────────┘    └────────────────┘
```

## 5. 教师悬浮助手

### 技术形态

使用 Manifest V3 Chromium 浏览器扩展，仅匹配保利威网页开播域名。内容脚本挂载一个隔离的 Shadow DOM，避免与保利威页面样式冲突。

目录建议：

```text
extension/
├─ manifest.json
├─ src/
│  ├─ content.ts
│  ├─ service-worker.ts
│  ├─ api.ts
│  ├─ AssistantOrb.vue
│  ├─ AssistantPanel.vue
│  ├─ ClusterCard.vue
│  └─ styles.css
└─ vite.config.ts
```

### 收起状态

- 52px 紫色脉搏球。
- 新疑问显示数字角标。
- 高频疑问触发一次轻微脉冲。
- 断连变灰，不遮挡开播操作。
- 可拖动并记住位置。

### 展开状态

宽约 380px，高度不超过浏览器可视区域的 80%。只显示授课时需要的内容：

1. 课堂连接状态。
2. 当前讲解问题。
3. 疑问 Top 3 与独立学生数。
4. 仍困惑提醒。
5. DeepSeek 摘要和讲解建议。
6. 开始讲解、结束讲解、关闭疑问等确认按钮。

完整配置、历史记录和报告仍留在 QuestionPulse 教师页面。

## 6. DeepSeek 聚类流程

### 进入队列

新问题必须先写入数据库并标记为 `pending`，之后才进入 AI 分析队列。模型故障不能导致原始问题丢失。

### 微批处理

在 3～5 秒窗口内收集新问题，一次发送多个问题，减少请求次数并提高全局判断质量。

输入只包含：

- 课堂课题；
- 新问题的内部 ID 和正文；
- 已有疑问簇的内部 ID、标题和少量代表问题；
- 不包含学生姓名、原始 POLYV viewerId 或任何密钥。

### 结构化输出

```json
{
  "assignments": [
    {
      "question_id": "q1",
      "action": "join",
      "cluster_id": "c1",
      "confidence": 0.94,
      "normalized_intent": "递归缺少终止条件的后果",
      "reason": "问题核心与现有递归出口疑问一致"
    },
    {
      "question_id": "q2",
      "action": "create",
      "new_cluster_key": "new-1",
      "suggested_title": "异步异常如何传播",
      "confidence": 0.89,
      "normalized_intent": "Promise 异常传播"
    }
  ]
}
```

服务端必须检查：

- 所有问题 ID 属于当前课堂且处于待处理状态。
- `join` 指向的疑问簇真实存在。
- 一个问题只能出现一次。
- 置信度在 0～1 范围。
- 输出数量与输入问题相符。
- JSON 解析或校验失败时不得写入部分结果。

### 置信度策略

| 置信度 | 处理 |
| --- | --- |
| `≥ 0.85` | 自动加入已有簇或创建新簇 |
| `0.60～0.85` | 创建新簇并标记“建议教师检查” |
| `< 0.60` | 使用本地算法给出候选，但保持人工确认状态 |

阈值应通过现有标注集评测后确定，不能只凭演示效果选择。

## 7. AI 数据记录

建议增加：

### `ai_runs`

- `id`
- `session_id`
- `task_type`
- `provider`
- `model`
- `status`
- `input_fingerprint`
- `latency_ms`
- `prompt_tokens`
- `completion_tokens`
- `error_code`
- `created_at`

### `ai_decisions`

- `id`
- `ai_run_id`
- `question_id`
- `cluster_id`
- `action`
- `confidence`
- `reason`
- `normalized_intent`
- `accepted_by`
- `created_at`

不保存密钥，不把原始 viewerId 发送给模型，不在普通日志中记录完整 Prompt。

## 8. 后端模块

```text
backend/app/ai/
├─ base.py
├─ schemas.py
├─ orchestrator.py
├─ prompts.py
├─ deepseek.py
└─ fallback.py
```

接口建议：

```text
GET  /sessions/{id}/assistant/brief
POST /sessions/{id}/assistant/analyze-pending
POST /sessions/{id}/assistant/clusters/{clusterId}/explanation
POST /sessions/{id}/assistant/clusters/{clusterId}/check-question
GET  /sessions/{id}/assistant/suggestions
POST /sessions/{id}/assistant/suggestions/{suggestionId}/confirm
```

DeepSeek 配置仅存在后端：

```env
LLM_BASE_URL=https://api.deepseek.com
LLM_API_KEY=
LLM_MODEL=deepseek-flash
LLM_TIMEOUT_SECONDS=15
LLM_MAX_OUTPUT_TOKENS=1200
```

## 9. 降级策略

现有 `questionpulse-zh-semantic-hash-v1` 不删除，改为降级能力：

1. DeepSeek 正常：使用 DeepSeek 进行主要聚类。
2. DeepSeek 超时或限流：问题保持 `pending`，后台退避重试。
3. 演示现场需要立即显示：使用本地算法生成临时分组，并标记来源为 fallback。
4. DeepSeek 恢复后可重新分析低置信度或 fallback 结果。
5. 已经由教师确认的聚类不自动覆盖。

## 10. 实施阶段

### V2-P0：悬浮助手基础版

- 建立 `extension/` 工程和 MV3 配置。
- 在保利威开播页面注入悬浮球和 Shadow DOM。
- 配置本地后端地址与课堂 ID。
- 读取当前课堂、Top 3 疑问和反馈状态。
- 支持教师确认状态操作。
- Edge 解压加载并完成页面兼容验证。

退出条件：教师全程停留在保利威开播页即可查看并处理疑问。

### V2-P1：DeepSeek 主要聚类

- 增加 AI Provider 接口、DeepSeek 客户端和结构化 Schema。
- 增加 `ai_runs`、`ai_decisions` 迁移。
- 实现微批处理、超时、重试、缓存和本地降级。
- 用现有标注集比较 DeepSeek 与本地算法。
- 教师端展示模型、置信度和决策原因。

退出条件：DeepSeek 聚类效果在固定测试集上优于当前算法，API 故障时不丢问题。

### V2-P2：教学 Copilot

- 疑问簇摘要。
- 一分钟讲解提纲。
- 检查理解问题。
- 高影响疑问主动提醒。
- 所有写操作均要求教师确认。

退出条件：AI 建议有来源数据、可忽略、不可越权修改课堂。

### V2-P3：课后智能总结

- 基于数据库事实生成课堂总结。
- 输出下节课复习建议。
- 保存事实引用，不让模型自行生成统计数据。
- 报告中区分“事实统计”和“AI 建议”。

## 11. 测试范围

- DeepSeek 正常、超时、429、5xx、空输出、非法 JSON 和截断输出。
- 模型返回不存在的课堂、问题或疑问簇 ID。
- 同一批问题重试不重复归簇。
- DeepSeek 与本地降级在相同数据上的结果记录。
- 已归档课堂拒绝 AI 写入。
- 扩展在保利威页面刷新、路由切换和全屏操作后仍可恢复。
- 悬浮窗不遮挡开始直播、结束直播、麦克风和摄像头控制。
- Edge 和 Chrome 解压扩展测试。
- API Key 不进入扩展包、前端产物、日志或提交压缩包。

## 12. 暂不实现

- AI 自动替教师发送回答。
- AI 自动开始或结束直播。
- 未经确认自动关闭疑问簇。
- 读取摄像头、麦克风或教师屏幕内容。
- 用模型输出替代数据库统计。
- 为比赛演示引入向量数据库、多 Agent 或复杂知识库 RAG。

## 13. 比赛演示主线

1. 教师在 POLYV 页面开播，右下角出现 QuestionPulse 悬浮助手。
2. 多名学生提交表达不同但语义相同的问题。
3. DeepSeek 将它们识别为同一群体疑问，并展示判断原因。
4. 数据库准确显示独立学生人数。
5. 悬浮助手生成一分钟讲解提纲，教师点击开始讲解。
6. 学生提交理解反馈，教师无需离开 POLYV 页面即可看到仍困惑人数。
7. 结束课堂后播放器关闭，报告展示事实统计和 AI 教学建议。

这条主线同时展示 POLYV 集成、AI 技术、产品体验、数据可信度和实际教学价值。
