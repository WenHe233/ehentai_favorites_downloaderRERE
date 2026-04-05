# EFDRR 后端 API 文档

这里存放 `ehentai_favorites_downloaderRERE` 后端接口说明，面向部署者、前端调用方和二次集成使用者。

## 文档索引

- [REST API 参考](./rest-api.md)
- [SSE 实时事件说明](./sse.md)

## 基本信息

- 默认 API 前缀：`/api/v1`
- OpenAPI JSON：`/api/v1/openapi.json`
- Swagger UI：`/docs`
- 默认开发监听地址：`http://localhost:8000`

## 鉴权模型

- 当 `security.enable_auth: false`
  - 除登录相关接口外，其余接口直接可访问
  - 仅建议在本机或受信任网络使用
- 当 `security.enable_auth: true`
  - 先通过 `POST /api/v1/auth/login` 获取 Bearer Token
  - 再在 `Authorization: Bearer <token>` 头中访问业务接口

## 接口分组

- `auth`：登录与身份信息
- `status`：全局运行状态与账户余额
- `galleries`：画廊列表、日志、重试、删除
- `actions`：手动同步、重置同步状态
- `settings`：运行配置读写
- `maintenance`：遗留数据检查与清理
- `download`：手动补链入队
- `events`：SSE 实时状态推送

## 与部署相关的建议

- 生产环境建议通过反向代理只暴露一个入口端口
- 如果前端和后端通过同域反代集成，前端默认可直接使用同源 `/api/v1`
- 使用 Nginx 代理 `SSE` 时必须关闭缓冲，否则实时进度会明显延迟
