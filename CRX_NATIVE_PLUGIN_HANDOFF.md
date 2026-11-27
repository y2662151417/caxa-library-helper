# CAXA CRX 原生插件｜跨对话接续与开发记录

> **新对话第一步：先完整阅读本文件，再检查 GitHub 当前分支和本地 Changes；不要从聊天记忆直接改代码。**
>
> 本文件是 CRX 原生插件这条独立开发线的交接入口和持续工作日志。后续每次实质性操作都必须更新本文件，记录修改、验证和未解决事项。

- 记录日期：2026-11-27
- 仓库：`https://github.com/y2662151417/caxa-library-helper`
- 当前开发分支：`feature/crx-native-plugin`
- 主分支：`main`（本开发线暂不合并、不修改）
- 本次交接文件：仓库根目录 `CRX_NATIVE_PLUGIN_HANDOFF.md`

---

## 1. 项目边界

当前工作是 **CAXA 电子图板 2024 的 C++ CRX 原生插件验证与开发**，不是原有 Python/Tk + SQLite + AutoHotkey v2 外部图库助手的普通迭代。

两条技术线必须区分：

- 原外部助手：Python/Tk + SQLite/INI + AutoHotkey v2，已有独立代码和历史交接记录。
- 当前 CRX 线：C++，使用 CAXA ObjectCRX/CRX API，在独立 Git 分支开发，目标是验证并利用 CAXA 原生接口完成外部模拟点击难以可靠完成的 CAD 操作。
- **尚未确认 CRX 最终会整体替代外部助手，还是只承担其中一部分原生 CAD 操作。** 不要自行合并两套架构，也不要覆盖原外部助手。

本分支当前是独立试验线。不得擅自合并到 `main`、删除原 Python 助手，或改变已存在的更新机制。

## 2. 当前已知实现

根据本轮可见的 C++ 源码内容，当前原型注册了以下命令：

| 命令 | 当前功能 | 操作性质 |
|---|---|---|
| `CAHELP` | 输出插件命令说明 | 只读 |
| `CAINFO` | 读取当前活动图纸标题和完整路径 | 只读 |
| `CALAYERS` | 遍历当前图纸图层表，输出图层名称和颜色索引 | 只读 |

代码中使用 `AcRxArxApp` 作为应用入口，通过 `crxedRegCmds->addCommand` 注册命令；图层表按 `CRxDb::kForRead` 打开。当前命令说明明确表示这一版只读取信息，不修改图纸。

可见入口文件为 `CrxEntryPoint.cpp`。它引用了 CAXA CRX 相关头文件，包括 `crxutcds.h`、`crxdocman.h`、`dbapserv.h`、`dbsymtb.h`。其中 CAINFO 的 API 用法注释指向官方 ObjectCRX Chapter 11 示例。

**能力边界：** 目前只能把上述三个只读命令视为源码中已有的实现。不能据此声称插件已在 CAXA 2024 中成功加载、命令已完成实机验证，或已具备颜色归层、实体修改、视图成块、属性写入和图库入库能力。

前序对话记录称 Visual Studio 的 Release x64 曾成功编译；本次没有重新编译，因此新对话应重新核对编译配置和结果。编译成功不等于 CRX 已在 CAXA 中成功加载。

## 3. Git 与远程仓库状态（2026-11-27）

### 3.1 分支

- 当前开发分支：`feature/crx-native-plugin`
- 最近一次核验时，该分支远程 HEAD 为：`813843d6eeee191854781c241e13adeec2444d8d`
- 最近一次核验时，`main` HEAD 为：`1485f36417753f9165f107ad961163f217bf2fac`
- 上述 SHA 是本交接文档提交之前的状态；提交本文件后，开发分支 HEAD 会更新。
- 本轮只允许在 `feature/crx-native-plugin` 上继续工作。不要把 CRX 改动推到 `main`。

### 3.2 .gitignore 已处理

本轮已通过 GitHub 远程提交，在 `feature/crx-native-plugin` 的 `.gitignore` 中增加 Visual Studio / C++ 构建产物忽略规则。提交 SHA：

`813843d6eeee191854781c241e13adeec2444d8d`

新增忽略范围包括：

- Visual Studio 缓存目录：`.vs/`、`ipch/`
- 构建目录：`build/`、`Debug/`、`Release/`、`x64/`、`Win32/`、`Intermediate/`
- 临时/编译文件：`*.obj`、`*.pch`、`*.pdb`、`*.ilk`、`*.idb`、`*.tlog`、`*.lastbuildstate`、`*.recipe`、`*.log`、`*.exp`、`*.crx`
- Visual Studio 用户状态和数据库文件：`*.suo`、`*.user`、`*.VC.db`、`*.VC.VC.opendb`、`*.vsidx` 等

用户随后在 GitHub Desktop 同步。截图中的 Changes 数量由 66 降到 16，说明忽略规则已明显减少待处理项；但仍须以本地 Git 状态为准。

### 3.3 当前本地 Changes：16 个，尚未提交

用户 2026-11-27 最新截图显示：

- GitHub Desktop 当前仓库：`caxa-library-helper`
- 当前分支：`feature/crx-native-plugin`
- Changes：`16 changed files`
- 当前选中的差异文件：`CAXAHelper.sln`
- 差异窗口提示 LF/CRLF 行结束符转换。这是换行符提示，不等同于编译错误。

截图可辨认的待处理路径包括（截图未完整显示全部 16 项，以下不是完整清单）：

- `crx-native-plugin/开发阶段说明.txt`
- `crx-native-plugin/README_先看我.txt`
- `crx-native-plugin/CAXAHelper.cpp`
- `crx-native-plugin/CrxEntryPoint.cpp`
- `crx-native-plugin/src/StdAfx.cpp`
- `crx-native-plugin/src/StdAfx.h`
- `docs/开发阶段说明.txt`
- `README_先看我.txt`
- `src/CAXAHelper.cpp`
- `src/CrxEntryPoint.cpp`
- `src/StdAfx.cpp`
- `src/StdAfx.h`
- `CAXAHelper.sln`（当前差异查看器选中的文件）

其余项目必须在用户本机 GitHub Desktop 中查看，不能凭截图猜测。

**重要：这 16 个文件尚未提交。** 最近核验的远程分支树中尚未出现 CRX 项目目录和这些 CRX 文件；因此不能把它们描述为已上传到 GitHub。用户暂停前没有授权提交这 16 个文件，也没有授权丢弃或删除它们。

## 4. 目前最重要的结构问题：重复源码目录

本地 Changes 截图同时出现两组相似路径：

- 仓库根目录：`src/...`、`CAXAHelper.sln` 等
- 子目录：`crx-native-plugin/src/...`、`crx-native-plugin/...` 等

之前的整理方向是把 CRX 工程放在独立的 `crx-native-plugin/` 目录中，与原有 Python 助手并列；但当前本地同时出现根目录副本和子目录副本，**尚未确认哪一套是 Visual Studio 当前实际使用的工程目录**。

下一轮必须先做以下核对，再决定是否删除或移动任何文件：

1. 查看 `CAXAHelper.sln` 实际所在路径及其引用的 `.vcxproj` 相对路径。
2. 检查根目录与 `crx-native-plugin/` 下的 `.vcxproj` 是否存在、是否内容一致、各自引用了哪些源文件。
3. 比较两套 `CAXAHelper.cpp`、`CrxEntryPoint.cpp`、`StdAfx.cpp`、`StdAfx.h` 的实际内容和文件哈希。
4. 检查项目的 CRX SDK include/lib 路径、平台、工具集、预处理器宏、输出目录及依赖库。
5. 根据真实项目引用确定唯一权威工程目录，再提出清理方案。未经核对和用户确认，不删除根目录副本或子目录副本。

## 5. 下一轮建议执行顺序

1. **恢复现场：** 先核对仓库、分支、Fetch/Pull 状态和完整 16 项 Changes；不重置、不清理、不丢弃用户本地修改。
2. **审查工程结构：** 完成第 4 节所列的路径、文件差异、SDK 配置检查，确定唯一工程目录。
3. **核对构建：** 检查 Release x64 和 Debug x64 的配置；先做可复现编译，再记录具体错误或成功结果。
4. **CAXA 实机验证：** 在 CAXA 2024 中加载生成的 CRX，依次测试 CAHELP、CAINFO、CALAYERS；使用自制测试图，不使用公司保密图纸。
5. **再规划写操作：** 只读命令验证后，再根据 CAXA API 文档和实机结果设计图层/实体操作。任何会修改图纸的命令都应先定义作用范围、预览、确认、撤销/恢复策略和失败处理，不直接跳到批量自动修改。
6. **阶段归档：** 每一阶段更新本文件中的工作日志，记录实际代码、构建、实机结果及剩余问题。用户确认阶段结果后再进入下一阶段。

## 6. 后续协作硬规则

后续对话和开发操作必须遵守：

1. **先读交接，再动代码。** 每个新对话先读本文件、查看当前分支和工作区状态，再阅读将要修改的实际源文件；不能只靠历史聊天摘要。
2. **严格区分事实和推断。** 明确写出“源码已实现”“本地编译通过”“CAXA 实机已验证”分别代表什么，不互相替代。没有实测证据就标记为未验证。
3. **一次聚焦一个模块。** 先确认问题和验收条件，再改动；不要为了增加版本号而堆叠无关模块。
4. **保留用户现有工作。** 不执行 `reset --hard`、`clean`、批量 discard，不覆盖用户本地未提交文件。删除重复文件、重命名工程、改变目录结构前先核对并说明，等待用户确认。
5. **分支隔离。** CRX 开发只在 `feature/crx-native-plugin` 进行；未经用户明确同意，不合并 `main`，不删除其他分支。
6. **每次操作留痕。** 每次实质性改动后更新本文件的“工作日志”，写明日期、修改文件/路径、修改目的、验证命令及结果、是否提交、剩余风险。若本轮没有代码改动，也记录检查结果和未解决事项。
7. **提交前核对。** 先逐项审查 Changes，排除缓存、编译输出、用户配置和无关文件；说明将提交的文件和目的。不得把“本地有文件”说成“远程已提交”。
8. **保护公开仓库。** 仓库为公开仓库。不得提交公司 EXB/DWG/DXF、真实客户图纸、图号/块名称清单、用户数据库、个人配置、备份、日志、凭据或未经许可分发的 CAXA SDK 文件/库。编译产物默认不入库。
9. **不夸大自动化能力。** 任何涉及图元修改、批量改层、属性写入、图符入库的能力，必须有对应 API 依据和 CAXA 2024 实机测试证据。
10. **保持操作简单。** 向用户说明下一步具体点哪里、做什么、预期看到什么；一次只要求用户完成最必要的操作。

## 7. 工作日志

### 2026-11-27｜建立跨对话交接

- 核对仓库和分支：`y2662151417/caxa-library-helper`，`feature/crx-native-plugin`。
- 核对远程分支 HEAD；确认上一笔远程提交是更新 `.gitignore`，提交 SHA 为 `813843d6eeee191854781c241e13adeec2444d8d`。
- 根据用户 GitHub Desktop 截图记录：本地仍有 16 个待处理文件，尚未提交；截图只显示了部分路径。
- 记录根目录和 `crx-native-plugin/` 两套源码目录并存的问题；尚未删除、移动或覆盖任何本地源码。
- 新增本文件，作为下一轮的接续入口和持续开发日志。
- 本次没有修改 C++ 源码，没有提交用户的 16 个本地文件，没有执行构建或 CAXA 实机测试。

## 8. 新对话可直接发送的指令

> 继续我的 CAXA CRX 原生插件开发。请先打开 GitHub 仓库 `y2662151417/caxa-library-helper` 的 `feature/crx-native-plugin` 分支，完整阅读根目录 `CRX_NATIVE_PLUGIN_HANDOFF.md`，严格遵守其中的项目边界和协作规则。先检查当前 GitHub Desktop 本地 Changes（上次为16个未提交文件），不要丢弃、重置或直接提交。第一项工作是核对根目录与 `crx-native-plugin/` 中重复的 C++ 源码、`.sln`、`.vcxproj` 路径和 CRX SDK 配置，确认实际工程目录后再提出清理方案。每次实质性操作都更新交接文件工作日志；没有 CAXA 2024 实机证据时，不得宣称插件功能已验证。