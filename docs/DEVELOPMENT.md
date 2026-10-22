# QuestionPulse 开发指南

版本：1.1 · 初始日期：2026-10-19 · 状态更新：2026-10-22 · 适用：校园个人赛 Demo

项目名称：**QuestionPulse**

项目定位：接入 POLYV 的直播课堂疑问聚合与解决追踪工具。将学生的重复问题聚合为疑问簇，帮助教师决定先讲什么，并收集讲解后的理解反馈。

本文件是开发基线。标为 P0 的能力构成最小交付；P1 仅在 P0 验收后开发。本文中的接口、事件和数据表均为 QuestionPulse 自有设计，除非明确注明 POLYV 官方接口。

## 1. 约束与证据边界

### 1.1 比赛约束

- 用户提供的海报：校园赛道要求使用 POLYV API 或 SDK 开发工具、小程序或 App；支持个人参赛。
- 第一阶段创新力、技术实现力、体验与设计力、实际价值、展示与感染力各占 20%。
- 海报标注 10 月 23—24 日的创作为 **24 小时**。按用户的两天准备期安排准备工作，正式工作按约 24 小时窗口、约 16 小时有效开发预算安排，保留休息和现场缓冲。
- 海报未说明赛前可提交多少预写代码、第三方模型限制及具体交付格式。准备期默认以环境、文档、技术学习和样例验证为主；可复用代码是否允许带入，以主办方细则为准。

### 1.2 已知与未知

| 项目 | 当前证据 | 开发结论 |
|---|---|---|
| 聊天、问答、知识库答疑、回放 AI 看 | 官方文档已提供相关能力 | 不以这些基础功能本身作为创新 |
| 语义疑问簇、人数排序、理解反馈闭环 | 已检查资料中未发现完整同类方案 | 可主张扩展价值，不宣称保利威所有版本绝对没有 |
| 聊天历史和聊天事件 | 官方 SDK 文档存在 | 具体版本、字段、可见范围需验证 |
| 问答列表 | 官方服务端文档存在 | 不等于当前账号已获调用权限 |
| 当前素材库 | 页面显示到期、无视频素材 | P0 不依赖新回放、逐字稿或 AI 看 |
| 直播播放、观看授权、提问发送、问答读取 | 已完成真实 SDK/API 单链路验收 | 可展示真实接入证据；Edge 播放仍需人工复核 |

本文最初记录的是准备期约束；之后用户已明确授权真实 API/SDK 验证，并完成一条真实问题的导入与幂等去重。密钥仍只保存在服务端本机配置中。

“提问”“问答”“聊天室”可能是不同业务模块；不能因为名称相似，就认为 SDK 事件与问答列表 API 读取同一份记录。

## 2. MVP 产品范围

### 2.1 用户故事

1. 学生进入绑定 POLYV 频道的自定义观看页，提交课堂问题，看到提交是否成功。
2. 不同学生用不同表述提出同一问题，教师端显示一个疑问簇及独立提问人数。
3. 教师查看原始问题，将疑问簇标记为讲解中；讲解完成后请求学生反馈。
4. 学生选择“已理解”或“仍困惑”。教师据此决定结束或再次讲解。
5. 课后报告列出高频疑问、处理状态和反馈情况，每个结论可追溯到原始数据。

### 2.2 功能优先级

| 优先级 | 功能 | 交付要求 |
|---|---|---|
| P0 | 真实 POLYV 接入 | 绑定频道，实际 SDK/API 数据进入处理流程，明确显示连接状态 |
| P0 | 问题收集 | 中文文本，1—500 字，提交幂等，刷新后可恢复 |
| P0 | 在线语义聚类 | 一个问题归入一个疑问簇，保存原文和匹配依据 |
| P0 | 教师看板 | 疑问卡片、独立人数、等待时长、状态、原始问题 |
| P0 | 理解反馈 | 每人每轮一次有效反馈，可修改，不重复计数 |
| P0 | 人工纠错 | 可将误合并问题移到新簇；不得只依赖模型正确 |
| P0 | 课后报告 | 统计和未闭环清单，可打印，不依赖 LLM |
| P0 | 演示回放 | 使用标注的合成问题，经过同一处理流程 |
| P1 | 普通聊天识别 | 过滤非问题消息后聚类 |
| P1 | AI 标题和模糊匹配 | 严格结构化输出，有超时和降级 |
| P1 | AI 教学建议 | 结合真实统计生成带证据的建议 |
| P1 | 历史问答补偿 | 分页、去重、场次隔离，按实测限流执行 |

不纳入本次交付：语音转写、全自动答疑、知识库 RAG、多 Agent、向量数据库、原生后台插件、多端 App、跨校账号体系。

### 2.3 页面

**学生页 `/student/:sessionId`**：POLYV 观看区域、问题输入、自己的问题归属、讲解状态和反馈入口。默认只公开疑问簇摘要，不向学生展示其他人的原文或身份。

**教师页 `/teacher/:sessionId`**：优先级卡片列表、选中疑问的原文侧栏、开始讲解/结束讲解/关闭/重新打开、误合并纠正、接入状态。

**报告页 `/report/:sessionId`**：问题数、独立提问人数、疑问簇数、教师关闭情况、反馈覆盖情况、仍困惑清单。支持浏览器打印和 CSV 导出。

### 2.4 状态机

```text
open → addressing → awaiting_feedback → closed
  ↑                       │              │
  └───────────────────────┴──────────────┘
               教师重新打开
```

- `closed` 表示教师关闭，不代表所有学生已理解。
- 结束讲解时 `feedback_round += 1`，冻结本轮应反馈学生集合；进入 `awaiting_feedback`。
- 有人反馈仍困惑时显著提示，P0 不自动改教师状态。
- 关闭后又出现同义问题：建立新一轮疑问簇，可记录前一簇引用，避免历史人数和反馈污染当前处理。
- 重新打开的簇保留历史反馈；下次结束讲解再开新反馈轮。

## 3. 架构与技术栈

```mermaid
flowchart TD
    A[Vue 学生观看页] --> B[POLYV Web SDK]
    A --> C[FastAPI REST]
    D[Vue 教师看板] --> C
    B --> E[POLYV 事件适配器]
    E --> C
    F[服务端 POLYV HTTP 适配器] --> C
    G[标注的演示数据适配器] --> C
    C --> H[问题持久化与处理队列]
    H --> I[Embedding 与在线聚类]
    I --> J[MySQL]
    J --> K[REST 快照轮询]
    K --> A
    K --> D
    J --> L[统计报告 / 可选 LLM 建议]
```

| 部分 | 选择 | 约束 |
|---|---|---|
| 前端 | Vue 3、Vite、TypeScript、Vue Router | UI 组件沿用熟悉的库；图表可选 ECharts |
| 后端 | Python 3.11、FastAPI、Pydantic v2 | REST 写入与快照读取 |
| 数据 | MySQL 8、SQLAlchemy 2 Async、asyncmy、Alembic | utf8mb4、UTC、独立请求/任务 Session |
| AI | 本地中文字符 n-gram 语义哈希向量 | 无网络可复现；保留替换真实 Embedding 服务的接口 |
| 部署 | Docker Compose、单 Uvicorn Worker | 前端静态服务反代 `/api` 和 `/ws`，线上 HTTPS/WSS |

锁定经过验证的精确依赖版本并提交 lock 文件。MySQL 保存业务数据和向量 JSON；当前课堂簇数量较少，由 Python 做余弦相似度。无需专用向量数据库。

POLYV SDK 内部使用自己的实时连接；QuestionPulse 当前通过 REST 快照轮询更新业务状态，两者不能直接互换。不得为接入 FastAPI 改写 POLYV SDK 的底层协议。

## 4. POLYV 接入设计

### 4.1 官方参考

- 聊天室模块：https://help.polyv.net/live/js/new_sdk/live_watch_sdk/articles/modules/chat/overview/
- 互动接收端初始化：https://help.polyv.net/live/js/new_sdk/interactions_receive_sdk/sdk/overview/
- 问答模块：https://help.polyv.net/live/js/new_sdk/interactions_receive_sdk/sdk/question_answer/
- 问答列表：https://help.polyv.net/live/api/v4/chat/qa/qa_list/
- 原生提问产品：https://help.polyv.net/live/product/live_tools_basic/ask_question/
- AI 看：https://help.polyv.net/live/product/live_bgm/AI_watch/
- AI 答疑助手：https://help.polyv.net/zh-hant/live/product/live_bgm/AI_chat_bot_sdk/

这些链接用于开发前再次确认字段和版本，不是可直接执行的调用脚本。

### 4.2 接入验收门槛

取得联调授权后，先完成以下最小验证，再扩展业务：

1. 固定一套 SDK 版本，验证自定义页面能正确初始化对应频道。
2. 通过文档规定的后端授权接口获得所需短期 Token；仅向前端返回必要 Token，密钥始终在服务端。
3. 用两个受控测试观众确认消息 ID、用户 ID、场次 ID、时间和可见范围。
4. 确认“问答发送”产生的记录能否被“问答列表”读取；记录延迟与返回字段。
5. 确认公开聊天与私密提问的权限差异。普通观众连接不能假设看得到全班私密问题。
6. 确认额度、域名要求、限流、Token 到期处理和重连行为。

通过标准：一条真实 POLYV 消息有来源 ID，进入数据库，形成教师卡片；重复接收不会重复计数。仅嵌入播放器不等于题目数据接入已完成。

### 4.3 统一输入协议

```json
{
  "session_id": "本地课堂 UUID",
  "source": "polyv_qa",
  "external_id": "官方消息或问答 ID",
  "client_request_id": null,
  "participant_id": "服务端映射后的内部 ID",
  "content": "为什么递归需要终止条件？",
  "occurred_at": "2026-10-23T02:00:00Z"
}
```

`source`：`questionpulse`、`polyv_chat`、`polyv_qa`、`demo`。`participant_id` 必须由后端会话或可信适配器导出，不能信任浏览器任意填写的学生 ID。

前端转发 SDK 事件只能作为 Demo 数据桥接，不是可靠服务端事实来源：客户端可能断开、篡改或多次转发。使用教师受控桥接页面及教师认证，公开产品阶段优先升级为经验证的服务端读取或官方推送。

### 4.4 双写和去重

**避免把浏览器两次请求视为原子操作。** 如采用“先存本地，再发送 POLYV”的方式：

- 本地提交携带唯一 `client_request_id`，服务端幂等保存。
- 将 POLYV 同步标记为 `pending / succeeded / failed / uncertain`。
- 只有拿到官方确认及官方 ID 才记录映射；超时不等于发送失败，不能盲目自动重发。
- API 再次同步同一官方 ID 时关联本地记录，不再生成一条问题。
- 未能取得可靠 ID 映射时，P0 只启用一种权威题目输入路径，关闭另一条自动导入。文本相同和时间接近不能作为可靠跨来源去重键。

### 4.5 问答列表的使用

文档列出 `GET https://api.polyv.net/live/v4/chat/list-qa`，请求包含签名、频道与分页参数，结果包含问答 ID、`sessionId`、`viewerId`、状态、内容和回答。

- 签名按官方规则实现，不自行推测序列化方式。
- 此文档未证明支持增量游标或按场次筛选参数；根据返回 `sessionId` 本地筛选，处理完整分页。
- 轮询频率根据实测权限和官方限流设置；429/暂时失败退避，不写死“每秒轮询”。
- 当前场次无法确认时，不将记录自动分配给某个课堂。
- POLYV 的“已回复”保存在来源状态中，不自动映射为 QuestionPulse 的“学生已理解”。

## 5. 数据库设计

所有主键使用 UUID 字符串 `CHAR(36)`，外部消息 ID 使用字符串；时间使用 UTC `DATETIME(3)`；状态使用字符串＋应用校验。迁移通过 Alembic 管理，禁止启动时自动删表重建。

| 表 | 关键字段 |
|---|---|
| sessions | id、title、polyv_channel_id、polyv_session_id(nullable)、mode(live/demo)、status、created_at、ended_at |
| participants | id、session_id、viewer_key、display_name(nullable)、created_at |
| questions | id、session_id、participant_id、content、normalized_content、processing_status、cluster_id(nullable)、assignment_method、similarity(nullable)、embedding_json(nullable)、embedding_model、occurred_at、created_at、error_code(nullable) |
| question_sources | id、question_id、session_id、source、external_id、sync_status、created_at |
| submissions | id、session_id、participant_id、client_request_id、question_id、created_at |
| clusters | id、session_id、title、representative_question_id、status、feedback_round、version、related_cluster_id(nullable)、first_question_at、last_question_at、created_at、closed_at(nullable) |
| feedback_targets | cluster_id、round、participant_id、created_at |
| feedback | id、cluster_id、round、participant_id、result(understood/still_confused)、updated_at |
| cluster_events | id、session_id、cluster_id、actor_id、event_type、payload_json、created_at |
| reports | id、session_id、stats_json、suggestions_json(nullable)、model(nullable)、generated_at |

P0 一个问题只有一个当前簇，因此直接使用 `questions.cluster_id`，不再维护多余的多对多关联表。人工移动记录进入 `cluster_events`。

### 5.1 约束和索引

```text
participants          UNIQUE(session_id, viewer_key)
question_sources      UNIQUE(session_id, source, external_id)
submissions           UNIQUE(session_id, participant_id, client_request_id)
questions             INDEX(session_id, processing_status, created_at)
questions             INDEX(cluster_id, participant_id)
clusters              INDEX(session_id, status, last_question_at)
feedback_targets      PRIMARY KEY(cluster_id, round, participant_id)
feedback              UNIQUE(cluster_id, round, participant_id)
cluster_events        INDEX(session_id, created_at)
reports               INDEX(session_id, generated_at)
```

内部学生标识采用 `HMAC(secret, channelId + viewerId)` 映射，避免把原始账号 ID暴露给模型和其他学生；凭证不得进入日志。无平台身份的演示学生使用随机访客身份，报告明确其为“独立身份数”，不宣称真人去重。

影响人数通过 `COUNT(DISTINCT participant_id)` 计算，问题数通过 `COUNT(*)` 计算。MVP 不缓存这两个值，避免并发漂移。反馈率按本轮 targets 计算，未反馈不能记作已理解。

## 6. 自有 REST 接口

统一前缀 `/api/v1`。返回格式：`{"data": ..., "request_id": "..."}`；错误：`{"error":{"code":"...","message":"..."},"request_id":"..."}`。

| 方法与路径 | 权限 | 用途 |
|---|---|---|
| POST /auth/teacher | 教师口令 | 创建 HttpOnly 教师会话，限流 |
| POST /sessions/{id}/join | 课堂加入凭证 | 创建/绑定学生会话，不接受自选角色 |
| POST /sessions | 教师 | 创建本地课堂并绑定频道 |
| GET /sessions/{id} | 课堂成员 | 场次基本信息 |
| GET /sessions/{id}/snapshot | 课堂成员 | 按角色返回看板完整快照 |
| POST /sessions/{id}/questions | 学生 | 幂等提交，返回 202 与 question_id |
| GET /sessions/{id}/questions/mine | 学生 | 自己问题的处理结果 |
| GET /sessions/{id}/clusters/{cid}/questions | 教师 | 原始问题列表 |
| PATCH /sessions/{id}/clusters/{cid}/status | 教师 | 带 expected_version 的状态修改 |
| POST /sessions/{id}/questions/{qid}/detach | 教师 | 将误合并问题移入新簇 |
| PUT /sessions/{id}/clusters/{cid}/feedback | 学生 | 提交/修改当前轮反馈 |
| POST /sessions/{id}/end | 教师 | 结束本地课堂，不调用 POLYV 停播 |
| GET /sessions/{id}/report | 教师 | 读取统计报告 |
| POST /sessions/{id}/report/generate | 教师 | 生成报告，AI建议为可选 |
| POST /sessions/{id}/polyv/viewer-token | 课堂成员 | 后端校验频道绑定后取所需官方 Token |
| POST /sessions/{id}/integrations/polyv/events | 教师桥接 | 导入当前频道允许的事件 |
| GET /health/live | 无 | 进程存活 |
| GET /health/ready | 无敏感详情 | 数据库等必要依赖就绪 |

后端任何涉及 session、cluster、question 的操作都要验证归属关系，不能只验证“已登录”。`report/generate` 重复点击应复用正在执行的任务。

提交示例：

```json
{"client_request_id":"UUID","content":"递归什么时候停止？"}
```

状态修改示例：

```json
{"status":"awaiting_feedback","expected_version":3}
```

反馈示例：

```json
{"round":1,"result":"still_confused"}
```

主要错误：401 未登录、403 无权限、404 不存在或不可见、409 版本/状态/反馈轮冲突、422 参数错误、429 频率限制、503 集成暂不可用。后台细节写入脱敏日志，不直接回传。

## 7. 实时协议与恢复

地址：`/ws/sessions/{session_id}`。使用同源会话 Cookie，握手验证身份和课堂权限；校验 Origin。不要将长期密钥放入 URL。

```json
{
  "event_id":"UUID",
  "type":"cluster.updated",
  "session_id":"UUID",
  "entity_id":"UUID",
  "version":4,
  "occurred_at":"2026-10-23T02:00:01Z",
  "data":{"affected_student_count":3,"status":"open"}
}
```

事件：`question.processed`、`question.failed`、`cluster.created`、`cluster.updated`、`feedback.updated`、`session.ended`、`integration.status`。

- 数据库提交成功后才广播；不能先显示成功再保存。
- 学生只收自己的处理结果和可公开的簇摘要，原始问题只向教师广播。
- 页面初次打开和每次轮询均获取 REST snapshot；当前版本不实现 QuestionPulse 自有 WebSocket，也不承诺事件持久回放。
- 建立连接后先缓冲事件，再读取快照，应用快照后仅应用更高实体版本；忽略已见 event_id。
- 心跳与指数退避重连；前端显示“重连中”，恢复后不重复提交用户问题。
- 单 Worker 下使用内存连接管理器。多 Worker 会导致房间分裂，扩容时再接 Redis。

## 8. 聚类与 AI 设计

### 8.1 处理流水线

```text
校验与幂等 → 保存 pending → 入队 → 规范化 → Embedding
→ 当前场次候选匹配 → 自动归簇/新建簇 → 保存结果 → 提交事务 → 通知
```

学生通过“提问”入口提交的文本默认是问题，不需要模型再次否定。只有 P1 普通聊天导入需要问题识别。清洗保留“不、不是、不能”等否定词和代码内容。

### 8.2 候选和阈值

- 仅比较当前课堂、非关闭簇；不跨课堂复用向量。
- 每个簇用代表问题及最多 3 条成员样本作相似度参考，防止逐步合并导致主题漂移。
- 对单位归一化向量计算余弦相似度。
- 初始高/低阈值可用 0.82/0.68，但仅是待调参数；必须根据所选模型和标注集校准，不能当准确率承诺。
- 高相似且最高与次高候选有足够差距：归簇；低相似：新建；模糊或多簇接近：P1 调 LLM，P0 保守新建。
- “同一主题”不等于“同一个问题”。例如“什么是闭包”和“如何避免闭包内存泄漏”应可分开处理。
- 默认标题使用代表问题截断，P1 再异步生成简短标题；标题生成失败不得阻塞提问。

### 8.3 模型输出契约

模糊匹配只向模型提供脱敏问题和少量候选问题，不发送姓名、Token 或整场历史。学生内容始终视为数据，不能成为工具调用指令。

```json
{"decision":"merge","cluster_id":"候选集内的UUID","reason":"询问相同的停止条件"}
```

`decision` 只能为 `merge/new`；`merge` 的 ID 必须存在于当前候选集合；禁止让模型直接输出 SQL 或操作数据库。JSON 校验失败、超时或不确定时创建新簇。

### 8.4 故障与并发

- API 接受后即返回 202，不让学生等待外部模型。
- 单 Worker 内维护有界异步队列；保存 pending 后尝试入队，队列满时由扫描器补入。
- 启动时恢复 pending 及超过租约时间的 processing 任务；完成前再次检查处理状态，避免重复归簇。
- 外部模型调用不持有数据库事务。先生成向量，再在每课堂的锁内检查最新候选和提交簇更新，避免两个并发同义问题各建一簇。
- 每个后台任务创建独立 AsyncSession，不跨任务共享 ORM Session。
- 模型不可用时用中文字符 n-gram TF-IDF 作降级，阈值独立校准；无法可靠匹配就新建簇，界面标记降级状态。
- 建议初始配置：Embedding 超时 5 秒、LLM 超时 8 秒、最多一次带退避重试；上线前按实测调整。

### 8.5 优先级和统计语义

MVP 使用可解释启发式，不宣称学习效果预测：

```text
priority = 5 × 独立提问人数
         + min(最早未处理等待分钟数, 10)
         + 3 × 当前轮仍困惑人数
```

关闭簇不参加排序；同分按最早问题优先。前端同时显示三个原始量，避免只给不可解释分数。数值是产品初始配置，不是经过科学验证的指标。

课后报告区分：教师关闭率、反馈覆盖率、已反馈学生的理解率。所有比例显示分母；零分母显示“暂无数据”。“3/5 已反馈者理解”不能写成“全班理解率 60%”。

### 8.6 Agent 范围

P0 生成确定性统计报告。P1 用一次结构化模型调用生成教学建议，附 cluster_id 证据引用，称为“AI复盘助手”。只有确实实现模型工具选择与调用后才称 Agent；不得把普通提示词函数包装成自主 Agent 的完成成果。

## 9. 目录与配置

```text
questionpulse/
  frontend/src/
    pages/          StudentPage、TeacherPage、ReportPage
    components/     ClusterCard、QuestionList、FeedbackPanel
    services/       api、websocket、polyv
    stores/         session、clusters
  backend/
    app/
      api/          auth、sessions、questions、clusters、reports
      models/       SQLAlchemy 表
      schemas/      Pydantic 请求响应
      integrations/polyv/  signing、client、mapping
      services/     ingestion、clustering、feedback、reporting
      ai/           embedding、matching、prompts
      realtime/     manager、events
      workers/      processor、recovery
      core/         config、auth、logging
      main.py
    migrations/
    tests/
  fixtures/         合成演示数据与标注集
  docs/
  compose.yaml
  .env.example
```

`.env.example` 仅包含占位值：

```dotenv
APP_ENV=development
DATABASE_URL=mysql+asyncmy://questionpulse:CHANGE_ME@mysql:3306/questionpulse
APP_SESSION_SECRET=CHANGE_ME
VIEWER_HASH_SECRET=CHANGE_ME
TEACHER_PASSWORD_HASH=CHANGE_ME
POLYV_APP_ID=
POLYV_APP_SECRET=
EMBEDDING_BASE_URL=
EMBEDDING_API_KEY=
EMBEDDING_MODEL=
LLM_BASE_URL=
LLM_API_KEY=
LLM_MODEL=
DEMO_MODE=true
```

SDK 包名、Token 字段和签名细节在接入验证后固定，不能凭旧版示例直接混用。真实 `.env` 不进入版本库。MySQL 不暴露公网端口，应用容器连接内部网络。

## 10. 开发任务与排期

### 准备期

| 时间 | 工作 | 产物 |
|---|---|---|
| 准备第1天 | 规则确认、环境检查、SDK文档与身份模型、获授权后最小接入验证 | 兼容版本表、权限记录、实际消息字段样本（脱敏） |
| 准备第2天 | 页面线框、接口契约、合成题集、模型和阈值评估、部署验证 | 设计稿、评测结果、可复现环境说明 |

赛前代码是否可带入由规则决定。没有确认前，不把完整业务实现作为默认准备任务。

### 正式开发窗口：约16小时有效工作＋8小时休息/缓冲

| 工作预算 | 任务 | 退出条件 |
|---|---|---|
| 0—2h | 工程、数据库迁移、基础会话和权限 | 前后端连接数据库，学生无法调用教师操作 |
| 2—5h | 一条真实 POLYV 输入链路、幂等入库、处理队列 | 真实来源问题能显示，重复消息只计一次 |
| 5—8h | Embedding 聚类、教师卡片、REST 快照刷新 | 不同表达归簇，刷新后恢复 |
| 8—10h | 状态机、反馈轮、人工拆分 | 讲解—反馈—再次处理闭环 |
| 10—12h | 统计报告、演示回放、故障降级 | 无模型仍可演示全流程 |
| 12—14h | 权限/并发/幂等验收、部署 | 新环境启动、关键用例通过 |
| 14—16h | 视觉打磨、录屏、答辩演练 | 3分钟演示完整且数据诚实 |

第5小时真实接入仍未通过：停止扩展AI，集中解决官方接入；模拟数据不能替代参赛要求。第10小时闭环未完成：取消全部P1。最后4小时冻结新增功能，只修复、部署和演示。

## 11. 验收清单

| 用例 | 预期 |
|---|---|
| 两名学生各提一个同义问题 | 同簇、问题数2、独立人数2 |
| 同一学生重复表述 | 可有多条问题，人数仍为1 |
| 重试相同 client_request_id | 同一个 question_id，不重复计数 |
| 相同外部 ID 多次导入 | 只有一条来源记录 |
| 两个并发同义问题 | 聚类提交串行化，不因竞态多建簇 |
| 不同场次同一问题 | 绝不跨场次聚合 |
| 同主题但不同疑问 | 标注集中检查误合并，可人工拆分 |
| 学生调用教师状态接口 | 403 |
| 修改 URL 访问别的课堂 | 不泄露问题或报告 |
| 教师结束讲解 | 固定本轮目标人群、开启反馈 |
| 学生重复/修改反馈 | 一条有效反馈，不累加次数 |
| 提交旧反馈轮次 | 409，不污染当前轮 |
| 未反馈学生 | 不计为已理解 |
| 模型超时/非法JSON | 问题仍保留，进入降级路径 |
| 刷新/断线/进程重启 | 快照恢复，pending问题可继续处理 |
| POLYV发送结果不确定 | 标记 uncertain，不盲目重发 |
| 公开学生页面 | 不展示其他学生原文、身份或密钥 |
| 演示数据模式 | 显示“合成数据演示”，与真实场次隔离 |

自动化测试优先覆盖幂等、授权、状态迁移、反馈分母、并发归簇。SDK真实接入用脱敏的人工联调记录佐证，不把 mock 测试视为账号验证。

质量目标（验收时实测，不先宣称达到）：准备约60条合成问题、8—12个疑问主题，包含闲聊、否定句、同词不同意图和重复提交。固定一部分为保留集，报告成对聚类 precision/recall、误合并示例、处理延迟与模型成本。不得只展示挑选出来的成功样本。

## 12. 演示与交付

建议演示顺序：

1. 展示一个已连接 POLYV 的课堂，两名真实测试观众提交问题。
2. 启动明确标注的合成问题回放，教师看板把重复表述聚为疑问簇。
3. 展示人数去重和优先级变化，教师进入讲解状态。
4. 学生分别选择已理解、仍困惑，看板保留未闭环提示。
5. 展示原始证据与课后清单，说明模型降级和人工纠错。

交付包：源码与依赖锁、`.env.example`、迁移、启动说明、脱敏联调记录、测试结果、合成数据、3分钟演示视频、比赛要求的海报/材料。正式提交格式仍以主办方细则为准。

Definition of Done：真实 POLYV 接入通过；P0验收完成；无密钥提交；可按README在新环境启动；真实与演示数据明确区分；报告没有夸大理解率或模型准确率；现场演示可在模型异常时完成业务闭环。
