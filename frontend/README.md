# ehentai_favorites_downloaderRERE Frontend

前端控制台基于 `React + Vite + shadcn/ui + Tailwind CSS 4`，负责提供下载任务中心、仪表盘、系统设置、登录和实时状态展示。

## 主要页面

- 仪表盘：查看下载服务、同步状态、活跃任务和账户余额
- 任务中心：分页查看所有画廊、日志、进度、重试与删除
- 系统设置：管理 Cookies、同步规则、下载策略、Telegram 与维护项
- 登录页：当后端开启鉴权时使用

## 前端如何连接后端

默认情况下，前端会请求同源：

- `/api/v1`

这适合：

- 使用 Nginx / Caddy 等反代后只暴露一个端口
- Docker Compose 中通过统一网关部署

如果你想手动指定后端地址，可以在启动或构建前设置：

```bash
export VITE_API_BASE_URL="http://localhost:8000/api/v1"
```

## 本地开发

```bash
cd frontend
npm install
npm run dev
```

常用命令：

```bash
npm run lint
npm run build
```

## Docker 构建

仓库已提供：

- [Dockerfile](./Dockerfile)
- [nginx.conf](./nginx.conf)

该镜像会：

1. 先使用 Node 构建静态资源
2. 再使用轻量 Nginx 容器提供前端页面

## 与后端鉴权配合方式

如果后端开启 `security.enable_auth`：

- 前端会先进入登录页
- 登录成功后将 Bearer Token 存入浏览器本地存储
- 后端返回 `401` 时会自动清空令牌并回到未登录状态

## 发布建议

- 生产环境建议通过根目录 `docker-compose.yml.example` 搭配统一网关部署
- 不建议直接暴露 Vite 开发服务器端口
- 如果需要直连调试后端，可通过 `VITE_API_BASE_URL` 手动覆盖

更完整的项目说明见仓库根目录的 [README.md](../README.md)。

开发服务器自动将 /api 请求代理到 http://127.0.0.1:8000。
界面版本由根目录 VERSION 在构建时注入。
单元测试运行 npm test，浏览器测试运行 npm run test:e2e。
Docker 构建需以仓库根目录为上下文：docker build -f frontend/Dockerfile .
