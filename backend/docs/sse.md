# SSE 实时事件说明

EFDRR 使用 `SSE` 推送下载与同步的实时状态，前端通过 `fetch + ReadableStream` 消费事件流。

## 接口地址

`GET /api/v1/events/downloads`

响应头重点：

- `Content-Type: text/event-stream`
- `Cache-Control: no-cache`
- `X-Accel-Buffering: no`

## 鉴权

- 当 `security.enable_auth: false` 时，可直接访问
- 当 `security.enable_auth: true` 时，需要带 Bearer Token

示例请求头：

```http
Authorization: Bearer <token>
```

## 事件类型

### `snapshot`

连接建立后立即发送一次快照，帮助前端恢复当前活跃任务状态。

常见字段：

- `active_galleries`
- `sync_status`
- `downloader_running`
- `updated_at`

### `gallery_progress`

单个画廊下载进度更新。

字段示例：

```json
{
  "gid": 3875168,
  "title": "示例标题",
  "status": "downloading",
  "requested_quality": "original",
  "resolved_quality": "native",
  "progress": {
    "phase": "downloading",
    "percent": 62,
    "current": 14,
    "total": 22,
    "unit": "images",
    "detail": "正在下载第 14/22 张图片",
    "updated_at": "2026-04-05T12:22:00Z"
  }
}
```

### `gallery_status`

画廊终态变化，例如完成、失败、部分完成。

常见用途：

- 从“下载中”切到“已完成”
- 从“下载中”切到“失败”
- 由 `native_crawl` 输出 `partial`

### `sync_status`

同步器状态变化。

常见字段：

- `sync_running`
- `sync_last_error`
- `last_sync_ts`

### `heartbeat`

保活事件，用于告诉客户端连接仍然有效。

## 进度阶段

当前后端使用的主要阶段值：

- `queued`
- `preparing`
- `polling`
- `downloading`
- `packaging`
- `verifying`
- `completed`
- `failed`
- `cancelled`

## 反向代理要求

如果使用 Nginx 代理 SSE，必须满足：

- 关闭代理缓冲 `proxy_buffering off`
- 提高读取超时 `proxy_read_timeout`
- 避免中间层缓存事件流

根目录提供的 `deploy/nginx/nginx.conf` 已经包含这些设置。
