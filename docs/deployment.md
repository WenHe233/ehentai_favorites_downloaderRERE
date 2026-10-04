# 部署与数据迁移

## 目录与首次登录

CLI 和 GUI 默认将 config.yaml、data/、downloads/ 放在解压目录；macOS 位于 EFDRR.app 旁。
参数 --data-root 优先于 EFDRR_DATA_ROOT。源代码直接运行 Uvicorn 时仍默认使用 backend 目录。

首次启动会创建随机管理员密码和签名密钥。GUI 显示首次登录信息，服务器请查看 config.yaml。
配置保存使用同目录临时文件和原子替换，必须挂载整个目录，不要单独绑定 config.yaml。

Windows 便携版升级时退出旧程序，保留 config.yaml、data/ 和 downloads/，替换整个程序部分。
不要混用新旧版本的 _internal 目录。同一数据目录禁止同时运行 CLI 与 GUI。

## 从旧三服务 Compose 迁移

1. 在旧部署目录运行 docker compose down，停止 backend、frontend、nginx。
2. 备份 backend/config.yaml、backend/data 和 backend/downloads。
3. 用新的 docker-compose.yml.example 替换部署配置，保留 ./backend:/app/userdata 挂载。
4. 运行 docker compose pull 和 docker compose up -d，仍通过 8080 访问。
5. 登录后检查下载记录、设置和输出目录。旧自定义绝对路径需要维持原有挂载，或修改为容器内的新路径。

数据库不做额外格式迁移，应用沿用现有启动迁移逻辑。数据库记录可能包含绝对下载路径，移动数据到其他系统前应备份并核对这些路径。

## 系统要求

Windows 10/11 x64 需要 Edge WebView2 Runtime。程序、窗口、托盘使用同一 Logo。
旧任务栏快捷方式若指向 pythonw.exe，请取消固定后重新固定新版 EFDRR.exe。
CLI 可执行文件带品牌图标；Windows Terminal 等终端窗口使用其自身图标。

Linux 以 Ubuntu 24.04 为基线。GUI 使用随包的 PySide6 WebEngine，需要桌面会话。
Ubuntu 所需系统库可安装：

```bash
sudo apt install libegl1 libopengl0 libnss3 libxkbcommon-x11-0 libxcb-cursor0 libxcb-icccm4 libxcb-keysyms1 libxcb-shape0 libxcb-xinerama0 libasound2t64 libopus0 libminizip1t64 libpulse0
```

不要以 root 运行桌面版。桌面环境不提供系统托盘时，关闭窗口即退出。
运行 install-desktop-entry.sh 可安装当前用户的应用菜单入口；移动便携目录后重新运行。
服务器使用 CLI 或容器，无需图形环境。

macOS 要求 15 或以上，提供 Intel 和 Apple Silicon 两个包。没有 Apple Developer 签名和公证。
根据 macOS 的系统提示，在“隐私与安全性”中允许该应用。不要修改系统全局安全设置。
优先用 start.command 启动并指定真实解压目录，避免应用转移运行造成数据目录不可写。
保持 EFDRR.app 与数据目录配套，移动或升级前退出程序。

## 运行维护

- 健康检查：GET /api/v1/health，返回版本和就绪状态。
- Docker 日志：docker compose logs -f efdrr。
- 应用日志：数据目录内 data/app.log；桌面异常日志为 data/desktop-crash.log。
- 备份：停止实例，再复制 config.yaml、data/ 和 downloads/；恢复时保持自定义挂载与输出路径。
- 镜像可用完整版本、latest 和 sha-完整提交SHA 标签。预发布不更新 latest。
- 反向代理需要关闭 SSE 缓冲，延长 /api/v1/events/downloads 读取超时。
- 配置含 Cookie 和 Token，应只由部署者访问；对外部署保留登录保护，并由反向代理提供 HTTPS。
- 不要增加 Uvicorn workers 或多个容器副本共享同一数据目录，进程内队列和事件流不支持这种部署。
