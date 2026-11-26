# CAXA 图库助手 v0.42.10

## 更新策略隔离

- 启动时识别程序根目录的 .git 目录或 worktree .git 文件。
- Git 开发仓库跳过更新源读取和自动增量更新，改由 GitHub Desktop Fetch/Pull 同步。
- 更新器的 apply_update 增加第二道保护；即使被其他入口直接调用，在 Git 仓库中也不会下载、替换、删除或改写版本号。
- 无 .git 的独立运行目录保留原有自动增量更新。
- 增加测试覆盖 Git 目录、worktree 文件、无 Git 的独立安装、无网络访问、程序文件不变，以及无效本地更新配置不影响开发仓库启动。
- 更新机制文档明确说明 E 盘迁移会保留 .git，因此迁移后的仓库仍由 GitHub Desktop 管理。

## 验证边界

GitHub Actions 负责 Python 编译、更新器单元测试和 Manifest 文件哈希完整性检查。Windows 本地仓库需在合并后通过 GitHub Desktop Pull 验证；独立无 .git 目录的真实网络增量更新仍需单独验收。
