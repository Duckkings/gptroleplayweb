# Docker 开发模式（建议）

> 适用于：你不想在宿主机装 Python 环境，只想用 Docker 一键拉起前后端。

## 启动

在仓库根目录执行：

```bash
docker compose -f docker-compose.dev.yml up --build
```

- 前端（Vite）：http://localhost:5173
- 后端（FastAPI）：http://localhost:8000

## 说明

- 前端通过 Vite proxy 把 `/api` 转发到后端。
- 多用户模式下配置与存档按账号隔离，落在：
  - `data/users/<username>/config.json`
  - `data/users/<username>/current-save.json`

## 常见问题

### 1) Windows 文件监听不灵

可以在 `docker-compose.dev.yml` 的 `frontend.environment` 里加：

- `CHOKIDAR_USEPOLLING=true`

### 2) 端口冲突

修改 `docker-compose.dev.yml` 的端口映射即可。
