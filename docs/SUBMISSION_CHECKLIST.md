# 最终提交清单

## 必交成果

- [x] 项目源码与 README
- [x] 数据库迁移、测试和启动脚本
- [x] 学生端、教师端和课后报告页
- [x] 参赛海报 `assets/submission/questionpulse-team-poster-ray-v7.png`
- [x] 三分钟路演脚本
- [x] 真实 POLYV SDK 提问、服务端同步和官方 ID 去重验收记录
- [ ] 按赛事表单要求上传最终文件
- [ ] 录制 2—3 分钟备份演示视频

## 现场前检查

- [ ] Docker Desktop 已启动，MySQL 健康
- [ ] 执行 `./scripts/check.ps1`
- [ ] 执行 `./scripts/start-demo.ps1` 并保存输出的三个地址
- [ ] 使用无痕窗口分别打开学生端和教师端
- [ ] 演示一次接入降级与恢复
- [ ] 演示完成后执行 `./scripts/stop-demo.ps1`

## 数据口径

- `demo / not_configured`：本地演示数据，未连接 POLYV。
- `demo / contract_verified`：本地契约和去重验证通过，仍未读取真实账号。
- `live / connected`：仅在正式凭据成功读取官方问题后使用。

## 安全检查

- `.env` 不进入压缩包。
- App Secret、数据库密码和 API Key 不出现在源码、海报、录屏或终端输出中。
- 前端不保存 POLYV 签名密钥。
- 演示数据不得表述为真实用户数据。
