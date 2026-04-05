# ehentai_favorites_downloaderRERE Backend

后端基于 `FastAPI + SQLAlchemy + SQLite`，负责同步收藏夹、下载画廊、维护运行状态、提供 Telegram Bot 与通知能力，并向前端输出 REST API 与 SSE 实时事件。

## 主要功能

- 收藏夹增量同步与失败重试
- `archive` / `native_crawl` 两种下载方式
- `native_crawl` 断点补抓、部分完成、启动恢复
- 手动补链与新版 `gid` 自动跟进
- Telegram Bot、主动通知、批量聚合、静默时段
- SSE 实时进度推送
- 本地 `config.yaml` 配置管理

## 目录说明

- `app/`：核心应用代码
- `scripts/`：维护、自检和清理脚本
- `docs/`：后端 API 文档
- `config.yaml.example`：配置模板

## 配置方式

后端只使用 `config.yaml` 作为主配置源。

首次使用：

```powershell
cd backend
Copy-Item config.yaml.example config.yaml
```

重点配置项：

- `security.*`：鉴权、管理员、CORS
- `auth.*`：EH / ExH Cookies
- `download.*`：下载模式、质量、命名模板、冲突策略
- `sync.*`：监控收藏夹、时间过滤、自动同步
- `telegram.*`：Bot、提醒、静默时段

## 本地启动

```powershell
cd backend
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

默认地址：

- API：`http://localhost:8000/api/v1`
- OpenAPI JSON：`http://localhost:8000/api/v1/openapi.json`
- Swagger UI：`http://localhost:8000/docs`

## 部署说明

### 通过反向代理部署

推荐做法：

- 后端只监听内网或容器网络
- 对外只暴露一个反向代理端口
- 前端默认走同源 `/api/v1`
- `SSE` 代理时关闭缓冲

### Docker 镜像

仓库已提供：

- [Dockerfile](./Dockerfile)
- 根目录 [docker-compose.yml.example](../docker-compose.yml.example)

容器内路径约定：

- `/app/config.yaml`
- `/app/data`
- `/app/downloads`

## 运行维护

### 自检

```powershell
python scripts/preflight_check.py
python scripts/preflight_check.py --json
```

### 清理遗留状态

```powershell
python scripts/cleanup_legacy_state.py
python scripts/cleanup_legacy_state.py --all
```

## API 文档

后端接口文档位于：

- [docs/README.md](./docs/README.md)
- [docs/rest-api.md](./docs/rest-api.md)
- [docs/sse.md](./docs/sse.md)

## 上传到 Git 前的注意事项

不要提交这些本地文件：

- `config.yaml`
- `data/`
- `downloads/`
- 日志文件

根目录 `.gitignore` 已经包含这些规则，但上传前仍建议再检查一次工作区。
