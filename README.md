# ehentai_favorites_downloaderRERE

`ehentai_favorites_downloaderRERE`（简称 `EFDRR`）是一个面向 E-Hentai / ExHentai 收藏夹管理与下载的前后端分离项目。它把“收藏夹同步、手动补链、下载队列、实时进度、通知提醒、运行配置”整合到了同一套控制台里。

## 核心功能

- 收藏夹增量同步与失败重试
- `archive` / `native_crawl` 两种下载模式
- `native_crawl` 断点补抓、部分完成和启动恢复
- 手动补链，自动识别新版 `gid`
- 可选后台登录保护
- Telegram Bot 与主动提醒
- `SSE` 实时下载状态推送
- 自定义输出路径/文件名模板
- 旧残留检查、清理与联调前自检

## 仓库结构

- `backend/`：FastAPI 后端、下载器、同步器、数据库、Bot、通知和配置
- `frontend/`：React + Vite 控制台界面
- `deploy/`：统一入口反向代理配置
- `docker-compose.yml.example`：整套部署示例

## 快速开始

### 方式一：本地开发运行

后端：

```powershell
cd backend
Copy-Item config.yaml.example config.yaml
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

前端：

```powershell
cd frontend
npm install
npm run dev
```

前端默认使用同源 `/api/v1`。如果你需要直连其他后端地址，可以自行设置：

```powershell
$env:VITE_API_BASE_URL="http://localhost:8000/api/v1"
```

### 方式二：Docker Compose 部署

1. 复制配置模板：

```powershell
Copy-Item .\backend\config.yaml.example .\backend\config.yaml
```

2. 复制部署示例并按需修改：

```powershell
Copy-Item .\docker-compose.yml.example .\docker-compose.yml
```

3. 启动：

```powershell
docker compose up -d --build
```

默认对外暴露：

- `http://localhost:8080`

说明：

- 对外只开放 `nginx` 一个端口
- 前端通过同源 `/api/v1` 访问后端
- `backend/config.yaml`、`backend/data/`、`backend/downloads/` 都通过宿主机绑定卷持久化

## 文档索引

- 根目录项目说明：当前文件
- 后端说明：[backend/README.md](./backend/README.md)
- 前端说明：[frontend/README.md](./frontend/README.md)
- 后端 API 文档：[backend/docs/README.md](./backend/docs/README.md)

## 运行与安全建议

- `backend/config.yaml` 可能包含真实 Cookies / Token，请不要上传到公开仓库
- 如果对外部署，建议开启 `security.enable_auth`
- 如果通过同域反代部署前后端，浏览器通常不需要跨域访问后端
- `Telegram Bot` 建议始终限制 `allowed_ids`

## 当前前端如何连接后端

当前前端连接策略如下：

- 默认：使用同源 `/api/v1`
- 可覆盖：通过 `VITE_API_BASE_URL` 指定其他后端地址

这意味着：

- 在反向代理部署下，不需要额外暴露后端端口给浏览器
- 在本地开发或跨域调试时，仍然可以手动指定后端地址
