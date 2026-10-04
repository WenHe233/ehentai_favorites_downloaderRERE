# 构建与发布

## 构建矩阵

Windows x64、Linux x64/arm64、macOS x64/arm64 分别构建 cli 和 gui，共十个包。
Runner 固定为 windows-2022、ubuntu-24.04、ubuntu-24.04-arm、macos-15-intel、macos-15。
运行时使用 Python 3.13，前端使用 Node.js 24。PyInstaller 目录模式保留依赖文件，macOS GUI 输出 .app。

每个包包含 BUILD-INFO.json，记录版本、Git 提交、平台、架构、Python 版本和品牌图标校验和。
发行附件包括十个包、SHA256SUMS.txt 和 RELEASE_NOTES.md。

## 本地构建

在目标系统和架构上使用干净虚拟环境：

```bash
python -m pip install --require-hashes -r backend/requirements.txt
python -m pip install --require-hashes -r desktop/build-requirements.lock
python desktop/build.py --flavor cli
```

GUI 使用独立环境，再安装桌面依赖：

```bash
python -m pip install --require-hashes -r desktop/requirements.lock
python desktop/build.py --flavor gui
```

已有 frontend/dist 时可传 --skip-frontend。输出默认在 dist。
scripts/validate_package.py 验证包结构和架构；scripts/smoke_package.py 从压缩包解压到带中文和空格的临时路径，再启动验收。

依赖更新：

```bash
uv pip compile backend/requirements.in --python-version 3.13 --universal --generate-hashes -o backend/requirements.txt
uv pip compile desktop/requirements.in --python-version 3.13 --universal --generate-hashes -o desktop/requirements.lock
uv pip compile desktop/build-requirements.in --python-version 3.13 --universal --generate-hashes -o desktop/build-requirements.lock
```

## Logo

frontend/public/efdrr-icon.svg 是唯一设计源。AppBrandIcon、favicon 使用该 SVG。
desktop/icon.ico、icon.png、icon.icns 由固定版本 resvg-py 和 Pillow 生成：

```bash
python scripts/icons.py
python scripts/icons.py --check
```

Windows 同时嵌入 EXE 图标、向 pywebview 传入 ICO，并在显示窗口前设置 WenHe233.EFDRR.GUI。
macOS 应用包标识为 io.github.WenHe233.EFDRR；Linux 使用 Qt 窗口图标和 efdrr.desktop 菜单入口。
构建缺少图标或图标未同步时失败。图标验收需覆盖真实文件、窗口、任务栏/Dock、托盘以及前端品牌位置。

## GitHub Actions

- ci.yml：分支与 PR 验证，判断 VERSION 是否变化，调用构建与发布工作流。
- packages.yml：十个原生发行包，分别执行冻结产物验收。
- images.yml：amd64/arm64 镜像构建和容器验收，通过 workflow_call 调用。
- release.yml：汇总附件、公开完整 Release、更新稳定镜像 latest。

更新 VERSION 和 RELEASE_NOTES.md 后合入 master，自动发布 v版本标签。
首次迁移到空仓库也会发布。手动运行 Verify and release 并选择 master 可重试。
开发分支和 PR 不推送镜像、不发布 Release。Artifacts 只用于中转和诊断，保留一天。

发布只接受同一版本、同一提交的十个包。附件上传失败保留草稿；重跑重新验证并上传。
已有正式版本只核对，不覆盖。同一版本标签指向不同提交时失败。
已公开版本需要修复时必须提升 VERSION。若只是 latest 推送失败，可重跑发布任务。

GitHub Actions 使用 GITHUB_TOKEN 的 contents:write 和 packages:write。
GHCR 初次创建的包需要在包设置中改为 Public，随后验证匿名拉取。
镜像完整版本标签在双架构测试后创建，latest 在 Release 公开后更新，预发布不更新 latest。

## 验收

CI 使用临时配置和模拟接口，不读取真实账号数据。
服务验收覆盖登录、SPA 路由、API 404、SSE 首帧、配置保存、重启持久化和实例锁。
GUI 验收覆盖真实窗口、登录、品牌图标、隐藏恢复和退出；Linux 同时测试可用托盘与 --no-tray。
正式发布后下载附件复核 SHA-256，并匿名拉取镜像验证架构清单。
Windows 还需检查固定任务栏后退出重启的图标；该检查不能仅由 EXE 资源存在来替代。
