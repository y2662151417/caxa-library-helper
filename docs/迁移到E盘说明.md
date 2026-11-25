# CAXA 助手迁移到 E 盘

## 目标结构

```text
E:\CAXA助手\
  caxa-library-helper\   # Git 仓库，包含 .git 历史
  UserData\               # 私有数据，不进入 GitHub
```

## 数据目录选择

启动脚本优先检查仓库同级的 `UserData\.caxa_userdata.json`。存在有效迁移标记时，设置 `CAXA_HELPER_DATA_DIR` 指向该目录；否则回退到原有 `%LOCALAPPDATA%\CAXA_Library_Helper`。

Python 核心、AutoHotkey 控制器和受管 AHK 运行时统一读取 `CAXA_HELPER_DATA_DIR`。启动日志也写入同一数据目录。

## 一键迁移

1. 在 GitHub Desktop 对 `main` 执行 Fetch 和 Pull。
2. 关闭 CAXA 制作控制台和浮动面板；如果系统托盘区仍有 AutoHotkey 图标，右键选择 Exit。
3. 从仓库根目录双击 `迁移到E盘.bat`。启动器通过 Python 检查 E 盘可访问性，避免 CMD 的盘符哨兵判断误报。
4. Python 迁移程序将仓库复制到 `E:\CAXA助手\caxa-library-helper`，将用户数据复制到 `E:\CAXA助手\UserData`；目标路径由 Python 处理，避免中文路径经过 CMD 参数时出现编码问题。
5. 仓库文件逐个进行 SHA-256 校验；SQLite 主数据库通过 SQLite backup API 复制，并比较 `PRAGMA quick_check` 和各表记录数。
6. 迁移成功后，原始 C 盘仓库和原始 UserData 不会自动删除。

## 安全边界

- 保留仓库内受 Git 跟踪的 `logs/README.txt` 文档；不复制运行时日志文件。\n- 不上传 EXB、数据库、配置、日志或其他用户数据。
- 不移动原始 EXB 图纸目录；数据库中保存的图纸绝对路径保持不变。
- 目标目录非空时停止，不覆盖已有文件。
- 目标空间不足、助手进程仍在运行、Git 索引锁存在或完整性校验失败时停止。
- 迁移先在 E 盘临时目录中构建，完成校验后再重命名为正式目录。
- 迁移失败时删除本次临时目录；源目录和源数据保持不变。

## 迁移后切换 GitHub Desktop

使用 GitHub Desktop 的 Add > Add Existing Repository，选择：

`E:\CAXA助手\caxa-library-helper`

之后只从 E 盘仓库启动和同步。确认新目录正常运行且数据完整后，再决定是否清理旧 C 盘副本。
