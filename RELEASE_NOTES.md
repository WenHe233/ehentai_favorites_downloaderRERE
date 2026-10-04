# EFDRR 1.1.0

- 发布迁移到 GitHub Actions 和 GitHub Releases，保留 VERSION 自动发布及失败重跑。
- Windows x64、Linux x64/arm64、macOS Intel/Apple Silicon 分别提供 CLI 和 GUI 便携包。
- CLI 内置网页控制台，支持监听地址、端口和数据目录参数。
- GUI 保留窗口和托盘，数据保存在解压目录，macOS 放在应用包外。
- 统一程序、窗口、托盘、登录页、导航和 favicon 的 Logo，修复 Windows 任务栏显示 Python 图标的问题。
- 提供 GHCR 单容器镜像，支持 Linux amd64/arm64，可直接使用 Compose 部署。

升级前退出程序，保留 config.yaml、data/ 和 downloads/。Windows 旧固定项若指向 Python，请取消固定后重新固定新版 EFDRR.exe。
