#Requires AutoHotkey v2.0
#SingleInstance Force
Persistent

; Read-only staged control probe for fabricated CAXA drawings only.
; F2 is intercepted only while the configured CAXA process is foreground.
; Captures the CAD HWND BEFORE opening its own dialogs: never inspect "A"
; after a confirmation box, because it can point to the probe UI instead.
; Does not read titles, field text, filenames or CAD objects.
; Does not click, press keys into CAD, save files, or use network access.
; Requires company IT approval for AHK and local diagnostics logs.
global dataDir := EnvGet("CAXA_HELPER_DATA_DIR")
if dataDir = ""
    dataDir := EnvGet("LOCALAPPDATA") "\CAXA_Library_Helper"
DirCreate dataDir "\diagnostics"
global cfgFile := dataDir "\cad_buttons.ini"
global cadExe := ""
try cadExe := IniRead(cfgFile, "cad", "process", "")

; CI parses this complete script and exits without registering an interactive probe.
if A_Args.Length && A_Args[1] = "--syntax-check"
    ExitApp 0

#HotIf isConfiguredCaxaForeground()
F2::{
    try {
        targetHwnd := WinGetID("A")
        targetPID := WinGetPID("ahk_id " targetHwnd)
        process := WinGetProcessName("ahk_id " targetHwnd)
        winClass := WinGetClass("ahk_id " targetHwnd)

        message := "只读查看当前窗口的进程名、Windows 窗口类名、控件类名和几何位置。"
            . "`n不会获取图纸名称、参数、控件文本、截图，也不会修改 CAD。"
            . "`n`n目标程序：" process
            . "`n确认这是您用自制测试图打开的 CAXA 窗口或对话框？"
        if MsgBox(message, "只读诊断授权", "YesNo Icon? Default2") != "Yes"
            return

        stages := Map("0", "绘图主窗口", "1", "图层设置（尺寸线层）", "2", "拾取过滤设置",
            "3", "左侧特性栏", "4", "定义图符", "5", "图符入库")
        answer := InputBox("标注本次观察的 CAXA 阶段（只输入数字）："
            . "`n0 绘图主窗口"
            . "`n1 图层设置（尺寸线层）"
            . "`n2 拾取过滤设置"
            . "`n3 左侧特性栏"
            . "`n4 定义图符"
            . "`n5 图符入库", "诊断阶段", "w420 h255", "0")
        if answer.Result != "OK"
            return
        stage := Trim(answer.Value)
        if !stages.Has(stage) {
            MsgBox("阶段编号只能为 0 至 5。本次没有收集窗口信息。", "只读诊断取消", "Icon!")
            return
        }
        stageLabel := stages[stage]

        ; A confirmation or stage dialog may temporarily become the active window.
        ; Always inspect the ORIGINAL captured CAD window by HWND, never by "A".
        if !WinExist("ahk_id " targetHwnd)
            throw Error("原目标窗口已关闭")
        if WinGetPID("ahk_id " targetHwnd) != targetPID
            throw Error("目标窗口身份已变化")
        if WinGetClass("ahk_id " targetHwnd) != winClass
            throw Error("目标窗口类别已变化")

        items := WinGetControls("ahk_id " targetHwnd)
        result := "CAXA read-only control diagnostics - no user content`r`n"
        result .= "Stage: " stage " - " stageLabel "`r`n"
        result .= "Process: " process "`r`nWindowClass: " winClass "`r`n"
        result .= "Controls discovered: " items.Length "`r`n"
        result .= "Positions: parent-window client coordinates when available`r`n"
        result .= "Note: custom-drawn and UIA-only controls may be absent`r`n"
        for ctrl in items {
            result .= "ClassNN: " ctrl
            try {
                ControlGetPos &cx, &cy, &cw, &ch, ctrl, "ahk_id " targetHwnd
                result .= " | x=" cx " y=" cy " w=" cw " h=" ch
            } catch {
                result .= " | geometry unavailable"
            }
            result .= "`r`n"
        }

        root := EnvGet("CAXA_HELPER_DATA_DIR")
        if root = ""
            root := EnvGet("LOCALAPPDATA") "\CAXA_Library_Helper"
        dataDir := root "\diagnostics"
        DirCreate(dataDir)
        file := dataDir "\controls_stage" stage "_" FormatTime(A_Now, "yyyyMMdd_HHmmss")
            . "_" A_TickCount ".txt"
        FileAppend result, file, "UTF-8"
        MsgBox("已保存阶段【" stageLabel "】的只读控件报告（" items.Length " 项）。"
            . "`n不包含图纸文本或截图。`n" file,
            "只读诊断完成", "Iconi")
    } catch as e {
        MsgBox("诊断停止，未修改任何 CAD 内容：" e.Message, "只读诊断失败", "Icon!")
    }
}


#HotIf

isConfiguredCaxaForeground() {
    global cadExe
    if cadExe = ""
        return false
    try {
        return StrLower(WinGetProcessName("A")) = StrLower(cadExe)
    } catch {
        return false
    }
}
