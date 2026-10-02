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

### Windows 桌面版

从 Gitea Release 下载 `EFDRR-版本号-windows-x64.zip`，完整解压后运行 `EFDRR.exe`。
需要 Windows 10/11 x64 和 Microsoft Edge WebView2 Runtime，无需安装 Python 或 Node.js。
首次启动显示管理员登录信息，配置、数据库和默认下载目录位于程序旁。
关闭窗口时可选择退出或进入托盘；升级前退出程序并保留 `config.yaml`、`data/` 和 `downloads/`。

### 方式一：本地开发运行

后端：

```bash
cd backend
cp config.yaml.example config.yaml
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

前端：

```bash
cd frontend
npm install
npm run dev
```

前端默认使用同源 `/api/v1`。如果你需要直连其他后端地址，可以自行设置：

```bash
export VITE_API_BASE_URL="http://localhost:8000/api/v1"
```

### 方式二：Docker Compose 部署

1. 复制配置模板：

```bash
cp ./backend/config.yaml.example ./backend/config.yaml
```

2. 复制部署示例并按需修改：

```bash
cp ./docker-compose.yml.example ./docker-compose.yml
```

3. 启动：

```bash
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


## 版本与发布

根目录 VERSION 是唯一手工维护的应用版本来源。

```bash
python scripts/version.py check
python scripts/version.py patch
```

开发分支与 PR 在 Gitea 的 ubuntu-latest Runner 上运行后端、前端和浏览器测试，并生成 Windows 候选包。
VERSION 合入 master 后自动生成同名 v 标签和正式 Release。附件上传完整后才公开发布；失败的上传保留为草稿，允许重跑。
使用 Gitea 内置 GITEA_TOKEN，无需在仓库中保存个人令牌。

Ubuntu 构建工具需要 Python 3.13、Node.js 24、uv 0.12.10、MinGW-w64、setuptools 和 wheel。

```bash
python desktop/build.py
python scripts/validate_package.py dist/EFDRR-1.0.0-windows-x64.zip
```

## 验证与开发

```bash
python -m pip install -r backend/requirements.txt -r backend/requirements-dev.txt
python -m pytest -q
cd frontend
npm ci
npm run lint
npm test
npm run build
npx playwright install chromium
npm run test:e2e
```

后端 requirements.in 记录直接依赖，requirements.txt 锁定完整依赖与哈希。
桌面依赖由 desktop/requirements.in 生成 desktop/requirements-windows.lock，按 Windows x64 和 Python 3.13 解析。
更新依赖后应重新运行测试并生成两个锁文件：

```bash
uv pip compile backend/requirements.in --python-version 3.13 --universal --generate-hashes -o backend/requirements.txt
uv pip compile desktop/requirements.in --python-version 3.13 --python-platform x86_64-pc-windows-msvc --generate-hashes -o desktop/requirements-windows.lock
```

真实账号联调脚本为 scripts/live_acceptance.py，必须显式指定测试样本，读取本机 .env 的 Cookie。
脚本使用独立数据目录，并在归档提交前校验报价；累计 GP 上限为 10,000，未知报价或 Credits 请求会被拒绝。
.env、实际配置、测试下载及日志不进入 Git、Docker 构建上下文或发布包。
