# REST API 参考

本文档按接口分组说明请求路径、主要用途和常见请求/响应格式。

## 1. 鉴权接口

### `GET /api/v1/auth/config`

用途：获取当前是否启用了后端登录保护。

响应示例：

```json
{
  "auth_enabled": true
}
```

### `POST /api/v1/auth/login`

用途：管理员登录并获取 Bearer Token。

请求体：

```json
{
  "username": "admin",
  "password": "admin"
}
```

响应示例：

```json
{
  "auth_enabled": true,
  "access_token": "<jwt>",
  "token_type": "bearer",
  "username": "admin"
}
```

### `GET /api/v1/auth/me`

用途：查看当前登录身份。

要求：开启鉴权后需要 Bearer Token。

---

## 2. 全局状态接口

### `GET /api/v1/status`

用途：查看下载器、队列、同步器的总体状态。

响应字段：

- `downloader_running`
- `queue_len`
- `active_downloads`
- `max_concurrent_downloads`
- `failed_retry_count`
- `last_sync_ts`
- `sync_running`
- `sync_last_error`

### `GET /api/v1/account`

用途：查询 E-Hentai / ExHentai 账户余额。

响应字段通常包含：

- `gp`
- `credits`

---

## 3. 画廊与任务接口

### `GET /api/v1/galleries`

用途：分页获取任务中心列表。

查询参数：

- `skip`：偏移量，默认 `0`
- `limit`：页大小，默认 `50`，最大 `200`
- `status`：按状态筛选
- `search`：按 `gid`、标题、`parent_gid` 搜索

返回结构：

```json
{
  "items": [
    {
      "gid": 3875168,
      "token": "ea94844876",
      "title": "示例标题",
      "status": "completed",
      "filecount": 18,
      "posted": "2026-04-05T12:00:00",
      "downloaded_at": "2026-04-05T12:30:00",
      "favorited_at": "2026-04-05T11:59:00",
      "error_msg": null,
      "parent_gid": "3873603",
      "favcat": 7,
      "requested_quality": "original",
      "resolved_quality": "native",
      "progress": {
        "phase": "completed",
        "percent": 100,
        "current": null,
        "total": null,
        "unit": null,
        "detail": "下载完成",
        "updated_at": "2026-04-05T12:30:00Z"
      }
    }
  ],
  "total": 1,
  "skip": 0,
  "limit": 50
}
```

状态取值：

- `pending`
- `downloading`
- `completed`
- `partial`
- `failed`
- `archived`
- `outdated`

### `GET /api/v1/galleries/{gid}/logs`

用途：按需查看单个画廊的下载日志。

响应字段：

- `gid`
- `token`
- `title`
- `error_msg`
- `requested_quality`
- `resolved_quality`
- `logs`

### `POST /api/v1/galleries/{gid}/reset`

用途：将一个任务重置为 `pending`，重新进入下载队列。

### `DELETE /api/v1/galleries/{gid}`

用途：删除数据库记录，保留已下载文件。

### `DELETE /api/v1/galleries/{gid}/with-files`

用途：删除数据库记录，并尝试删除对应下载文件。

### `DELETE /api/v1/galleries`

用途：清空所有画廊任务记录。

---

## 4. 动作接口

### `POST /api/v1/action/sync`

用途：手动触发后台同步。

响应示例：

```json
{
  "status": "started",
  "message": "Sync started in background"
}
```

### `POST /api/v1/action/reset-sync-state`

用途：清空增量同步游标和失败重试队列。

---

## 5. 设置接口

### `GET /api/v1/settings`

用途：读取公开可编辑设置。

说明：

- 敏感字段不会直接原样回显
- Telegram token / Cookies 采用“已保存但不回显”的形式

### `POST /api/v1/settings`

用途：更新运行配置并写回 `backend/config.yaml`。

常见请求字段：

- 站点与认证
  - `ipb_member_id`
  - `ipb_pass_hash`
  - `igneous`
  - `eh_domain`
- 下载相关
  - `download_mode`
  - `archive_quality`
  - `max_concurrent_downloads`
  - `max_retries`
  - `output_template`
  - `conflict_strategy`
  - `truncate_filenames`
  - `filename_max_length`
- 同步相关
  - `auto_sync`
  - `monitored_favcats`
  - `fav_oldest_date`
  - `fav_date_timezone`
- Telegram
  - `telegram_bot_token`
  - `allowed_telegram_ids`
  - `telegram_notifications_enabled`
  - `telegram_notification_recipients`
  - `telegram_notify_download_completed`
  - `telegram_notify_download_failed`
  - `telegram_notify_download_partial`
  - `telegram_notify_sync_completed`
  - `telegram_notify_sync_failed`
  - `telegram_notification_batch_window_seconds`
  - `telegram_notification_quiet_hours_enabled`
  - `telegram_notification_quiet_hours_start`
  - `telegram_notification_quiet_hours_end`

错误处理：

- 输出模板非法时返回 `400`
- 时间字段格式非法时返回 `400`
- 其他未处理异常返回 `500`

---

## 6. 维护接口

### `GET /api/v1/maintenance/legacy-state`

用途：查看遗留文件和旧配置状态。

### `POST /api/v1/maintenance/cleanup`

用途：按选择清理遗留状态。

请求体：

```json
{
  "cleanup_app_config": true,
  "cleanup_temp_cookies": false,
  "cleanup_downloads_zip": false
}
```

---

## 7. 手动补链接口

### `POST /api/v1/download/manual`

用途：手动提交一个画廊链接到下载队列。

请求体：

```json
{
  "url": "https://exhentai.org/g/3875168/ea94844876/"
}
```

能力说明：

- 会解析真实标题与元数据
- 会自动跟进到新版 `gid`
- 已存在但未完成的记录会重置后重新入队

---

## 8. 常见返回码

- `200`：请求成功
- `400`：请求参数错误或模板校验失败
- `401`：未登录或 Token 失效
- `404`：目标任务不存在
- `500`：后端内部异常
