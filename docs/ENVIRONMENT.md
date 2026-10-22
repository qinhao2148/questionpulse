# 开发环境记录

更新日期：2026-10-19

## 已检测环境

| 工具 | 状态 | 版本/说明 |
|---|---|---|
| Node.js | 已安装 | 22.23.1，路径 `D:\node\node.exe` |
| npm | 已安装 | 9.6.6 |
| pnpm | 已安装 | 11.25.0 |
| Git | 已安装 | 2.52.0.windows.1 |
| Python | 多版本 | 项目固定使用 `uv` 提供的 CPython 3.11；默认 `python` 是 Conda 3.8，不使用 |
| uv | 已安装 | 0.11.32 |
| Docker CLI | 已安装 | 29.6.2 |
| Docker Compose | 已安装 | 5.3.1 |
| Docker Desktop | 已安装并运行 | Docker Engine 29.6.2，已完成容器验证 |
| MySQL | 已安装并运行 | MySQL 8.0.33，本机占用 3306；不改动其现有数据 |

项目 Docker MySQL 映射到主机 `3307`，避免与本机 MySQL 3306 冲突。

## 当前验证结果

- 前端类型检查通过，Vite 生产构建通过。
- FastAPI 静态检查通过，基础测试通过。
- MySQL 8.0.41 容器健康，映射端口为 3307。
- Alembic 已升级到 `20261020_0006`，包含课堂闭环、接入契约与可靠性字段。
- `/api/v1/health/live` 与 `/api/v1/health/ready` 均已实际返回成功。
- 前端开发服务器已实际返回 HTTP 200，并能通过 API 检查后端状态。

## 第一次准备

在项目根目录执行：

```powershell
./scripts/bootstrap.ps1
docker compose up -d mysql
Set-Location backend
uv run alembic upgrade head
```

分别启动服务：

```powershell
./scripts/start-backend.ps1
./scripts/start-frontend.ps1
```

访问：

- 前端：http://127.0.0.1:5173
- 后端文档：http://127.0.0.1:8000/docs
- 存活检查：http://127.0.0.1:8000/api/v1/health/live
- 数据库就绪检查：http://127.0.0.1:8000/api/v1/health/ready

运行全部检查：

```powershell
./scripts/check.ps1
```

`.env` 是本地配置且已被 Git 忽略。POLYV 和模型密钥只能写入 `.env`，不得写进前端源码或提交记录。

