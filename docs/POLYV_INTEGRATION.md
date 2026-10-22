# POLYV 接入与字段映射

状态：2026-10-21 已完成真实 API、SDK 和端到端验收；2026-10-22 当前直播演示频道为 `8645366`。学生端已发送一条真实问题；服务端首轮同步 `fetched=1 / accepted=1`，第二轮同步 `fetched=1 / duplicates=1 / accepted=0`。课堂快照为 `live / connected`，问题带 `source=polyv_ask` 和官方 `external_id`。

账号与场次核对：AppID/AppSecret 鉴权有效；频道为测试频道“测试1”。官方频道场次接口 `GET /live/v3/channel/session/data/list` 返回成功且最近 60 天 `totalItems=0`，真实提问记录的 `sessionId` 也为空。因此本次验收按频道绑定，未伪造或硬编码场次 ID；正式开播产生场次后可把返回的 `sessionId` 写入 `POLYV_SESSION_ID` 进行场次隔离。

## 已实现的真实链路

- 后端 `POST /sessions/{id}/integrations/polyv/sync` 通过 HTTPS 同时读取官方新版问答列表 `GET /live/v4/chat/list-qa` 和观看页 SDK 对应的提问记录 `GET /live/v2/chat/{channelId}/getQuestion`。
- 签名按官方规则在服务端生成：过滤空值、参数名 ASCII 升序、首尾拼 AppSecret、UTF-8 MD5 大写。
- 新版响应的 `id / viewerId / content / timestamp` 与传统提问响应的 `id / user.userId / content / time` 均映射到统一问题模型；只导入 `S_QUESTION`，按课堂、来源和官方 ID 去重。
- 成功后课堂标记为 `live / connected`；鉴权或网络错误标记为 `not_configured / degraded`，本地课堂闭环仍可用。
- 前端已安装 `@polyv/live-watch-sdk@2.20.0` 和 `@polyv/interactions-receive-sdk@0.24.0`。学生端按官方流程执行 `createWatchCore → setup → verifyNoneAuth → connect → setupPlayer → setupIarCore`，通过 `watchCore.ask.sendAskSpeak` 发送问题，并展示连接或降级状态；`services/polyvSdk.ts` 另保留 `updateConfig + QuestionAnswer` 的直接接入边界。
- 真实 SDK 验收：观看授权、聊天室连接、播放器、互动模块和提问发送均已成功；当前演示频道为 `8645366`。内置浏览器学生端能够显示直播，Edge 兼容性仍按人工验收清单复核。

本机已确认 AppID 和可用测试频道，但 AppSecret 只放在 `.env` 的 `POLYV_APP_SECRET`，不得复制到前端、文档、日志或提交包。

## 接入边界

QuestionPulse 需要 POLYV 提供课堂载体和至少一条可验证的问题输入链路。优先顺序为：官方问答读取/事件 → 教师受控 SDK 事件桥接 → 标注演示数据。播放器嵌入只能证明能观看直播，不能证明问题数据已经接入。

正式联调时只选择一条权威输入路径，直到官方 ID 去重验证通过；不同时导入聊天和问答后再凭文本猜测去重。

## 规范化字段

| QuestionPulse | 候选 POLYV 含义 | 处理规则 |
|---|---|---|
| `session_id` | 本地课堂与频道/场次绑定 | 服务端配置，不接受客户端覆盖 |
| `source` | `polyv_qa` 或 `polyv_ask` | 新版问答与观看页提问分别标记，由适配器常量写入 |
| `external_id` | 官方问答/消息唯一 ID | 原样存为字符串；与 source 组成唯一键 |
| `participant_id` | viewer/user 标识 | 服务端 HMAC 映射，原始标识不进入 AI 输入 |
| `content` | 问题或消息正文 | 保留原文；另存规范化文本 |
| `occurred_at` | 官方创建/发送时间 | 转成 UTC；缺失时标记来源异常，不伪造业务时间 |
| `polyv_session_id` | 官方直播场次标识 | 用于隔离不同场直播，不能只按频道聚合 |
| `source_status` | 官方已回复等状态 | 单独保存，不映射成“学生已理解” |

## 已完成的真实验收

- 官方 SDK 在测试频道发送问题后，传统提问接口返回同一条记录。
- 首轮同步导入 1 条，生成教师疑问卡并保存官方 ID。
- 第二轮同步识别 1 条重复记录，数据库问题数不增加。
- 课堂从 `demo / not_configured` 切换为 `live / connected`，错误字段清空。
- AppSecret 只存在本机 `.env`，敏感扫描和提交包清单均不包含 `.env`。

官方依据：[签名规则](https://help.polyv.net/live/api/buildSign/)、[新版问答列表](https://help.polyv.net/live/api/v4/chat/qa/qa_list/)、[传统提问记录](https://help.polyv.net/live/api/live_interaction/get_question_list/)、[观看页 SDK 初始化](https://help.polyv.net/live/js/new_sdk/live_watch_sdk/articles/product/fast-start/)。

## 后续扩展验证

- 固定 SDK 与文档版本，记录验证日期。
- 后端生成短期 Token；App Secret、签名材料不下发浏览器、不写日志。
- 两个受控观众各发送一条问题，记录 ID、用户、场次、时间、可见范围和延迟。
- 多页数据和大量历史记录下验证完整分页。
- 断网重连和 Token 过期后恢复，不制造重复问题。
- 普通观众不能读取其他人的私密问题；教师页面权限单独验证。
- 记录限流、域名白名单、回调或轮询条件以及失败退避方式。

通过门槛已经满足：一条真实问题带官方来源 ID 进入 QuestionPulse，形成教师疑问卡；重复接收没有重复计数。任何字段与此表不一致时，以届时官方文档和实测响应为准，并更新本文件。

## 降级策略

若比赛账号权限无法读取问答，演示模式仍通过同一个 `NormalizedQuestion` 适配器和处理队列运行，并在界面清楚标注“演示数据”。不得把合成数据呈现为 POLYV 实时数据。
