#Requires AutoHotkey v2.0
#Include %A_ScriptDir%\CAXA_标题匹配.ahk
#Include %A_ScriptDir%\CAXA_视图断点.ahk
#SingleInstance Force
Persistent

; CAXA gallery assistant: intentionally no silent confirmation, save, delete or batch edits.
; All CAD clicks require binding to the active process and one-time local calibration.

SetTitleMatchMode 2
CoordMode "Mouse", "Client"

global dataDir := EnvGet("CAXA_HELPER_DATA_DIR")
if dataDir = ""
    dataDir := EnvGet("LOCALAPPDATA") "\CAXA_Library_Helper"
DirCreate dataDir
global cfgFile := dataDir "\cad_buttons.ini"
global jobFile := dataDir "\active_job.ini"
global guardRunner := dataDir "\ahk_guard_runner.ini"
global panelActionFile := dataDir "\panel_action.ini"
global panelActionSeen := ""
global calibrationBusy := false
global controllerMarker := dataDir "\ahk_controller.pid"
global cadExe := IniRead(cfgFile, "cad", "process", "")
global isPaused := false
; The view guide only tracks explicit operator actions. It NEVER sends Enter,
; confirms a dialog, saves a file, or chooses CAD objects on its own.
global guideItems := []
global guideIndex := 0
global guideFilename := ""
global guideSignature := ""
global guideMainHwnd := 0
; A restart may restore *only* an operator-confirmed checklist index.
; This is not evidence that CAXA already selected any entities or basepoints.
global guideWorkFile := ""
global guidePlan := ""
global guideCheckpointFile := dataDir "\view_guide_checkpoint.ini"
; An AHK mouse click must never be sent to another EXB tab, even within CAXA.
; For unrecognized/custom CAXA window titles, fall back to manual clicks.

; Optional read-only parameter-grid capture, disabled until the operator
; calibrates against a fabricated EXB and explicitly enables it.
global autoReadOn := false  ; Unverified on CAXA 2024: fail closed; operator copy remains available.
global captureSeen := ""
global paramBusy := false
SetTimer ParamCapturePoll, 1100
SetTimer PanelActionPoll, 250
try {
    if FileExist(controllerMarker)
        FileDelete controllerMarker
    FileAppend DllCall("GetCurrentProcessId", "UInt"), controllerMarker, "UTF-8"
} catch {
}
OnExit cleanupControllerMarker

autoTip(msg) {
    ToolTip msg
    SetTimer () => ToolTip(), -2600
}

cadOk(quiet := false) {
    global cadExe, isPaused
    if isPaused {
        if !quiet
            autoTip("已暂停：Ctrl+Alt+End 可恢复")
        return false
    }
    if cadExe = "" {
        if !quiet
            MsgBox "尚未绑定 CAXA 进程。先打开 CAXA 主窗口，按 Ctrl+Alt+B 并确认。", "未绑定", "Icon!"
        return false
    }
    try {
        activeExe := WinGetProcessName("A")
        if StrLower(activeExe) = StrLower(cadExe)
            return true
    } catch {
    }
    if !quiet
        autoTip("拦截：当前活动窗口不属于已绑定的 CAD 程序")
    return false
}

bindCad(*) {
    global cadExe, cfgFile
    try {
        exe := WinGetProcessName("A")
        title := WinGetTitle("A")
        response := MsgBox("准备将以下程序绑定为 CAD：`n" exe "`n窗口：" title
            "`n`n确认这确实是 CAXA 绘图窗口，而不是聊天、浏览器或文件窗口？", "绑定 CAD 进程", "YesNo Icon? Default2")
        if response != "Yes"
            return
        cadExe := exe
        IniWrite cadExe, cfgFile, "cad", "process"
        autoTip("已绑定：" cadExe "，现在可以校准按钮")
    } catch as e {
        MsgBox "绑定失败：" e.Message
    }
}

calibrate(slot, label) {
    global cfgFile
    if !cadOk()
        return
    try {
        ; Bind the pointer's owning window, not merely the currently focused
        ; CAXA process. The operator may be hovering above another window.
        targetHwnd := WinGetID("A")
        MouseGetPos &x, &y, &hoverHwnd
        if hoverHwnd != targetHwnd {
            autoTip("鼠标没有停在当前 CAXA 窗口上；取消标定")
            return
        }
        title := WinGetTitle("ahk_id " targetHwnd)
        windowClass := WinGetClass("ahk_id " targetHwnd)
        if MsgBox("标定 " label "？`n按钮所在窗口：" title "`n位置（客户区）：" x "," y
                "`n`n只有在此窗口布局不变时才使用。", "标定按钮", "YesNo Icon? Default2") != "Yes"
            return
        ; The confirmation dialog can steal focus. Never save a calibration
        ; from another active window or a changed CAD dialog.
        if !cadOk(true) || WinGetID("A") != targetHwnd
          || WinGetClass("ahk_id " targetHwnd) != windowClass
          || WinGetTitle("ahk_id " targetHwnd) != title {
            autoTip("确认期间窗口发生变化；本次标定未保存")
            return
        }
        IniWrite x, cfgFile, slot, "x"
        IniWrite y, cfgFile, slot, "y"
        IniWrite windowClass, cfgFile, slot, "class"
        ; For dialogs, use the entire captured title, which usually stays stable.
        ; On any mismatch, refuse to click (fail closed).
        if slot != "define"
            IniWrite title, cfgFile, slot, "title"
        autoTip(label " 已标定；可按对应快捷键使用")
    } catch as e {
        MsgBox "标定失败：" e.Message
    }
}

; Work-file caption matching lives in a shared, independently testable helper.
; Do not infer a CAD document identity from a substring inside another EXB name.

activeDocumentMatches() {
    global jobFile, guideMainHwnd, guideSignature
    if !guideMainHwnd || !WinExist("ahk_id " guideMainHwnd)
        return false
    if !FileExist(jobFile) || IniRead(jobFile,"active","job_signature","") != guideSignature
        return false
    file := IniRead(jobFile,"active","working_file","")
    if file = ""
        return false
    ; Compare the *live* CAD document title; unrecognized captions block clicks.
    try {
        title := WinGetTitle("ahk_id " guideMainHwnd)
        if !titleHasExactWorkFile(title, file)
            return false
        if WinGetPID("A") != WinGetPID("ahk_id " guideMainHwnd)
            return false
        ; A custom dialog has the same process, and main title still shows the work EXB.
        return true
    } catch {
        return false
    }
}

; Run the local Python/SQLite verifier on every *real* CAD click.
; INI signatures alone do not prove the source EXB has not changed.
; The verifier exits 0 only when original hash, working-copy metadata,
; view plan, and the live workbench lease all agree. No CAD API is called.
verifyBeforeAction(signature) {
    global guardRunner
    if !RegExMatch(signature, "^[0-9a-f]{64}$") || !FileExist(guardRunner) {
        autoTip("缺少实时安全校验配置；停止快捷操作")
        return false
    }
    try {
        pythonExe := IniRead(guardRunner, "guard", "executable", "")
        pythonScript := IniRead(guardRunner, "guard", "script", "")
        if pythonExe = "" || !FileExist(pythonExe) {
            autoTip("Python 安全校验器不可用；请手动操作")
            return false
        }
        command := '"' pythonExe '"'
        if pythonScript != "" {
            if !FileExist(pythonScript) {
                autoTip("安全校验脚本缺失；已停止")
                return false
            }
            command .= ' "' pythonScript '"'
        }
        command .= ' --check-job "' signature '"'
        rc := RunWait(command, , "Hide")
        if rc != 0 {
            autoTip("本张 EXB 的任务实时校验未通过；请工作台重新发布")
            return false
        }
        return true
    } catch {
        autoTip("安全校验失败；已停止快捷点击")
        return false
    }
}

safeClick(slot, label) {
    global cfgFile, jobFile, guideFilename, guideSignature
    if !cadOk()
        return
    if !activeDocumentMatches() {
        autoTip("已拦截：无法验证当前 CAXA 标签页与工作副本一致；请手动操作")
        return
    }
    ; Every CAD action must bind to the exact active workflow signature,
    ; not just a process name or a matching dialog title.
    if guideSignature = "" || !FileExist(jobFile)
      || IniRead(jobFile,"active","job_signature","") != guideSignature {
        autoTip("先按 Ctrl+Alt+F6 核对本张EXB与视图计划；快捷操作已拦截")
        return
    }
    try {
        x := IniRead(cfgFile, slot, "x", "")
        y := IniRead(cfgFile, slot, "y", "")
        className := IniRead(cfgFile, slot, "class", "")
        savedTitle := IniRead(cfgFile, slot, "title", "")
        if x = "" || y = "" || className = "" {
            MsgBox "按钮【" label "】未标定。按住 Ctrl+Alt+Shift 并按指定数字，鼠标先悬停在对应按钮上。", "需要标定", "Icon!"
            return
        }
        if WinGetClass("A") != className {
            autoTip("已拦截 " label "：活动窗口类型不同，请手动操作")
            return
        }
        if slot != "define" && WinGetTitle("A") != savedTitle {
            autoTip("已拦截 " label "：弹窗标题不同，请手动操作")
            return
        }
        ; Verify fresh metadata immediately before sending the click.
        if !verifyBeforeAction(guideSignature)
            return
        ; Guard execution can take time: refuse if the user changed CAD tabs
        ; or activated a different dialog while its source hash was calculated.
        if !cadOk(true) || !activeDocumentMatches()
          || WinGetClass("A") != className
          || (slot != "define" && WinGetTitle("A") != savedTitle) {
            autoTip("校验期间 CAXA 活动窗口变化；已取消点击")
            return
        }
        ; This is exactly one click. No subsequent Enter, no save, no silent submit.
        Click Integer(x), Integer(y)
        autoTip("已点击【" label "】；请检查 CAXA 当前界面")
    } catch as e {
        MsgBox "执行失败，未继续自动化：" e.Message, "停止", "Icon!"
    }
}

copySuggestedName(*) {
    global jobFile
    if !cadOk()
        return
    try {
        if !FileExist(jobFile) {
            MsgBox "尚无活动图纸。请在图库工作台中选择图纸，导入并匹配正式块名称清单后发布任务。", "缺少任务", "Icon!"
            return
        }
        code := IniRead(jobFile, "active", "code", "")
        filename := IniRead(jobFile, "active", "filename", "")
        blockName := IniRead(jobFile, "active", "block_name", "")
        blockStatus := IniRead(jobFile, "active", "block_name_status", "未导入块名称清单")
        suggested := IniRead(jobFile, "active", "suggested_name", "")
        if blockStatus = "已匹配" && blockName != "" {
            proposed := blockName
            nameLabel := "正式图符名称"
        } else if blockStatus = "未导入块名称清单" && suggested != "" {
            proposed := suggested
            nameLabel := "本地建议名称（尚未导入正式块名称清单）"
        } else {
            MsgBox(
                "当前图号没有唯一匹配的正式块名称。`n图号：" . code . "`n匹配状态：" . blockStatus
                . "`n`n请先在工作台导入并核对块名称清单；不会用相似图号猜测。",
                "块名称未匹配",
                "Icon!"
            )
            return
        }
        if code = "" || proposed = "" {
            MsgBox "当前图纸信息不完整，已停止复制。", "缺少名称", "Icon!"
            return
        }
        originalTitle := WinGetTitle("A")
        caption := (
            nameLabel . "：`n" . proposed . "`n`n工作台图纸：" . filename
            . "`n当前 CAD 窗口：" . WinGetTitle("A")
            . "`n`n确认工作台选中的图纸与 CAD 中打开的图纸一致？"
        )
        if MsgBox(caption, "防串图确认", "YesNo Icon? Default2") != "Yes"
            return
        sig := IniRead(jobFile, "active", "job_signature", "")
        if !verifyBeforeAction(sig)
            return
        if !cadOk(true) || WinGetTitle("A") != originalTitle {
            autoTip("校验期间窗口发生变化，已取消复制")
            return
        }
        A_Clipboard := proposed
        autoTip("已复制" nameLabel "；请在【图符名称】字段核对后粘贴")
    } catch as e {
        MsgBox "复制失败：" e.Message
    }
}

jobWindowMatches(hwnd, workFile) {
    ; This gate is usable before the six-view guide starts. It binds a command
    ; launcher to the currently active CAXA window and the exact published EXB.
    if !hwnd || !WinExist("ahk_id " hwnd) || workFile = ""
        return false
    try {
        if WinGetID("A") != hwnd
            return false
        if !titleHasExactWorkFile(WinGetTitle("ahk_id " hwnd), workFile)
            return false
        if WinGetPID("A") != WinGetPID("ahk_id " hwnd)
            return false
        return true
    } catch {
        return false
    }
}

cleanupControllerMarker(exitReason, exitCode) {
    global controllerMarker
    currentPid := DllCall("GetCurrentProcessId", "UInt")
    try {
        if FileExist(controllerMarker) && Trim(FileRead(controllerMarker, "UTF-8")) = (currentPid "")
            FileDelete controllerMarker
    } catch {
    }
}

findUniqueWorkWindow(workFile, processName := "") {
    global cadExe
    wantedProcess := processName != "" && processName != "*" ? processName : cadExe
    matches := []
    windows := processName = "*" ? WinGetList() : (wantedProcess != "" ? WinGetList("ahk_exe " wantedProcess) : WinGetList())
    for hwnd in windows {
        try {
            title := WinGetTitle("ahk_id " hwnd)
            if titleHasExactWorkFile(title, workFile)
                matches.Push(hwnd)
        } catch {
        }
    }
    return matches.Length = 1 ? matches[1] : 0
}

activatePublishedWorkWindow(workFile) {
    hwnd := findUniqueWorkWindow(workFile)
    if !hwnd
        return 0
    try {
        WinActivate("ahk_id " hwnd)
        if !WinWaitActive("ahk_id " hwnd, , 2)
            return 0
        return jobWindowMatches(hwnd, workFile) ? hwnd : 0
    } catch {
        return 0
    }
}

findUniqueCalibratedWindow(slot) {
    global cfgFile, cadExe
    if cadExe = ""
        return 0
    cls := IniRead(cfgFile, slot, "class", "")
    title := IniRead(cfgFile, slot, "title", "")
    if cls = "" || title = ""
        return 0
    matches := []
    for hwnd in WinGetList("ahk_exe " cadExe) {
        try {
            if WinGetClass("ahk_id " hwnd) = cls && WinGetTitle("ahk_id " hwnd) = title
                matches.Push(hwnd)
        } catch {
        }
    }
    return matches.Length = 1 ? matches[1] : 0
}

bindCadForPublishedJob(signature) {
    global jobFile, cadExe, cfgFile
    if !FileExist(jobFile) || IniRead(jobFile, "active", "job_signature", "") != signature {
        autoTip("当前任务已变化；未绑定 CAXA")
        return
    }
    workFile := IniRead(jobFile, "active", "working_file", "")
    if workFile = "" || !verifyBeforeAction(signature)
        return
    hwnd := findUniqueWorkWindow(workFile, "*")
    if !hwnd {
        autoTip("未找到唯一的工作副本窗口；请先在 CAXA 打开当前工作副本")
        return
    }
    try {
        exe := WinGetProcessName("ahk_id " hwnd)
        title := WinGetTitle("ahk_id " hwnd)
        if MsgBox("找到与当前工作副本文件名完全匹配的窗口：`n" title "`n进程：" exe
             "`n`n确认将此程序绑定为 CAXA？", "连接 CAXA", "YesNo Icon? Default2") != "Yes"
            return
        if !WinExist("ahk_id " hwnd) || !titleHasExactWorkFile(WinGetTitle("ahk_id " hwnd), workFile)
          || !FileExist(jobFile) || IniRead(jobFile, "active", "job_signature", "") != signature
          || !verifyBeforeAction(signature) {
            autoTip("确认期间任务或窗口发生变化；未绑定 CAXA")
            return
        }
        WinActivate("ahk_id " hwnd)
        if !WinWaitActive("ahk_id " hwnd, , 2) || WinGetID("A") != hwnd
          || !titleHasExactWorkFile(WinGetTitle("ahk_id " hwnd), workFile) {
            autoTip("绑定窗口未能保持活动状态；未保存 CAXA 连接")
            return
        }
        cadExe := exe
        IniWrite cadExe, cfgFile, "cad", "process"
        autoTip("已连接 CAXA：" cadExe)
    } catch as e {
        MsgBox "连接 CAXA 失败：" e.Message, "连接失败", "Icon!"
    }
}

PanelActionPoll() {
    global panelActionFile, panelActionSeen, jobFile
    if !FileExist(panelActionFile)
        return
    try {
        token := IniRead(panelActionFile, "request", "token", "")
        if token = "" || token = panelActionSeen
            return
        action := IniRead(panelActionFile, "request", "action", "")
        signature := IniRead(panelActionFile, "request", "job_signature", "")
        requestTime := FileGetTime(panelActionFile, "M")
        age := DateDiff(requestTime, A_Now, "Seconds")
        panelActionSeen := token
        FileDelete panelActionFile
        if age < 0 || age > 30 {
            autoTip("面板请求已过期；请重新点击操作按钮")
            return
        }
        if !RegExMatch(signature, "^[0-9a-f]{64}$") || !FileExist(jobFile)
          || IniRead(jobFile, "active", "job_signature", "") != signature {
            autoTip("面板请求对应的图纸任务已失效；未执行")
            return
        }
        if action = "bind_cad" {
            bindCadForPublishedJob(signature)
        } else if action = "duplicate_line_cleanup" {
            startDuplicateLineCleanup(signature)
        } else if action = "fill_symbol_name" {
            fillSymbolNameField(true, signature)
        } else if action = "open_pick_filter" {
            runPublishedNativeCommand(signature, "objectset", "打开拾取过滤设置")
        } else if action = "open_properties" {
            runPublishedNativeCommand(signature, "properties", "打开属性面板")
        } else if action = "restore_pick_filter" {
            runPublishedNativeCommand(signature, "objectset", "恢复拾取过滤设置")
        } else if action = "start_view_guide" {
            startGuide(signature)
        } else if action = "next_view" {
            if activateGuideMainWindow(signature)
                nextGuide()
        } else if action = "previous_view" {
            if activateGuideMainWindow(signature)
                previousGuide()
        } else if action = "show_view_guide" {
            if activateGuideMainWindow(signature)
                showGuideHint()
        } else if action = "end_view_guide" {
            if guideSignature = signature
                endGuide()
            else
                autoTip("当前任务没有对应的视图引导记录")
        } else if action = "define_symbol" {
            if activateGuideMainWindow(signature)
                safeClick("define", "定义图符")
        } else if action = "edit_symbol_attributes" {
            if activateCalibratedWindowForJob("attrEdit", signature)
                safeClick("attrEdit", "属性编辑")
        } else if action = "fill_titleblock_attributes" {
            if activateCalibratedWindowForJob("attrFill", signature)
                safeClick("attrFill", "填入当前标题栏属性值")
        } else if action = "finish_gallery_insert" {
            if guideSignature != signature || guideItems.Length = 0 || guideIndex <= guideItems.Length {
                autoTip("全部视图尚未人工确认；拒绝完成入库")
                return
            }
            if IniRead(jobFile, "active", "block_name_status", "") != "已匹配"
              || IniRead(jobFile, "active", "block_name", "") = "" {
                autoTip("正式块名称未唯一匹配；拒绝完成入库")
                return
            }
            expectedName := IniRead(jobFile, "active", "block_name", "")
            nameControl := IniRead(cfgFile, "symbolNameField", "control", "")
            nameWindow := findUniqueCalibratedWindow("symbolNameField")
            finishWindow := findUniqueCalibratedWindow("galleryFinish")
            if nameControl = "" || !nameWindow || !finishWindow || nameWindow != finishWindow {
                autoTip("图符名称框与完成按钮未绑定到同一入库窗口；拒绝提交")
                return
            }
            try {
                actualName := ControlGetText(nameControl, "ahk_id " nameWindow)
            } catch {
                autoTip("无法读取图符名称框；拒绝提交，请人工核对")
                return
            }
            if actualName != expectedName {
                autoTip("入库名称与正式块名称不一致；拒绝提交")
                return
            }
            if activateCalibratedWindowForJob("galleryFinish", signature)
                safeClick("galleryFinish", "完成入库")
        } else if action = "calibrate_define" {
            beginTimedCalibration(signature, "define", "定义图符")
        } else if action = "calibrate_attr_edit" {
            beginTimedCalibration(signature, "attrEdit", "属性编辑")
        } else if action = "calibrate_attr_fill" {
            beginTimedCalibration(signature, "attrFill", "填入当前标题栏属性值")
        } else if action = "calibrate_symbol_name" {
            beginTimedCalibration(signature, "symbolNameField", "图符名称输入框")
        } else if action = "calibrate_gallery_finish" {
            beginTimedCalibration(signature, "galleryFinish", "图符入库完成按钮")
        } else {
            autoTip("未知面板操作；已拒绝")
        }
    } catch as e {
        autoTip("面板操作未执行：" e.Message)
    }
}


; Activate the exact work-copy window for panel-driven guide actions.
activateGuideMainWindow(expectedSignature) {
    global jobFile, guideSignature, guideMainHwnd, isPaused
    if isPaused {
        autoTip("CAD 辅助已暂停；未切换视图引导")
        return false
    }
    if !FileExist(jobFile) || guideSignature = "" || guideSignature != expectedSignature {
        autoTip("视图引导尚未启动，或当前任务签名不一致")
        return false
    }
    workFile := IniRead(jobFile, "active", "working_file", "")
    if !guideMainHwnd || !WinExist("ahk_id " guideMainHwnd)
      || !titleHasExactWorkFile(WinGetTitle("ahk_id " guideMainHwnd), workFile) {
        autoTip("当前工作副本窗口已变化；请重新启动视图引导")
        return false
    }
    try {
        WinActivate("ahk_id " guideMainHwnd)
        if !WinWaitActive("ahk_id " guideMainHwnd, , 2)
          || WinGetID("A") != guideMainHwnd || !jobWindowMatches(guideMainHwnd, workFile) {
            autoTip("无法激活视图引导对应的 CAXA 工作副本")
            return false
        }
        return true
    } catch {
        autoTip("激活 CAXA 工作副本失败")
        return false
    }
}

; For a calibrated dialog button, find exactly one window in the bound CAXA
; process that matches the saved class/title, then activate it before clicking.
activateCalibratedWindowForJob(slot, expectedSignature) {
    global jobFile, cadExe, guideSignature, guideMainHwnd, isPaused
    if isPaused || cadExe = "" {
        autoTip("CAD 辅助已暂停或尚未连接 CAXA")
        return false
    }
    if !FileExist(jobFile) || guideSignature = "" || guideSignature != expectedSignature
      || !guideMainHwnd || !WinExist("ahk_id " guideMainHwnd) {
        autoTip("请先启动当前图纸的视图引导")
        return false
    }
    workFile := IniRead(jobFile, "active", "working_file", "")
    mainHwnd := findUniqueWorkWindow(workFile)
    targetHwnd := findUniqueCalibratedWindow(slot)
    if !mainHwnd || !targetHwnd || WinGetPID("ahk_id " mainHwnd) != WinGetPID("ahk_id " targetHwnd) {
        autoTip("未找到唯一匹配的 CAXA 属性窗口；请检查是否已打开正确弹窗")
        return false
    }
    try {
        WinActivate("ahk_id " targetHwnd)
        if !WinWaitActive("ahk_id " targetHwnd, , 2)
          || WinGetID("A") != targetHwnd
          || !titleHasExactWorkFile(WinGetTitle("ahk_id " mainHwnd), workFile) {
            autoTip("属性窗口激活或工作副本核对失败")
            return false
        }
        return true
    } catch {
        autoTip("无法激活已校准的 CAXA 属性窗口")
        return false
    }
}

findUniqueCalibrationDialog(pid, mainHwnd, requiredTitle := "") {
    matches := []
    for hwnd in WinGetList("ahk_pid " pid) {
        if hwnd = mainHwnd
            continue
        try {
            title := WinGetTitle("ahk_id " hwnd)
            if title = ""
                continue
            if requiredTitle != "" && !InStr(title, requiredTitle)
                continue
            matches.Push(hwnd)
        } catch {
        }
    }
    return matches.Length = 1 ? matches[1] : 0
}

; Panel-driven, timed calibration removes the need to remember AHK hotkeys.
; The panel hides, CAXA is activated, and the operator moves the pointer to
; the requested button/control. Nothing is clicked during calibration.
beginTimedCalibration(signature, slot, label) {
    global jobFile, cadExe, calibrationBusy, isPaused
    if isPaused || cadExe = "" {
        autoTip("CAD 辅助已暂停或尚未连接 CAXA；未开始校准")
        return false
    }
    allowed := Map("define", true, "attrEdit", true, "attrFill", true, "symbolNameField", true, "galleryFinish", true)
    if !allowed.Has(slot) || calibrationBusy {
        autoTip("当前校准类型无效，或已有校准正在进行")
        return false
    }
    if !FileExist(jobFile) || IniRead(jobFile, "active", "job_signature", "") != signature {
        autoTip("当前任务已变化；未启动控件校准")
        return false
    }
    workFile := IniRead(jobFile, "active", "working_file", "")
    mainHwnd := findUniqueWorkWindow(workFile)
    if !mainHwnd || !verifyBeforeAction(signature) {
        autoTip("无法唯一定位当前工作副本；校准已取消")
        return false
    }
    pid := WinGetPID("ahk_id " mainHwnd)
    if slot = "define"
        targetHwnd := mainHwnd
    else if slot = "symbolNameField" || slot = "galleryFinish" || slot = "attrEdit"
        targetHwnd := findUniqueCalibrationDialog(pid, mainHwnd, "图符入库")
    else if slot = "attrFill" {
        targetHwnd := findUniqueCalibrationDialog(pid, mainHwnd, "属性")
        ; Some CAXA builds keep the title unchanged while switching the
        ; contents of the single modal dialog; fall back only if it is unique.
        if !targetHwnd
            targetHwnd := findUniqueCalibrationDialog(pid, mainHwnd)
    } else
        targetHwnd := findUniqueCalibrationDialog(pid, mainHwnd)
    if !targetHwnd {
        autoTip(slot = "symbolNameField" ? "请先打开唯一的【图符入库】窗口" : "请先打开唯一的 CAXA 属性/入库弹窗")
        return false
    }
    try {
        WinActivate("ahk_id " targetHwnd)
        if !WinWaitActive("ahk_id " targetHwnd, , 2)
          || WinGetID("A") != targetHwnd
          || WinGetPID("ahk_id " targetHwnd) != pid
          || !titleHasExactWorkFile(WinGetTitle("ahk_id " mainHwnd), workFile) {
            autoTip("校准窗口与当前工作副本不一致；已取消")
            return false
        }
        title := WinGetTitle("ahk_id " targetHwnd)
        className := WinGetClass("ahk_id " targetHwnd)
        calibrationBusy := true
        ToolTip("请在 5 秒内把鼠标移到 CAXA 的【" label "】上，不要点击。")
        SetTimer(() => ToolTip(), -5200)
        SetTimer(FinishTimedCalibration.Bind(targetHwnd, mainHwnd, signature, slot, label, title, className, workFile), -5000)
        return true
    } catch as e {
        calibrationBusy := false
        autoTip("启动控件校准失败：" e.Message)
        return false
    }
}

FinishTimedCalibration(targetHwnd, mainHwnd, signature, slot, label, title, className, workFile) {
    global cfgFile, jobFile, cadExe, calibrationBusy
    calibrationBusy := false
    try {
        if !WinExist("ahk_id " targetHwnd) || !WinExist("ahk_id " mainHwnd)
          || WinGetID("A") != targetHwnd
          || WinGetTitle("ahk_id " targetHwnd) != title
          || WinGetClass("ahk_id " targetHwnd) != className
          || !titleHasExactWorkFile(WinGetTitle("ahk_id " mainHwnd), workFile)
          || WinGetPID("ahk_id " targetHwnd) != WinGetPID("ahk_id " mainHwnd)
          || !FileExist(jobFile) || IniRead(jobFile, "active", "job_signature", "") != signature {
            autoTip("校准期间窗口或任务发生变化；未保存校准")
            return false
        }
        MouseGetPos(&x, &y, &hoverHwnd, &ctrlClass)
        if hoverHwnd != targetHwnd {
            autoTip("鼠标未停在目标 CAXA 窗口上；未保存校准")
            return false
        }
        if slot = "symbolNameField" && ctrlClass = "" {
            autoTip("未识别到图符名称输入控件；请使用复制后手动粘贴")
            return false
        }
        if !verifyBeforeAction(signature)
          || WinGetID("A") != targetHwnd
          || WinGetTitle("ahk_id " targetHwnd) != title
          || WinGetClass("ahk_id " targetHwnd) != className {
            autoTip("最终校验未通过；未保存控件标定")
            return false
        }
        if slot != "symbolNameField" {
            IniWrite x, cfgFile, slot, "x"
            IniWrite y, cfgFile, slot, "y"
            IniWrite className, cfgFile, slot, "class"
            IniWrite title, cfgFile, slot, "title"
        } else {
            IniWrite ctrlClass, cfgFile, slot, "control"
            IniWrite className, cfgFile, slot, "class"
            IniWrite title, cfgFile, slot, "title"
        }
        autoTip("【" label "】校准已保存；可从悬浮面板调用")
        return true
    } catch as e {
        autoTip("控件校准失败：" e.Message)
        return false
    }
}

; Start only documented CAXA native dialogs. This helper never selects entities
; or edits properties. Commands are allow-listed and bound to the published
; work-copy window and the live workbench lease.
runPublishedNativeCommand(expectedSignature, command, label) {
    global jobFile, isPaused, cadExe
    allowed := Map("objectset", true, "properties", true)
    if !allowed.Has(command) {
        autoTip("未允许的 CAXA 命令；已拒绝")
        return false
    }
    if isPaused {
        autoTip("CAD 辅助已暂停；未启动" label)
        return false
    }
    if !FileExist(jobFile) || cadExe = "" {
        autoTip("尚未连接 CAXA 或没有已发布的工作副本任务")
        return false
    }
    try {
        sig := IniRead(jobFile, "active", "job_signature", "")
        workFile := IniRead(jobFile, "active", "working_file", "")
        if !RegExMatch(sig, "^[0-9a-f]{64}$") || sig != expectedSignature || workFile = "" {
            autoTip("当前图纸任务与面板请求不一致；已停止")
            return false
        }
        hwnd := activatePublishedWorkWindow(workFile)
        if !hwnd || !cadOk(true) || WinGetID("A") != hwnd || !jobWindowMatches(hwnd, workFile) {
            autoTip("未能唯一定位并激活当前工作副本；未启动" label)
            return false
        }
        if !verifyBeforeAction(sig)
            return false
        if !cadOk(true) || WinGetID("A") != hwnd || !jobWindowMatches(hwnd, workFile)
          || !FileExist(jobFile) || IniRead(jobFile, "active", "job_signature", "") != sig {
            autoTip("安全校验期间图纸或活动窗口变化；已取消" label)
            return false
        }
        if !verifyBeforeAction(sig)
            return false
        if !cadOk(true) || WinGetID("A") != hwnd || !jobWindowMatches(hwnd, workFile) {
            autoTip("最终窗口核验未通过；未发送命令")
            return false
        }
        ; The operator must finish/cancel any active CAXA command first.
        ; The command opens a native dialog/palette only; no object is selected.
        SendText command
        Send "{Enter}"
        autoTip("已向当前工作副本发送 CAXA 命令：" command "。请在 CAXA 中完成后续选择和属性确认")
        return true
    } catch as e {
        autoTip("启动" label "失败：" e.Message)
        return false
    }
}

startDuplicateLineCleanup(expectedSignature := "") {
    global jobFile, guideSignature, isPaused
    if isPaused {
        autoTip("CAD 辅助已暂停；未启动删除重复线")
        return
    }
    if !FileExist(jobFile) {
        autoTip("没有已发布的当前图纸任务；请先在工作台选择图纸并打开工作副本")
        return
    }
    try {
        sig := IniRead(jobFile, "active", "job_signature", "")
        workFile := IniRead(jobFile, "active", "working_file", "")
        if !RegExMatch(sig, "^[0-9a-f]{64}$") || workFile = ""
          || (expectedSignature != "" && expectedSignature != sig) {
            autoTip("当前任务签名或工作副本无效；已停止")
            return
        }
        if guideSignature != "" && guideSignature != sig {
            autoTip("当前任务与已启动的视图引导不一致；请重新发布/启动任务")
            return
        }
        ; A floating-panel click is the explicit operator command. Locate and
        ; activate the one exact work-copy window; no extra AHK confirmation.
        hwnd := activatePublishedWorkWindow(workFile)
        if !hwnd {
            autoTip("未找到唯一匹配的 CAXA 工作副本窗口；未启动删除重线")
            return
        }
        if !cadOk(true) || !jobWindowMatches(hwnd, workFile) {
            autoTip("当前活动窗口不是目标 CAXA 工作副本；未启动删除重线")
            return
        }
        if !verifyBeforeAction(sig)
            return
        if !cadOk(true) || WinGetID("A") != hwnd || !jobWindowMatches(hwnd, workFile) {
            autoTip("安全校验期间活动窗口或图纸发生变化；已取消")
            return
        }
        if !verifyBeforeAction(sig)
            return
        if !cadOk(true) || WinGetID("A") != hwnd || !jobWindowMatches(hwnd, workFile) {
            autoTip("最终校验未通过；未发送删除重线命令")
            return
        }
        ; One native command only. The operator selects the range and handles
        ; CAXA's prompts; the tool does not select, delete-confirm, or save.
        SendText "eraseline"
        Send "{Enter}"
        autoTip("已启动 CAXA 删除重复线；请在图面选择范围并按 CAXA 提示确认，工具未自动保存")
    } catch as e {
        MsgBox "启动删除重复线失败，未继续自动化：" e.Message, "停止", "Icon!"
    }
}

statusInfo(*) {
    global cadExe, isPaused, cfgFile, jobFile
    description := (
        "进程：" . (cadExe != "" ? cadExe : "未绑定")
        . "`n状态：" . (isPaused ? "暂停" : "启用")
    )
    for slot, title in Map("define","开始定义", "attrEdit","属性编辑", "attrFill","填入当前标题栏", "galleryFinish","完成入库", "dimToggle","尺寸层按钮") {
        value := IniRead(cfgFile, slot, "x", "")
        description .= "`n" title "：" (value != "" ? "已标定" : "未标定")
    }
    description .= "`n删除重线：悬浮面板按钮（原生命令；人工选取/确认）"
    description .= "`n当前任务：" (FileExist(jobFile) ? "已发布，使用前需核对" : "未发布")
    global guideItems, guideIndex
    description .= "`n向导：" (guideItems.Length ? guideIndex "/" guideItems.Length : "未启动")
    MsgBox description, "CAXA 半自动辅助状态"
}

^!b::bindCad()
^!+1::calibrate("define", "定义图符")
^!+2::calibrate("attrEdit", "属性编辑")
^!+3::calibrate("attrFill", "填入当前标题栏属性值")
^!+4::calibrate("dimToggle", "尺寸线层显示开关（仅在图层窗口已打开且状态可见时使用）")

; Active process, class, and (for dialogs) title must match calibration.
^!F5::safeClick("define", "定义图符")
^!F9::copySuggestedName()
^!F10::safeClick("attrEdit", "属性编辑")
^!F11::safeClick("attrFill", "填入当前标题栏属性值")
; Disabled in v0.13: a fixed position may refer to another layer if row order
; changes. A stable layer-name-aware control has not been verified in CAXA.
^!F7::autoTip("尺寸层快捷点击已锁定：请按图层名称手动关闭/恢复，避免误关其他层")
^!F12::statusInfo()
; Duplicate-line cleanup is launched from the floating panel; no daily hotkey required.

; ---------------- Optional symbol-name field control ----------------------
; Uses a calibrated Windows edit control rather than fixed screen coordinates.
; No auto submit or dialog confirmation; unsupported custom controls fail closed.
; The user must start the guide on the correct work copy first.
calibrateSymbolNameField(*) {
    global cfgFile, jobFile
    if !cadOk() || !FileExist(jobFile)
        return
    try {
        workFile := IniRead(jobFile,"active","working_file","")
        mainHwnd := findUniqueWorkWindow(workFile)
        if !mainHwnd || WinGetPID("A") != WinGetPID("ahk_id " mainHwnd) {
            autoTip("请先在当前 CAXA 工作副本中打开图符入库窗口")
            return
        }
        targetHwnd := WinGetID("A")
        title := WinGetTitle("ahk_id " targetHwnd)
        targetClass := WinGetClass("ahk_id " targetHwnd)
        if !InStr(title, "图符入库") {
            autoTip("请先手工进入【图符入库】窗口，悬停在图符名称输入框")
            return
        }
        MouseGetPos &x, &y, &hoverHwnd, &ctrlClass
        if hoverHwnd != targetHwnd {
            autoTip("鼠标并未停在当前入库窗口上；拒绝绑定其他窗口的控件")
            return
        }
        if ctrlClass = "" {
            MsgBox "此输入框没有可识别的 Windows 控件；不能用 ControlSetText。后续请人工粘贴。", "无法标定", "Icon!"
            return
        }
        if MsgBox("绑定图符名称输入框？`n窗口：" title "`n控件：" ctrlClass
             "`n`n只允许将建议名称写入此控件，不自动提交或覆盖图库。", "标定控件", "YesNo Icon? Default2") != "Yes"
            return
        ; Read these values *before* the prompt and verify focus afterwards:
        ; the AHK prompt itself must not become the saved CAD dialog identity.
        if !cadOk(true) || WinGetID("A") != targetHwnd
          || !WinExist("ahk_id " mainHwnd)
          || !titleHasExactWorkFile(WinGetTitle("ahk_id " mainHwnd), workFile)
          || WinGetClass("ahk_id " targetHwnd) != targetClass
          || WinGetTitle("ahk_id " targetHwnd) != title {
            autoTip("确认期间入库窗口发生变化；取消本次标定")
            return
        }
        IniWrite ctrlClass, cfgFile, "symbolNameField", "control"
        IniWrite targetClass, cfgFile, "symbolNameField", "class"
        IniWrite title, cfgFile, "symbolNameField", "title"
        autoTip("图符名称输入框已标定；可用 Ctrl+Alt+F8 尝试填写")
    } catch as e {
        MsgBox "图符名称输入框标定失败：" e.Message
    }
}

fillSymbolNameField(fromPanel := false, expectedSignature := "") {
    global cfgFile, jobFile, guideSignature, cadExe, isPaused
    if fromPanel && isPaused {
        autoTip("CAD 辅助已暂停；未填写块名称")
        return
    }
    if !fromPanel && (!cadOk() || !activeDocumentMatches())
        return
    try {
        ; Bind this attempt to ONE dialog instance, not just its shared title
        ; and window class. Panel requests locate the calibrated dialog in the
        ; already-bound CAXA process and activate that exact window.
        ctrl := IniRead(cfgFile,"symbolNameField","control","")
        windowClass := IniRead(cfgFile,"symbolNameField","class","")
        windowTitle := IniRead(cfgFile,"symbolNameField","title","")
        if fromPanel {
            if cadExe = "" || !FileExist(jobFile) {
                autoTip("尚未连接 CAXA 或没有活动图纸任务；未填写名称")
                return
            }
            workFile := IniRead(jobFile,"active","working_file","")
            mainHwnd := findUniqueWorkWindow(workFile)
            targetHwnd := findUniqueCalibratedWindow("symbolNameField")
            if !mainHwnd || !targetHwnd || WinGetPID("ahk_id " mainHwnd) != WinGetPID("ahk_id " targetHwnd) {
                autoTip("未找到唯一的当前图纸/图符入库输入框；请手动填写")
                return
            }
            WinActivate("ahk_id " targetHwnd)
            if !WinWaitActive("ahk_id " targetHwnd, , 2) {
                autoTip("无法激活已标定的图符入库窗口")
                return
            }
        } else {
            targetHwnd := WinGetID("A")
        }
        targetWin := "ahk_id " targetHwnd
        title := WinGetTitle(targetWin)
        if ctrl = "" || title != windowTitle || WinGetClass("A") != windowClass || !InStr(title,"图符入库") {
            autoTip("图符入库窗口或输入框标定不匹配，请手动填写")
            return
        }
        sig := IniRead(jobFile,"active","job_signature","")
        if !RegExMatch(sig, "^[0-9a-f]{64}$")
          || (expectedSignature != "" && sig != expectedSignature)
          || (guideSignature != "" && sig != guideSignature) {
            autoTip("图纸任务已变化，拒绝填名")
            return
        }
        proposed := IniRead(jobFile,"active","block_name","")
        blockStatus := IniRead(jobFile,"active","block_name_status","未导入块名称清单")
        if blockStatus != "已匹配" || proposed = "" {
            autoTip("正式块名称未按完整图号唯一匹配；请先导入并核对块名称清单")
            return
        }
        if InStr(proposed,"`n") || InStr(proposed,"`r") {
            autoTip("正式块名称包含非法换行，拒绝输入")
            return
        }
        existing := ControlGetText(ctrl, targetWin)
        if existing != "" && existing != proposed {
            if MsgBox("当前图符名称已有内容：`n" existing "`n`n准备替换为：`n" proposed
                   "`n`n是否继续？不会点击完成或保存。", "替换前核对", "YesNo Icon? Default2") != "Yes"
                return
            if fromPanel {
                WinActivate(targetWin)
                if !WinWaitActive(targetWin, , 2) {
                    autoTip("确认后无法恢复入库窗口焦点；未填写")
                    return
                }
            }
        }
        if !verifyBeforeAction(sig)
            return
        if fromPanel {
            if !cadOk(true) || WinGetID("A") != targetHwnd
              || !WinExist("ahk_id " mainHwnd)
              || !titleHasExactWorkFile(WinGetTitle("ahk_id " mainHwnd), workFile)
              || WinGetPID("ahk_id " mainHwnd) != WinGetPID(targetWin) {
                autoTip("校验期间工作副本窗口变化，已取消填写")
                return
            }
            WinActivate(targetWin)
            if !WinWaitActive(targetWin, , 2) {
                autoTip("入库窗口焦点已变化，取消填写")
                return
            }
        } else if !cadOk(true) || !activeDocumentMatches()
          || WinGetID("A") != targetHwnd {
            autoTip("校验期间入库窗口发生变化，已取消填写")
            return
        }
        if WinGetTitle(targetWin) != title || WinGetClass(targetWin) != windowClass {
            autoTip("入库窗口身份变化，已取消填写")
            return
        }
        ; Even the same dialog may have been edited while confirmation and
        ; hashing ran. Do not overwrite user/CAD changes not explicitly approved.
        if ControlGetText(ctrl, targetWin) != existing {
            autoTip("图符名称字段已变化；本次不覆盖，请重新核对")
            return
        }
        ; Write only the checked input control in the exact captured dialog;
        ; this does not click OK, save, replace an existing symbol or submit.
        ControlSetText proposed, ctrl, targetWin
        observed := ControlGetText(ctrl, targetWin)
        if observed != proposed {
            MsgBox "输入后读取的内容与建议名称不一致。已停止后续操作，请手工检查字段。", "填写未验证", "Icon!"
            return
        }
        autoTip("名称已填入并读回核对；请自行检查属性、类别并确认入库")
    } catch as e {
        MsgBox "CAXA 控件无法直接填写：" e.Message "`n请使用 Ctrl+Alt+F9 复制名称并手动粘贴。", "仅保留手工操作", "Icon!"
    }
}

^!+7::calibrateSymbolNameField()
^!F8::fillSymbolNameField()



; ---------------- Panel-driven multi-view guide ----------------------------
; Panel actions (plus legacy fallback hotkeys) advance an operator-declared
; checklist only. They never choose shapes, place base points, or infer CAD success.
startGuide(expectedSignature := "") {
    global jobFile, guideItems, guideIndex, guideFilename, guideSignature, guideMainHwnd
    global guideCheckpointFile, guideWorkFile, guidePlan, isPaused
    if isPaused {
        autoTip("CAD 辅助已暂停；未启动视图引导")
        return
    }
    if !FileExist(jobFile) {
        autoTip("未发布当前图纸任务，请先在工作台确认名称和视图计划")
        return
    }
    try {
        fullName := IniRead(jobFile,"active","filename","")
        requested := IniRead(jobFile,"active","view_plan","")
        proposed := IniRead(jobFile,"active","suggested_name","")
        blockName := IniRead(jobFile,"active","block_name","")
        blockStatus := IniRead(jobFile,"active","block_name_status","未导入块名称清单")
        if blockStatus = "已匹配" && blockName != ""
            proposed := blockName
        ; View guidance may continue with the local suggestion even when the
        ; formal block-name list has a mismatch. The name-field fill hotkey
        ; remains strictly blocked unless the exact mapping status is matched.
        sig := IniRead(jobFile,"active","job_signature","")
        if fullName = "" || requested = "" || proposed = "" || sig = "" {
            MsgBox "当前任务没有有效图符名称。请先导入正式块名称清单并按完整图号匹配，或在未导入清单时确认本地建议名称。", "中止", "Icon!"
            return
        }
        parts := StrSplit(requested,"|")
        if parts.Length > 6 || parts.Length < 1 {
            MsgBox "单次需处理1-6个视图版本；当前任务无效。", "中止", "Icon!"
            return
        }
        ; CAXA can show multiple opened EXBs and custom tabs, so process-only
        ; comparison is insufficient. Confirm once when changing tasks.
        workName := IniRead(jobFile,"active","working_file","")
        if expectedSignature != "" && expectedSignature != sig {
            autoTip("面板请求与当前图纸签名不一致；未启动视图引导")
            return
        }
        originalWindow := activatePublishedWorkWindow(workName)
        if !originalWindow || !cadOk(true) || WinGetID("A") != originalWindow {
            MsgBox "未能唯一激活当前工作副本窗口。请先在工作台连接 CAXA 并打开对应 EXB。", "无法启动视图引导", "Icon!"
            return
        }
        docTitle := WinGetTitle("ahk_id " originalWindow)
        if !titleHasExactWorkFile(docTitle, workName) {
            MsgBox(
                "当前窗口标题未包含任务对应的工作副本文件名：`n" . docTitle
                . "`n`n为避免串图，本图仅允许手动 CAD 操作。可继续使用离线任务清单。",
                "标题无法核实",
                "Icon!"
            )
            return
        }
        if MsgBox("请核对 CAXA 当前打开的是工作副本：`n" fullName
            "`n窗口：" docTitle "`n`n本张图预计 " parts.Length " 个视图版本。"
            "`n确认开始人工选择/基点引导？", "人工核对当前文件", "YesNo Icon? Default2") != "Yes"
            return
        ; Only metadata from this exact signed job may suggest a prior cursor.
        ; Never silently resume: CAD may have lost the command/selection state.
        savedIndex := guideCheckpointRead(guideCheckpointFile, sig, workName, requested, parts.Length)
        chosenIndex := 1
        if savedIndex > 1 {
            message := "发现上次人工引导记录：第 " savedIndex "/" parts.Length " 项。"
            if savedIndex > parts.Length
                message := "发现上次记录：全部 " parts.Length " 组已人工确认。"
            message .= "`n`n这不是 CAD 命令完成证明。请核对当前工作副本与 CAXA 实际选图进度。"
                . "`n选择【是】恢复记录，【否】从第 1 项开始，均不会自动点击或提交。"
            if MsgBox(message, "恢复人工视图引导？", "YesNo Icon? Default2") = "Yes"
                chosenIndex := savedIndex
        }
        if !verifyBeforeAction(sig)
            return
        if !cadOk(true) || WinGetID("A") != originalWindow
          || !titleHasExactWorkFile(WinGetTitle("A"), workName) {
            autoTip("校验期间活动图纸发生变化，已取消引导")
            return
        }
        guideMainHwnd := WinGetID("A")
        guideItems := parts
        guideIndex := chosenIndex
        guideFilename := fullName
        guideSignature := sig
        guideWorkFile := workName
        guidePlan := requested
        if !persistGuideCheckpoint()
            MsgBox "视图引导已启动，但进度保存失败。关闭脚本后可能需要从第一项重新开始。", "进度未保存", "Icon!"
        guideHint()
    } catch as e {
        MsgBox "无法启动视图引导：" e.Message,"中止", "Icon!"
    }
}

guideHint() {
    global guideItems, guideIndex
    if guideItems.Length = 0 {
        autoTip("视图引导尚未启动")
    } else if guideIndex > guideItems.Length {
        ToolTip "本张所有视图已人工逐项确认；请按 CAXA 提示结束选图、检查基点和图库入库。"
        SetTimer () => ToolTip(), -8500
    } else {
        msg := "当前第 " guideIndex "/" guideItems.Length " 项：" guideItems[guideIndex]
        msg .= "`n请手动框选、确认选集并指定基点；完成后点击悬浮面板【下一视图】"
        ToolTip msg
        SetTimer () => ToolTip(), -8500
    }
}

; Common guide-context gate. AHK cannot inspect whether CAD geometry selection
; really completed; it may only show a checklist for the exact published job.
; A changed task revokes the in-memory guide completely. A different active
; document pauses navigation without discarding the current user's checklist.
persistGuideCheckpoint() {
    global guideCheckpointFile, guideSignature, guideWorkFile, guidePlan, guideIndex, guideItems
    if guideItems.Length = 0 || guideSignature = ""
        return false
    return guideCheckpointSave(guideCheckpointFile, guideSignature, guideWorkFile,
        guidePlan, guideIndex, guideItems.Length)
}

clearGuideState() {
    global guideItems, guideIndex, guideFilename, guideSignature, guideMainHwnd
    global guideWorkFile, guidePlan, guideCheckpointFile
    guideMainHwnd := 0
    guideItems := []
    guideIndex := 0
    guideFilename := ""
    guideSignature := ""
    guideWorkFile := ""
    guidePlan := ""
    if !guideCheckpointClear(guideCheckpointFile)
        autoTip("引导已清除，但本地断点文件未能删除；下次恢复前须核对")
}

guideContextValid() {
    global guideItems, guideSignature, jobFile
    if guideItems.Length = 0 || guideSignature = ""
        return false
    if !FileExist(jobFile) || IniRead(jobFile,"active","job_signature","") != guideSignature {
        clearGuideState()
        autoTip("快捷任务已更换或撤销：旧视图引导及断点已清除，请重新启动")
        return false
    }
    if !activeDocumentMatches() {
        autoTip("当前 CAD 标签页与工作副本不一致；视图引导未推进")
        return false
    }
    return true
}

nextGuide(*) {
    global guideItems, guideIndex
    if !cadOk() || !guideContextValid()
        return
    if guideIndex > guideItems.Length {
        autoTip("所有计划视图已记录。请人工检查并入库，不能自动提交。")
        return
    }
    ; Operator acknowledgement only, no CAD keyboard or mouse commands.
    guideIndex += 1
    if !persistGuideCheckpoint()
        MsgBox "本次人工视图位置未能保存；重启脚本后必须重新核对。", "进度保存失败", "Icon!"
    guideHint()
}

previousGuide(*) {
    global guideIndex
    if !cadOk() || !guideContextValid()
        return
    guideIndex := Max(1,guideIndex-1)
    if !persistGuideCheckpoint()
        MsgBox "本次人工视图位置未能保存；重启脚本后必须重新核对。", "进度保存失败", "Icon!"
    guideHint()
}

showGuideHint(*) {
    if !cadOk() || !guideContextValid()
        return
    guideHint()
}

endGuide(*) {
    clearGuideState()
    autoTip("已清除视图引导和本地断点，不影响 CAD 和工作台记录")
}

^!F6::startGuide()
^!PgDn::nextGuide()
^!PgUp::previousGuide()
^!Home::showGuideHint()
^!+F6::endGuide()

; Emergency switch stays functional even if CAD is not active.
^!End::{
    global isPaused
    isPaused := !isPaused
    autoTip(isPaused ? "自动化已暂停" : "自动化已恢复")
}

; ---------------- Optional automatic property-table read ------------------
; One-time setup on a dummy CAXA drawing:
;   Ctrl+Alt+Shift+5: hover parameter-table object in CAD drawing;
;   Ctrl+Alt+Shift+6: hover a cell of the OPEN parameter editor;
;   Ctrl+Alt+Shift+9: toggle automatic read after every workbench-opened EXB.
; The automation never edits or saves an EXB. If CAXA changes dialog layout,
; it refuses to proceed. Ctrl+Alt+End pauses all actions immediately.

^!+5::calibrate("paramObject", "参数栏对象位置（在标准图绘图界面标定）")
^!+6::calibrate("paramGrid", "参数栏编辑窗口的表格单元格（在弹窗内标定）")
^!+9::{
    global autoReadOn, cfgFile
    autoReadOn := false
    autoTip("CAXA 2024 参数窗口尚未实机验证：自动 Ctrl+A/Ctrl+C 已锁定；请使用人工复制回退")
}

ParamCapturePoll() {
    global dataDir, autoReadOn, captureSeen, paramBusy
    if !autoReadOn || paramBusy || !cadOk(true)
        return
    request := dataDir "\param_read_request.ini"
    if !FileExist(request)
        return
    token := IniRead(request,"capture","id","")
    fileName := IniRead(request,"capture","filename","")
    if token = "" || token = captureSeen || fileName = ""
        return
    ; A CAXA MDI window can contain multiple open drawings. Do not use a
    ; process-only match: require exact drawing filename visible in the title.
    ; This can reject some CAXA layouts; rejection is safer than wrong-file data.
    cadTitle := WinGetTitle("A")
    if !titleHasExactWorkFile(cadTitle, fileName)
        return
    captureSeen := token
    paramBusy := true
    try {
        CaptureParamGrid(token,fileName)
    } catch as err {
        autoTip("自动参数读取未成功（不会写入图纸）：" err.Message)
    } finally {
        paramBusy := false
    }
}

CaptureParamGrid(token,fileName) {
    global cfgFile, dataDir, cadExe
    request := dataDir "\param_read_request.ini"
    src := IniRead(request,"capture","source","")
    if src = "" || !cadOk(true)
        throw Error("请求缺少源图路径或 CAD 窗口已切换")
    cadHwnd := WinGetID("A")
    objClass := IniRead(cfgFile,"paramObject","class","")
    objX := IniRead(cfgFile,"paramObject","x","")
    objY := IniRead(cfgFile,"paramObject","y","")
    gridClass := IniRead(cfgFile,"paramGrid","class","")
    gridTitle := IniRead(cfgFile,"paramGrid","title","")
    gridX := IniRead(cfgFile,"paramGrid","x","")
    gridY := IniRead(cfgFile,"paramGrid","y","")
    if objClass = "" || objX = "" || objY = "" || gridClass = ""
      || gridTitle = "" || gridX = "" || gridY = ""
        throw Error("参数栏位置/属性表窗口尚未完成标定")
    if WinGetClass("A") != objClass
        throw Error("当前 CAXA 绘图窗口与标定窗口不同")
    ; 'parafill' is documented in older CAXA releases; current 2024
    ; compatibility and its modal behavior need a real installation test.
    SendText "parafill"
    Send "{Enter}"
    Sleep 450
    if !cadOk(true) || WinGetID("A") != cadHwnd
        throw Error("CAD 窗口在选取参数栏前发生变化")
    Click Integer(objX), Integer(objY)
    found := false
    Loop 25 {
        Sleep 120
        try {
            if WinGetID("A") != cadHwnd && WinGetClass("A") = gridClass
                && WinGetTitle("A") = gridTitle {
                found := true
                break
            }
        }
    }
    if !found
        throw Error("未出现已标定参数表窗口；请检查 parafill 是否适用于 2024 版")
    Click Integer(gridX), Integer(gridY)
    oldClip := ClipboardAll()
    A_Clipboard := ""
    try {
        Send "^a"
        Sleep 100
        Send "^c"
        if !ClipWait(2)
            throw Error("CAXA 表格未输出可解析的文本（Ctrl+A 可能不支持全选）")
        copied := A_Clipboard
        if StrLen(Trim(copied)) < 8
            throw Error("参数栏复制内容为空或过短")
    } finally {
        A_Clipboard := oldClip
    }
    ; Closing via Escape cancels the properties dialog. No CAD save/commit.
    if WinGetClass("A") = gridClass && WinGetTitle("A") = gridTitle
        Send "{Escape}"
    tmp := dataDir "\.param_capture_tmp.txt"
    payload := dataDir "\param_read_payload.txt"
    response := dataDir "\param_read_response.ini"
    try FileDelete(tmp)
    FileAppend copied,tmp,"UTF-8"
    FileMove tmp,payload,1
    IniWrite token,response,"capture","id"
    IniWrite src,response,"capture","source"
    autoTip("已读取候选参数，等待工作台核对并缓存")
}
