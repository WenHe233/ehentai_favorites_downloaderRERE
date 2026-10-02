# EFDRR 1.0.0

- 使用 shadcn/ui 重构控制台，提供明暗主题、任务详情、实时进度和分组设置。
- 提供 Windows x64 便携桌面版，支持系统托盘，数据保存在程序旁边。
- 修复长标题、文件名中的点号、Unicode 长度和 Windows 保留名称处理。
- 失败任务按最新命名设置重试；已验证的临时归档可在输出失败后复用。
- 修复 Cookie 刷新地址、日志泄露、SSE 分帧、失败队列分类丢失和图片分页遗漏。
- VERSION 统一版本管理，Gitea Ubuntu Runner 自动构建 Windows 包并发布。

使用 Windows 版本时请解压整个 ZIP 包。首次启动显示登录信息；需要安装 WebView2 Runtime。
升级前退出程序，保留 config.yaml、data 和 downloads，再替换程序文件。
