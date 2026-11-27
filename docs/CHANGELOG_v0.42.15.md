# CAXA 图库助手 v0.42.16

## 本轮问题

用户点击“绿色”后，面板提示已发送请求，但 AHK 显示“面板请求已过期”，CAXA 拾取过滤窗口仍然全部颜色勾选。

代码核查发现：v0.42.14 的 AHK 控制器使用 30 秒本地时间 TTL；v0.42.15 的 Python 面板只按 PID 判断控制器是否存活，没有验证正在运行的 AHK 脚本版本。切换 Git 分支并重启 Python 面板后，旧 AHK 进程可能继续存活，导致新面板请求被旧控制器接收。这是与用户截图高度吻合的根因机制，但尚需用户本机日志确认该次运行的实际 build。

## 修复

- 请求 created_at 改为整数 Unix epoch 秒。
- AHK 仅接受 10 位 epoch 秒，并通过 A_NowUTC 计算年龄；队列 TTL 为 300 秒。
- AHK 启动时写入独立 build marker：caxa-helper-v0.42.16。
- Python 启动校验必须同时匹配 PID 与 build marker。
- 面板启动检查和每次发送 CAD 操作前都校验控制器 build；旧版控制器存活时阻止发送并提示退出托盘旧 H 图标后重启助手。
- 面板连接状态显示控制器 build ID。
- 任务签名、工作副本身份与实时租约安全校验保留。

## 自动化验证

- Python compileall：通过。
- unittest：113 项全部通过。
- 增量 manifest SHA-256/size：通过。
- Windows AutoHotkey v2 主助手脚本与只读探针语法检查：通过。
- CI：https://github.com/y2662151417/caxa-library-helper/actions/runs/45936746830

## 未改变的功能边界

五色直接按钮、自动颜色勾选、一键特性写入仍需 CAXA 2024 实机验证。线型比例自动写入尚未实现。助手不会自动保存 EXB、提交图库或执行最终入库。
