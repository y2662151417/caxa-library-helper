# CAXA 图库助手 v0.42.17

## 本轮问题
点击颜色按钮后，CAXA「拾取过滤设置」窗口能够打开，但颜色没有被自动筛选。

## 修复
- 旧代码可能把任意 Button 类且可读到 checked 状态的控件都视为复选框；这可能将 group box 或普通按钮误识别为颜色复选框。
- 新增 Win32 控件 style 读取，只将标准 checkbox / auto-checkbox / 3-state checkbox 样式作为可点击复选框。
- 颜色分组区域按 BS_GROUPBOX 样式识别。
- 拾取过滤只读诊断报告新增控件 Style 字段，以便区分标准控件与 OwnerDraw/ListView 控件。
- 控制器 build ID 更新为 caxa-helper-v0.42.17，避免旧版 AHK 进程被误判为当前版本。

## 验证边界
- 自动化测试和 AHK 语法检查以本轮 CI 为准。
- 尚未在用户电脑 CAXA 2024 实机验证颜色勾选。
- 若仍失败，需读取助手数据目录 pick_filter_dialog_probe.txt；该报告现在包含 Style 字段。
- 不合并 main、不发布正式安装包；不自动保存 EXB 或提交图库。
