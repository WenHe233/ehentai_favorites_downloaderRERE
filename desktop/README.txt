EFDRR 便携版

GUI：Windows 双击 EFDRR.exe；Linux 运行 EFDRR；macOS 运行 start.command 或 EFDRR.app。
CLI：运行 efdrr-server --help（Windows 文件名为 efdrr-server.exe）。
服务器对外监听示例：efdrr-server --host 0.0.0.0 --port 8000。

配置 config.yaml、数据库和日志 data/、默认下载 downloads/ 均保存在解压目录。
macOS 数据放在 EFDRR.app 外，请保留整个目录，优先使用 start.command。
--data-root 可覆盖数据目录，其次读取 EFDRR_DATA_ROOT。同一目录只允许一个实例。
首次管理员密码自动生成。GUI 会显示登录信息，CLI 请查看 config.yaml。

Windows 10/11 x64 需要 Edge WebView2 Runtime。
Linux 支持 Ubuntu 24.04 及兼容环境，需要桌面显示服务和系统图形库。
macOS 支持 15 及以上；未经 Apple 公证，请按系统提示在隐私与安全性中确认打开。
托盘可用时关闭窗口可以选择退出或进入托盘；不可用时关闭即退出。
Linux 可运行 install-desktop-entry.sh 创建当前用户的应用菜单入口。
Windows 旧固定项若仍指向 Python，请取消固定后重新固定本包的 EFDRR.exe。

升级前退出程序，保留 config.yaml、data/ 和 downloads/，替换程序文件。
完整文档：https://github.com/WenHe233/ehentai_favorites_downloaderRERE
