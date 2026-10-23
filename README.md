# QuestionPulse

POLYV 直播课堂疑问聚合与解决追踪工具。

当前阶段：本地业务闭环和真实 POLYV 接入均已完成。学生端使用官方观看页 SDK 连接测试频道并发送提问，FastAPI 服务端通过官方签名 API 读取提问、保存官方 ID 并幂等去重；2026-10-23 已在频道 `8655930` 上完成真实问题、DeepSeek 聚类、教师处理、定向检测和报告统计的端到端验收。

## 目录

```text
heikeson/
├─ frontend/                     Vue 3 + TypeScript 前端
├─ polyv-watch-client/           保利威官方观看端源码（v2.20.0）及 QuestionPulse 定制
├─ extension/                    POLYV 网页开播台教师悬浮助手
├─ backend/                      FastAPI + SQLAlchemy 后端
├─ scripts/                      环境准备、启动与检查脚本
├─ docs/                         项目与开发文档
├─ assets/competition/           比赛原始资料与可读切片
├─ archive/                      暂不使用但保留的生成文件
├─ compose.yaml                  隔离的 MySQL 8 开发服务
├─ .env.example                  本地配置模板
└─ README.md                     项目入口
```

- [开发指南](docs/DEVELOPMENT.md)：产品范围、接入边界、技术架构、数据表、REST 接口、实时协议、AI 流程、排期和验收。
- [开发环境](docs/ENVIRONMENT.md)：已检测版本、初始化、启动和检查命令。
- [接口契约](docs/API_CONTRACT.md)：前后端对象、HTTP、实时事件与验收样例。
- [POLYV 接入映射](docs/POLYV_INTEGRATION.md)：字段、权限边界、真实联调门槛与降级策略。
- [定制观看端与聊天疑问链路](docs/POLYV_DIY_CHAT_PIPELINE.md)：实时上报、DeepSeek 判疑、服务端补偿、理解反馈与答题闭环。
- [聚类基线](docs/CLUSTERING_BASELINE.md)：数据划分、复现方式、指标解释与模型路线。
- [开发与验收清单](docs/IMPLEMENTATION_CHECKLIST.md)：24 小时执行顺序和端到端验收场景。
- [0—5 小时开发成果](docs/LOCAL_QUESTION_PIPELINE.md)：本地持久化、语义聚类、演示数据和已知边界。
- [5—12 小时开发成果](docs/FEEDBACK_REPORT_LOOP.md)：教师状态机、学生反馈约束、事实报告和验收证据。
- [P0 演示强化](docs/P0_HARDENING.md)：按题拆分、失败重试、课堂终态、适配器边界与故障演练。
- [POLYV 接入契约阶段](docs/POLYV_CONTRACT_STAGE.md)：官方标识映射、数据库去重、本地契约验证和报告导出。
- [可靠性与响应式阶段](docs/RELIABILITY_STAGE.md)：就绪检查、断连降级、批量恢复和多尺寸验收。
- [三分钟路演稿](docs/PITCH_SCRIPT.md)：问题、方案、演示节奏与评委追问口径。
- [最终提交清单](docs/SUBMISSION_CHECKLIST.md)：现场检查、数据口径和安全检查。
- [明日人工验收清单](docs/TOMORROW_VALIDATION.md)：Edge、真实推流、结束课堂与新课堂流程。
- [功能与状态逻辑审计](docs/FUNCTIONAL_AUDIT.md)：课堂状态机、播放器生命周期、只读归档和验证范围。
- [项目总览](docs/PROJECT_OVERVIEW.md)：当前事实、架构、完成度、风险和比赛演示顺序。
- [V2 教师悬浮助手与 DeepSeek 路线](docs/V2_TEACHER_COPILOT.md)：下一阶段产品定义、架构、数据边界和实施顺序。
- [获奖导向优化路线](docs/AWARD_OPTIMIZATION_ROADMAP.md)：功能收益排序、即时检测闭环、困惑预警和停止线。
- [真实环境升级总方案](docs/REAL_WORLD_UPGRADE_PLAN.md)：角色、权限、悬浮助手、DeepSeek、即时检测、部署和验收的统一实施基线。
- [真实环境升级实施状态](docs/IMPLEMENTATION_STATUS.md)：已实现能力、自动验收结果和仍需真人执行的真实环境检查。
- [V1 冻结回退点](docs/V1_ROLLBACK.md)：现有未改动提交包的校验值、版本边界和隔离回退方法。
- [比赛资料说明](assets/competition/README.md)：海报原件、切片目录与已确认规则。
- [归档说明](archive/README.md)：重复切片等可恢复文件。

当前技术实现：Vue 3 + TypeScript、FastAPI、MySQL 8、SQLAlchemy Async、REST 快照轮询、DeepSeek 结构化语义分析与本地降级；`polyv-watch-client` 基于保利威官方 `polyv-web-live-watch-sdk` v2.20.0 源码进行本地定制，官方 SDK 继续负责直播与聊天实时连接。

学生加入课堂后会跳转到本地定制观看端。普通公聊发送成功后，观看端将该学生自己的消息和官方消息 ID 上报 QuestionPulse；后端使用 DeepSeek 判断是否为课程疑问，高置信度自动进入疑问聚类，中等置信度进入教师审核区。教师点击“同步聊天与提问”时，后端还会通过保利威签名 API 拉取聊天历史，补偿浏览器断线期间遗漏的消息。讲解结束后，观看端内的 QuestionPulse 面板会显示“已理解/仍困惑”和教师发布的理解检测题。

首次运行先执行 `./scripts/bootstrap.ps1`。配置 `.env` 中的 POLYV 凭据后，`./scripts/start-demo.ps1` 会同时启动 FastAPI（8000）、教师前端（5173）和定制观看端（15021）。教师端“同步聊天与提问”会发起真实服务端调用；`appSecret` 只保存在后端，绝不进入观看端。没有凭据或接口异常时保留本地演示闭环并明确显示降级状态。

保利威源码的再发布和闭源使用须遵守 `polyv-watch-client/LICENSE`：保利威客户适用其商业授权，其他情况适用 GPLv2。上线前应由账号所有方确认客户资格和品牌/域名配置。

比赛现场可直接运行：

```powershell
./scripts/start-demo.ps1   # 启动 MySQL、迁移、前后端并创建新课堂
./scripts/open-demo-teacher.ps1 # 打开教师登录页
./scripts/reset-demo.ps1   # 保留旧证据并创建一间全新演示课堂
./scripts/stop-demo.ps1    # 关闭前后端，MySQL 保持运行
```
