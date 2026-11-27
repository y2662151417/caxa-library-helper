#Requires AutoHotkey v2.0
#ErrorStdOut UTF-8
#Include %A_ScriptDir%\CAXA_标题匹配.ahk
#Include %A_ScriptDir%\CAXA_视图断点.ahk
#SingleInstance Force
Persistent

; CI-only parse mode: AHK parses this file and its includes before executing.
; No timers, files, CAD commands or hotkeys are started in this mode.
if A_Args.Length > 0 && A_Args[1] = "--syntax-check"
    ExitApp 0

; CAXA gallery assistant: no automatic save, delete or final gallery submission.
; Selected-object property changes require an explicit panel action and signed work-copy task.

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
global lastPickFilterSignature := ""
global lastPickFilterSource := ""
global lastPickFilterBaselineCount := -1
global lastPickFilterTick := 0
global galleryFillPendingSignature := ""
global galleryFillPendingSince := 0
global galleryDialogNoticeShown := false
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
SetTimer GalleryDialogPoll, 500
try {
    if FileExist(controllerMarker)
        FileDelete controllerMarker
    FileAppend DllCall("GetCurrentProcessId", "UInt"), controllerMarker, "UTF-8-RAW"
} catch as e {
    try FileAppend "[AHK_STARTUP_ERROR] 无法写入控制器 PID 标记：" e.Message "`n", dataDir "\ahk_controller_marker_error.log", "UTF-8-RAW"
}
OnExit cleanupControllerMarker

autoTip(msg) {
    ToolTip msg
    SetTimer () => ToolTip(), -2600
}

logPanelActionExpiry(action, token, createdAt, nowEpoch, age) {
    global dataDir
    try {
        line := FormatTime(A_Now, "yyyy-MM-dd HH:mm:ss")
            . " | action=" action
            . " | token=" SubStr(token, 1, 8)
            . " | created_at=" createdAt
            . " | now_epoch=" nowEpoch
            . " | age_seconds=" age
            . " | result=expired"
        FileAppend line "\r\n", dataDir "\panel_action_expiry.log", "UTF-8"
    } catch {
    }
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
            MsgBox "尚无活动图纸。请在图库工作台中选择图纸并导入正式块名称 Excel。", "缺少任务", "Icon!"
            return
        }
        code := IniRead(jobFile, "active", "code", "")
        filename := IniRead(jobFile, "active", "filename", "")
        workFile := IniRead(jobFile, "active", "working_file", "")
        blockName := IniRead(jobFile, "active", "block_name", "")
        blockStatus := IniRead(jobFile, "active", "block_name_status", "未导入块名称清单")
        if blockStatus != "已匹配" || blockName = "" {
            MsgBox(
                "当前图号没有唯一匹配的正式块名称。" . Chr(10) . "图号：" . code . Chr(10) . "匹配状态：" . blockStatus
                . Chr(10) . Chr(10) . "请核对 Excel 中的图号和正式块名称；不会使用本地建议名称或相似图号代替。",
                "正式块名称未匹配",
                "Icon!"
            )
            return
        }
        if code = "" || filename = "" || workFile = "" {
            MsgBox "当前图纸信息不完整，已停止复制。", "缺少名称", "Icon!"
            return
        }
        originalTitle := WinGetTitle("A")
        if !titleHasExactWorkFile(originalTitle, workFile) {
            autoTip("当前 CAXA 图纸与助手选中的工作副本不一致；拒绝复制")
            return
        }
        caption := (
            "正式图符名称：" . Chr(10) . blockName . Chr(10) . Chr(10) . "工作台图纸：" . filename
            . Chr(10) . "当前 CAD 窗口：" . originalTitle
            . Chr(10) . Chr(10) . "确认工作台选中的图纸与 CAD 中打开的图纸一致？"
        )
        if MsgBox(caption, "防串图确认", "YesNo Icon? Default2") != "Yes"
            return
        sig := IniRead(jobFile, "active", "job_signature", "")
        if !verifyBeforeAction(sig)
            return
        if !cadOk(true) || WinGetTitle("A") != originalTitle
          || !titleHasExactWorkFile(WinGetTitle("A"), workFile) {
            autoTip("校验期间 CAXA 图纸窗口发生变化，已取消复制")
            return
        }
        A_Clipboard := blockName
        autoTip("已复制正式图符名称；请在【图符名称】字段人工核对后粘贴")
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
        sourceColor := IniRead(panelActionFile, "request", "source_color", "")
        targetLayer := IniRead(panelActionFile, "request", "target_layer", "")
        targetColor := IniRead(panelActionFile, "request", "target_color", "")
        targetLinetype := IniRead(panelActionFile, "request", "target_linetype", "")
        linetypeScale := IniRead(panelActionFile, "request", "linetype_scale", "")
        targetLineweight := IniRead(panelActionFile, "request", "target_lineweight", "")
        createdAt := IniRead(panelActionFile, "request", "created_at", "")
        nowEpoch := 0
        if IsNumber(createdAt) {
            nowEpoch := DateDiff("19700101000000", A_NowUTC, "Seconds")
            age := nowEpoch - Floor(createdAt + 0)
        } else {
            age := 999999
        }
        panelActionSeen := token
        FileDelete panelActionFile
        ; UTC epoch avoids local-time/file-time timezone ambiguity. The
        ; five-minute queue TTL tolerates a busy controller; the signed job
        ; and 35-second live workbench lease remain mandatory before CAD work.
        if age < -10 || age > 300 {
            logPanelActionExpiry(action, token, createdAt, nowEpoch, age)
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
        } else if action = "probe_cad_controls" {
            probeCaxaControls(signature)
        } else if action = "probe_pick_filter_dialog" {
            probePickFilterDialog(signature, sourceColor)
        } else if action = "duplicate_line_cleanup" {
            startDuplicateLineCleanup(signature)
        } else if action = "fill_symbol_name" {
            autoTip("正式名称由操作者手动复制和粘贴；助手不会自动填写")
        } else if action = "set_pick_filter" {
            setPickFilterColor(signature, sourceColor)
        } else if action = "restore_pick_filter" {
            setPickFilterColor(signature, "全部颜色")
        } else if action = "apply_color_layer" {
            applyColorLayer(signature, sourceColor, targetLayer, targetColor, targetLinetype, linetypeScale, targetLineweight)
        } else if action = "probe_properties_palette" {
            probePropertiesPalette(signature)
        } else if action = "calibrate_layer_combo" {
            beginPropertyComboCalibration(signature, "layerCombo", "图层")
        } else if action = "calibrate_color_combo" {
            beginPropertyComboCalibration(signature, "colorCombo", "颜色")
        } else if action = "calibrate_linetype_combo" {
            beginPropertyComboCalibration(signature, "linetypeCombo", "线型")
        } else if action = "calibrate_lineweight_combo" {
            beginPropertyComboCalibration(signature, "lineweightCombo", "线宽")
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
            startSymbolDefinition(signature)
        } else if action = "edit_symbol_attributes" {
            if activateCalibratedWindowForJob("attrEdit", signature)
                safeClick("attrEdit", "属性编辑")
        } else if action = "fill_titleblock_attributes" {
            if activateCalibratedWindowForJob("attrFill", signature)
                safeClick("attrFill", "填入当前标题栏属性值")
        } else if action = "finish_gallery_insert" {
            autoTip("最终图符入库由操作者在 CAXA 中完成；助手不会点击完成按钮、提交或保存")
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


; Start the native CAXA multi-view symbol-definition command.
; CAXA prompts for the view count, then owns the per-view selection/basepoint sequence.
; The helper supplies only the count from the signed workbench plan; it never selects geometry.
startSymbolDefinition(expectedSignature) {
    global jobFile, cadExe, guideSignature, guideMainHwnd, guideFilename, guideWorkFile, guidePlan
    global guideItems, guideIndex, galleryFillPendingSignature, galleryFillPendingSince, galleryDialogNoticeShown, isPaused
    if isPaused {
        autoTip("CAD 辅助已暂停；未启动定义图符")
        return false
    }
    if !FileExist(jobFile) {
        autoTip("没有已发布的图纸任务；请先在图纸管理中选择并打开工作副本")
        return false
    }
    sig := IniRead(jobFile, "active", "job_signature", "")
    if sig = "" || sig != expectedSignature {
        autoTip("当前图纸任务签名不一致；拒绝启动定义图符")
        return false
    }
    fullName := IniRead(jobFile, "active", "filename", "")
    requested := IniRead(jobFile, "active", "view_plan", "")
    workFile := IniRead(jobFile, "active", "working_file", "")
    if fullName = "" || requested = "" || workFile = "" {
        autoTip("当前任务缺少图纸名称、视图计划或工作副本")
        return false
    }
    parts := StrSplit(requested, "|")
    if parts.Length != 4 && parts.Length != 6 {
        autoTip("当前视图计划无效；本工具只接受双视图4项或三视图6项")
        return false
    }
    for item in parts {
        if Trim(item) = "" {
            autoTip("视图计划包含空项目；请回工作台修正后再启动")
            return false
        }
    }
    ; Bind CAXA on first use from the exact published work-copy window.
    ; The one-time confirmation replaces a separate mandatory connect-button step.
    if cadExe = "" || !findUniqueWorkWindow(workFile) {
        bindCadForPublishedJob(sig)
        if cadExe = "" {
            autoTip("尚未连接到当前工作副本；请确认 CAXA 已打开该 EXB 后重试")
            return false
        }
    }
    if galleryFillPendingSignature != "" {
        if MsgBox("已有一个图符定义会话尚未结束。`n`n如果 CAXA 仍在等待选择视图，请选【否】返回继续；如果你已经在 CAXA 按 Esc 取消了旧命令，请选【是】清除旧会话并重新开始。", "已有定义会话", "YesNo Icon? Default2") != "Yes"
            return false
    }
    clearGuideState()
    hwnd := activatePublishedWorkWindow(workFile)
    if !hwnd || !cadOk(true) || WinGetID("A") != hwnd || !jobWindowMatches(hwnd, workFile) {
        autoTip("无法唯一激活当前 CAXA 工作副本；未启动定义图符")
        return false
    }
    if !verifyBeforeAction(sig) {
        autoTip("当前任务安全校验未通过；未启动定义图符")
        return false
    }
    if !cadOk(true) || WinGetID("A") != hwnd || !jobWindowMatches(hwnd, workFile)
      || !FileExist(jobFile) || IniRead(jobFile, "active", "job_signature", "") != sig {
        autoTip("校验期间活动图纸或窗口发生变化；已取消定义图符")
        return false
    }
    ; Keep the exact job/window context for later attribute and gallery actions.
    guideMainHwnd := hwnd
    guideSignature := sig
    guideFilename := fullName
    guideWorkFile := workFile
    guidePlan := requested
    guideItems := []
    guideIndex := 0
    SendText "symdef"
    Send "{Enter}"
    Sleep 450
    ; Symdef should now be waiting for its view count. Recheck the live task before typing it.
    if !verifyBeforeAction(sig) || !cadOk(true) || WinGetID("A") != hwnd
      || !jobWindowMatches(hwnd, workFile)
      || !FileExist(jobFile) || IniRead(jobFile, "active", "job_signature", "") != sig {
        clearGuideState()
        autoTip("Symdef 已启动，但第二次校验未通过；请在 CAXA 按 Esc 取消当前命令")
        return false
    }
    countText := String(parts.Length)
    SendText countText
    Send "{Enter}"
    galleryFillPendingSignature := sig
    galleryFillPendingSince := A_TickCount
    galleryDialogNoticeShown := false
    autoTip("已启动 CAXA Symdef（" countText "项）。在 CAXA 中依次框选每组视图并指定各自基点；请人工完成名称、属性和图库类别核对。助手不会自动填写、提交、点击入库或保存。")
    return true
}


; Read-only inspection of every visible top-level window in the exact published CAXA process.
; It does not activate windows, send CAD keys, click controls, or read control text.
probeCaxaControls(expectedSignature) {
    global jobFile, cadExe, dataDir, isPaused
    if isPaused {
        autoTip("CAD 辅助已暂停；只读诊断未启动")
        return false
    }
    if cadExe = "" {
        autoTip("尚未连接 CAXA；请先连接当前工作副本")
        return false
    }
    if !FileExist(jobFile) || IniRead(jobFile, "active", "job_signature", "") != expectedSignature {
        autoTip("当前任务已变化；拒绝执行只读诊断")
        return false
    }
    workFile := IniRead(jobFile, "active", "working_file", "")
    if workFile = "" {
        autoTip("当前任务缺少工作副本路径")
        return false
    }
    mainHwnd := findUniqueWorkWindow(workFile)
    if !mainHwnd {
        autoTip("未找到唯一的当前工作副本窗口；请确认 CAXA 已打开该工作副本")
        return false
    }
    pid := WinGetPID("ahk_id " mainHwnd)
    process := WinGetProcessName("ahk_id " mainHwnd)
    mainClass := WinGetClass("ahk_id " mainHwnd)
    if StrLower(process) != StrLower(cadExe) {
        autoTip("工作副本窗口进程与已绑定 CAXA 不一致；诊断已停止")
        return false
    }
    if !(WinGetStyle("ahk_id " mainHwnd) & 0x10000000) {
        autoTip("当前工作副本窗口不可见；只读诊断已停止")
        return false
    }

    if !verifyBeforeAction(expectedSignature)
      || !FileExist(jobFile)
      || IniRead(jobFile, "active", "job_signature", "") != expectedSignature
      || !WinExist("ahk_id " mainHwnd)
      || WinGetPID("ahk_id " mainHwnd) != pid
      || WinGetClass("ahk_id " mainHwnd) != mainClass
      || !titleHasExactWorkFile(WinGetTitle("ahk_id " mainHwnd), workFile) {
        autoTip("只读诊断前的任务/窗口复核未通过；未读取控件")
        return false
    }

    ; Keep the exact task window first; add every other visible top-level
    ; window owned by the same CAXA process. Never select by window title.
    maxWindows := 20
    maxControls := 1200
    maxControlsPerWindow := 300
    windowHandles := [mainHwnd]
    truncatedWindows := 0
    for hwnd in WinGetList("ahk_pid " pid) {
        if hwnd = mainHwnd
            continue
        try {
            if !(WinGetStyle("ahk_id " hwnd) & 0x10000000)
                continue
            if windowHandles.Length < maxWindows
                windowHandles.Push(hwnd)
            else
                truncatedWindows += 1
        } catch {
        }
    }

    snapshots := []
    totalControls := 0
    try {
        nl := Chr(13) Chr(10)
        result := "CAXA read-only window/control diagnostics - no user content" nl
        result .= "Process: " process nl
        result .= "MainWindowClass: " mainClass nl
        result .= "Visible top-level windows recorded: " windowHandles.Length nl
        result .= "Limits: " maxWindows " windows; " maxControlsPerWindow " controls/window; " maxControls " controls total" nl
        result .= "No window titles, control text, drawing text, parameters or screenshots were captured." nl
        result .= "Per-control metadata: Win32 class, dialog control ID, visible/enabled state, GWL_STYLE and GWL_EXSTYLE." nl
        result .= "Only the exact task-bound CAXA process was inspected." nl

        for windowIndex, hwnd in windowHandles {
            if totalControls >= maxControls
                break
            if !WinExist("ahk_id " hwnd) || WinGetPID("ahk_id " hwnd) != pid {
                autoTip("扫描期间 CAXA 窗口发生变化；报告未保存")
                return false
            }
            className := WinGetClass("ahk_id " hwnd)
            wx := 0
            wy := 0
            ww := 0
            wh := 0
            positionAvailable := true
            try {
                WinGetPos &wx, &wy, &ww, &wh, "ahk_id " hwnd
            } catch {
                positionAvailable := false
            }
            controls := []
            controlsAvailable := true
            try {
                controls := WinGetControls("ahk_id " hwnd)
            } catch {
                controlsAvailable := false
            }
            snapshots.Push({hwnd: hwnd, className: className})
            result .= nl "Window #" windowIndex
            result .= " | Role: " (hwnd = mainHwnd ? "Main drawing window" : "Other visible CAXA window")
            result .= " | HWND: " hwnd
            result .= " | Class: " className
            if positionAvailable
                result .= " | ScreenRect: x=" wx " y=" wy " w=" ww " h=" wh
            else
                result .= " | ScreenRect: unavailable"
            result .= nl
            result .= "Controls discovered: " controls.Length
            if !controlsAvailable
                result .= " (enumeration unavailable)"
            result .= nl

            controlLimit := Min(controls.Length, maxControlsPerWindow, maxControls - totalControls)
            for controlIndex, ctrl in controls {
                if controlIndex > controlLimit
                    break
                controlHwnd := 0
                try {
                    controlHwnd := ControlGetHwnd(ctrl, "ahk_id " hwnd)
                } catch {
                }
                result .= "  ClassNN: " ctrl
                if controlHwnd {
                    result .= " | ControlHWND: " controlHwnd
                    controlClass := ""
                    controlIdText := "unavailable"
                    visibleText := "unavailable"
                    enabledText := "unavailable"
                    styleText := "unavailable"
                    exStyleText := "unavailable"
                    try {
                        classBuffer := Buffer(512, 0)
                        classLength := DllCall("GetClassNameW", "Ptr", controlHwnd, "Ptr", classBuffer, "Int", 256, "Int")
                        if classLength > 0
                            controlClass := StrGet(classBuffer, classLength, "UTF-16")
                    } catch {
                    }
                    try controlIdText := String(DllCall("GetDlgCtrlID", "Ptr", controlHwnd, "Int"))
                    try visibleText := DllCall("IsWindowVisible", "Ptr", controlHwnd, "Int") ? "yes" : "no"
                    try enabledText := DllCall("IsWindowEnabled", "Ptr", controlHwnd, "Int") ? "yes" : "no"
                    try {
                        getWindowLongFn := A_PtrSize = 8 ? "GetWindowLongPtrW" : "GetWindowLongW"
                        longReturnType := A_PtrSize = 8 ? "Ptr" : "Int"
                        style := DllCall(getWindowLongFn, "Ptr", controlHwnd, "Int", -16, longReturnType)
                        exStyle := DllCall(getWindowLongFn, "Ptr", controlHwnd, "Int", -20, longReturnType)
                        styleText := Format("0x{:08X}", style & 0xFFFFFFFF)
                        exStyleText := Format("0x{:08X}", exStyle & 0xFFFFFFFF)
                    } catch {
                    }
                    result .= " | Win32Class: " (controlClass != "" ? controlClass : "unavailable")
                    result .= " | ControlID: " controlIdText
                    result .= " | Visible: " visibleText " | Enabled: " enabledText
                    result .= " | Style: " styleText " | ExStyle: " exStyleText
                } else {
                    result .= " | ControlHWND: unavailable | native metadata unavailable"
                }
                try {
                    ControlGetPos &cx, &cy, &cw, &ch, ctrl, "ahk_id " hwnd
                    result .= " | ClientRect: x=" cx " y=" cy " w=" cw " h=" ch
                } catch {
                    result .= " | geometry unavailable"
                }
                result .= nl
                totalControls += 1
            }
            if controls.Length > controlLimit
                result .= "  Truncated: recorded " controlLimit " of " controls.Length " controls." nl
        }

        if truncatedWindows > 0
            result .= nl "Additional visible windows omitted by the " maxWindows " window limit: " truncatedWindows nl
        if totalControls >= maxControls
            result .= "Global control limit reached: " maxControls nl
        result .= "Custom-drawn and UIA-only controls may be absent." nl

        if !verifyBeforeAction(expectedSignature)
          || !FileExist(jobFile)
          || IniRead(jobFile, "active", "job_signature", "") != expectedSignature
          || !WinExist("ahk_id " mainHwnd)
          || WinGetPID("ahk_id " mainHwnd) != pid
          || WinGetClass("ahk_id " mainHwnd) != mainClass
          || !titleHasExactWorkFile(WinGetTitle("ahk_id " mainHwnd), workFile) {
            autoTip("扫描期间任务或主窗口身份发生变化；报告未保存")
            return false
        }
        for _, item in snapshots {
            if !WinExist("ahk_id " item.hwnd)
              || WinGetPID("ahk_id " item.hwnd) != pid
              || WinGetClass("ahk_id " item.hwnd) != item.className
              || !(WinGetStyle("ahk_id " item.hwnd) & 0x10000000) {
                autoTip("扫描期间目标窗口发生变化；报告未保存")
                return false
            }
        }

        outputDir := dataDir "\diagnostics"
        DirCreate outputDir
        file := outputDir "\controls_all_" FormatTime(A_Now, "yyyyMMdd_HHmmss")
            . "_" A_TickCount ".txt"
        FileAppend result, file, "UTF-8"
        MsgBox("已保存当前 CAXA 进程的只读扫描报告。"
            . Chr(10) "可见窗口：" windowHandles.Length
            . Chr(10) "记录控件：" totalControls
            . Chr(10) Chr(10) file,
            "只读诊断完成", "Iconi")
        return true
    } catch as e {
        MsgBox("诊断停止，未修改任何 CAD 内容：" e.Message, "只读诊断失败", "Icon!")
        return false
    }
}


; When Symdef opens the gallery dialog, fill the exact mapped name once if the
; name field was calibrated. No category selection, attribute submission or final click occurs here.
; When Symdef opens the gallery dialog, notify the operator only.
; The helper does not fill attributes, submit, finish insertion, or save the EXB.
GalleryDialogPoll() {
    global galleryFillPendingSignature, galleryFillPendingSince, galleryDialogNoticeShown, jobFile, cadExe
    signature := galleryFillPendingSignature
    if signature = "" || cadExe = "" || !FileExist(jobFile)
        return
    try {
        if IniRead(jobFile, "active", "job_signature", "") != signature {
            galleryFillPendingSignature := ""
            galleryFillPendingSince := 0
            galleryDialogNoticeShown := false
            return
        }
        if A_TickCount - galleryFillPendingSince > 1800000 {
            galleryFillPendingSignature := ""
            galleryFillPendingSince := 0
            galleryDialogNoticeShown := false
            return
        }
        workFile := IniRead(jobFile, "active", "working_file", "")
        mainHwnd := findUniqueWorkWindow(workFile)
        if !mainHwnd
            return
        pid := WinGetPID("ahk_id " mainHwnd)
        dialogHwnd := findUniqueCalibrationDialog(pid, mainHwnd, "图符入库")
        if !dialogHwnd
            return
        if !verifyBeforeAction(signature) {
            galleryFillPendingSignature := ""
            galleryFillPendingSince := 0
            return
        }
        galleryFillPendingSignature := ""
        galleryFillPendingSince := 0
        galleryDialogNoticeShown := true
        autoTip("已打开图符入库窗口。请人工填写正式名称、核对属性和图库类别；助手不会自动填写、提交或保存。")
    } catch as e {
        galleryFillPendingSignature := ""
        galleryFillPendingSince := 0
        autoTip("图符入库窗口状态无法核验；请人工检查：" e.Message)
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

; Locate the native pick-filter dialog for the exact active work copy.
findPickFilterDialog(expectedSignature, workFile, mainHwnd) {
    ; Hash/SQLite preflight is intentionally performed once before polling.
    ; Re-running it on every 100 ms window check can launch dozens of Python
    ; processes and stall the CAD controller while the user queues another action.
    if !verifyBeforeAction(expectedSignature)
      || !WinExist("ahk_id " mainHwnd)
      || !titleHasExactWorkFile(WinGetTitle("ahk_id " mainHwnd), workFile)
        return 0
    pid := WinGetPID("ahk_id " mainHwnd)
    Loop 30 {
        if !WinExist("ahk_id " mainHwnd)
          || WinGetPID("ahk_id " mainHwnd) != pid
          || !titleHasExactWorkFile(WinGetTitle("ahk_id " mainHwnd), workFile)
            return 0
        if !FileExist(jobFile)
          || IniRead(jobFile, "active", "job_signature", "") != expectedSignature
            return 0
        for hwnd in WinGetList("ahk_pid " pid) {
            try {
                title := WinGetTitle("ahk_id " hwnd)
                if InStr(title, "拾取过滤设置")
                    return hwnd
            } catch {
            }
        }
        Sleep 100
    }
    return 0
}

normalizeFilterLabel(value) {
    value := StrReplace(value, "&", "")
    value := StrReplace(value, "（", "(")
    value := RegExReplace(value, "\s+", "")
    return value
}

filterColorKey(value) {
    value := normalizeFilterLabel(value)
    if value = "红色"
        return "红"
    if value = "黄色"
        return "黄"
    if value = "绿色"
        return "绿"
    if value = "青色"
        return "青"
    if value = "蓝色"
        return "蓝"
    if value = "洋红" || value = "洋红色"
        return "洋红"
    if value = "白色"
        return "白"
    if value = "黑色" || value = "黑白色"
        return "黑"
    return ""
}

findFilterCheckbox(labelItem, items, gx, gy, gr, gb) {
    if labelItem["checked"] >= 0 && labelItem["class"] = "Button"
        return labelItem["ctrl"]
    bestDistance := 999999
    targetControl := ""
    labelY := labelItem["y"] + labelItem["h"] / 2
    labelX := labelItem["x"]
    for item in items {
        if item["class"] != "Button" || item["checked"] < 0
            continue
        cx := item["x"] + item["w"] / 2
        cy := item["y"] + item["h"] / 2
        if cx < gx || cx > gr || cy < gy || cy > gb
            continue
        if item["x"] + item["w"] > labelX + 3 || Abs(cy - labelY) > 8
            continue
        distance := labelX - (item["x"] + item["w"])
        if distance >= 0 && distance < bestDistance {
            bestDistance := distance
            targetControl := item["ctrl"]
        }
    }
    return targetControl
}

setPickFilterColor(expectedSignature, sourceColor) {
    global jobFile, cadExe, isPaused, dataDir
    global lastPickFilterSignature, lastPickFilterSource
    global lastPickFilterBaselineCount, lastPickFilterTick
    ; Any new filter request invalidates the previous selection-to-rule link.
    lastPickFilterSignature := ""
    lastPickFilterSource := ""
    lastPickFilterBaselineCount := -1
    lastPickFilterTick := 0
    if isPaused || cadExe = "" || !FileExist(jobFile) {
        autoTip("尚未连接 CAXA 或控制器已暂停；未设置颜色过滤")
        return false
    }
    if sourceColor != "红色" && sourceColor != "绿色" && sourceColor != "蓝色"
      && sourceColor != "洋红色" && sourceColor != "白色+黑白色"
      && sourceColor != "全部颜色" {
        autoTip("未知颜色筛选项；未修改过滤条件")
        return false
    }
    try {
        if IniRead(jobFile, "active", "job_signature", "") != expectedSignature {
            autoTip("当前图纸任务已变化；未设置颜色过滤")
            return false
        }
        workFile := IniRead(jobFile, "active", "working_file", "")
        mainHwnd := findUniqueWorkWindow(workFile)
        if !mainHwnd || !titleHasExactWorkFile(WinGetTitle("ahk_id " mainHwnd), workFile) {
            autoTip("未能唯一定位当前工作副本；未设置颜色过滤")
            return false
        }
        baselineCount := readSelectedEntityCount(mainHwnd)
        if sourceColor != "全部颜色" && baselineCount > 0 {
            autoTip("请先按 Esc 清除旧选集，再点击颜色按钮；避免把旧选集误归到新颜色")
            return false
        }
        dialogHwnd := findPickFilterDialog(expectedSignature, workFile, mainHwnd)
        if !dialogHwnd {
            if !runPublishedNativeCommand(expectedSignature, "objectset", "打开拾取过滤设置")
                return false
            dialogHwnd := findPickFilterDialog(expectedSignature, workFile, mainHwnd)
        }
        if !dialogHwnd {
            autoTip("未找到拾取过滤设置窗口；没有修改任何过滤条件")
            return false
        }
        pid := WinGetPID("ahk_id " mainHwnd)
        if !verifyBeforeAction(expectedSignature)
          || !WinExist("ahk_id " dialogHwnd)
          || WinGetPID("ahk_id " dialogHwnd) != pid
          || !titleHasExactWorkFile(WinGetTitle("ahk_id " mainHwnd), workFile) {
            autoTip("拾取过滤窗口身份核验失败；未修改过滤条件")
            return false
        }
        WinActivate("ahk_id " dialogHwnd)
        if !WinWaitActive("ahk_id " dialogHwnd, , 2) || WinGetID("A") != dialogHwnd {
            autoTip("无法激活拾取过滤设置窗口；未修改过滤条件")
            return false
        }

        controls := WinGetControls("ahk_id " dialogHwnd)
        items := []
        colorGroup := 0
        for ctrl in controls {
            try {
                controlHwnd := ControlGetHwnd(ctrl, "ahk_id " dialogHwnd)
                label := ControlGetText(ctrl, "ahk_id " dialogHwnd)
                className := WinGetClass("ahk_id " controlHwnd)
                ControlGetPos(&x, &y, &w, &h, ctrl, "ahk_id " dialogHwnd)
                checked := -1
                try checked := ControlGetChecked(ctrl, "ahk_id " dialogHwnd)
                item := Map("ctrl", ctrl, "text", normalizeFilterLabel(label),
                    "class", className, "x", x, "y", y, "w", w, "h", h,
                    "checked", checked)
                items.Push(item)
                if item["text"] = "颜色" && className = "Button" && w > 100 && h > 100
                    colorGroup := item
            } catch {
            }
        }
        if !colorGroup {
            autoTip("未识别 CAXA 颜色过滤列表控件；未修改过滤条件")
            probePickFilterDialog(expectedSignature, sourceColor)
            return false
        }
        gx := colorGroup["x"], gy := colorGroup["y"]
        gr := gx + colorGroup["w"], gb := gy + colorGroup["h"]
        allButton := "", noneButton := ""
        for item in items {
            cx := item["x"] + item["w"] / 2
            cy := item["y"] + item["h"] / 2
            if cx < gx || cx > gr || cy < gy || cy > gb
                continue
            if InStr(item["text"], "全有")
                allButton := item["ctrl"]
            else if InStr(item["text"], "全无")
                noneButton := item["ctrl"]
        }
        if allButton = "" || noneButton = "" {
            autoTip("未识别颜色列表的“全有/全无”按钮；未修改过滤条件")
            probePickFilterDialog(expectedSignature, sourceColor)
            return false
        }

        expectedKeys := ["红", "黄", "绿", "青", "蓝", "洋红", "白", "黑"]
        colorControlMap := Map()
        for item in items {
            key := filterColorKey(item["text"])
            if key = ""
                continue
            if colorControlMap.Has(key) {
                autoTip("颜色列表中【" key "】出现重复标签；未修改过滤条件")
                return false
            }
            checkbox := findFilterCheckbox(item, items, gx, gy, gr, gb)
            if checkbox = "" {
                autoTip("无法将【" item["text"] "】文字与复选框对应；未修改过滤条件")
                probePickFilterDialog(expectedSignature, sourceColor)
                return false
            }
            colorControlMap[key] := checkbox
        }
        for key in expectedKeys {
            if !colorControlMap.Has(key) {
                autoTip("未识别完整的标准颜色列表；请将颜色列表滚动到顶部后重试，未修改过滤条件")
                probePickFilterDialog(expectedSignature, sourceColor)
                return false
            }
        }

        wanted := []
        if sourceColor = "红色"
            wanted := ["红"]
        else if sourceColor = "绿色"
            wanted := ["绿"]
        else if sourceColor = "蓝色"
            wanted := ["蓝"]
        else if sourceColor = "洋红色"
            wanted := ["洋红"]
        else if sourceColor = "白色+黑白色"
            wanted := ["白", "黑"]
        else if sourceColor = "全部颜色"
            wanted := expectedKeys

        if !verifyBeforeAction(expectedSignature)
          || !WinExist("ahk_id " dialogHwnd)
          || WinGetPID("ahk_id " dialogHwnd) != pid
          || !titleHasExactWorkFile(WinGetTitle("ahk_id " mainHwnd), workFile) {
            autoTip("颜色过滤最终核验失败；未修改过滤条件")
            return false
        }

        if sourceColor = "全部颜色" {
            ControlClick(allButton, "ahk_id " dialogHwnd)
            Sleep 120
            for key in expectedKeys {
                state := -1
                try state := ControlGetChecked(colorControlMap[key], "ahk_id " dialogHwnd)
                if state != 1 {
                    autoTip("恢复全选后颜色状态读回不一致；请人工检查过滤窗口")
                    probePickFilterDialog(expectedSignature, sourceColor)
                    return false
                }
            }
            autoTip("已恢复颜色列表全选；请在 CAXA 过滤窗口点击“确定”")
            return true
        }

        ControlClick(noneButton, "ahk_id " dialogHwnd)
        Sleep 100
        for key in expectedKeys {
            state := -1
            try state := ControlGetChecked(colorControlMap[key], "ahk_id " dialogHwnd)
            if state != 0 {
                autoTip("颜色列表“全无”状态未能核实；未继续勾选")
                probePickFilterDialog(expectedSignature, sourceColor)
                return false
            }
        }
        for target in wanted {
            ctrl := colorControlMap[target]
            ControlClick(ctrl, "ahk_id " dialogHwnd)
            Sleep 80
            state := -1
            try state := ControlGetChecked(ctrl, "ahk_id " dialogHwnd)
            if state != 1 {
                autoTip("颜色复选框状态读回失败；请人工检查过滤窗口")
                probePickFilterDialog(expectedSignature, sourceColor)
                return false
            }
        }
        for key in expectedKeys {
            expectedState := 0
            for target in wanted {
                if target = key {
                    expectedState := 1
                    break
                }
            }
            state := -1
            try state := ControlGetChecked(colorControlMap[key], "ahk_id " dialogHwnd)
            if state != expectedState {
                autoTip("颜色筛选最终状态不一致；请检查过滤窗口，未继续操作")
                probePickFilterDialog(expectedSignature, sourceColor)
                return false
            }
        }
        if !verifyBeforeAction(expectedSignature)
          || !WinExist("ahk_id " dialogHwnd)
          || WinGetPID("ahk_id " dialogHwnd) != pid
          || !titleHasExactWorkFile(WinGetTitle("ahk_id " mainHwnd), workFile) {
            autoTip("颜色过滤设置后任务窗口发生变化；请检查当前过滤窗口")
            return false
        }
        lastPickFilterSignature := expectedSignature
        lastPickFilterSource := sourceColor
        lastPickFilterBaselineCount := baselineCount
        lastPickFilterTick := A_TickCount
        autoTip("已自动设置" sourceColor "过滤；请在 CAXA 对话框点击“确定”，再框选对象")
        return true
    } catch as e {
        autoTip("自动设置颜色过滤失败：" e.Message "；未继续操作")
        try probePickFilterDialog(expectedSignature, sourceColor)
        return false
    }
}


readPropertyPaneText(mainHwnd) {
    try return WinGetText("ahk_id " mainHwnd)
    catch
        return ""
}

readSelectedEntityCount(mainHwnd) {
    for ctrl in WinGetControls("ahk_id " mainHwnd) {
        try {
            value := ControlGetText(ctrl, "ahk_id " mainHwnd)
            if RegExMatch(value, "全部\s*[（(]\s*([0-9]+)\s*[）)]", &match) {
                count := Integer(match[1])
                if count > 0
                    return count
            }
        } catch {
        }
    }
    value := readPropertyPaneText(mainHwnd)
    if RegExMatch(value, "全部\s*[（(]\s*([0-9]+)\s*[）)]", &match) {
        count := Integer(match[1])
        if count > 0
            return count
    }
    return 0
}

readSelectedLinetypeScale(mainHwnd) {
    value := readPropertyPaneText(mainHwnd)
    if RegExMatch(value, "线型比例\s*([0-9]+(?:\.[0-9]+)?)", &match)
        return Float(match[1])
    return ""
}

; One-time, non-clicking calibration of the four standard property-toolbar combos.
beginPropertyComboCalibration(expectedSignature, slot, label) {
    global jobFile, cadExe, calibrationBusy, isPaused
    if isPaused || cadExe = "" || calibrationBusy {
        autoTip("CAD 辅助已暂停、未连接，或已有校准正在进行")
        return false
    }
    allowed := Map("layerCombo", true, "colorCombo", true,
        "linetypeCombo", true, "lineweightCombo", true)
    if !allowed.Has(slot) || !FileExist(jobFile)
      || IniRead(jobFile, "active", "job_signature", "") != expectedSignature {
        autoTip("当前任务或属性校准类型无效；未启动校准")
        return false
    }
    workFile := IniRead(jobFile, "active", "working_file", "")
    mainHwnd := findUniqueWorkWindow(workFile)
    if !mainHwnd || !verifyBeforeAction(expectedSignature) {
        autoTip("无法唯一定位当前工作副本；校准已取消")
        return false
    }
    try {
        WinActivate("ahk_id " mainHwnd)
        if !WinWaitActive("ahk_id " mainHwnd, , 2)
          || WinGetID("A") != mainHwnd
          || !titleHasExactWorkFile(WinGetTitle("ahk_id " mainHwnd), workFile) {
            autoTip("无法激活当前工作副本；校准已取消")
            return false
        }
        title := WinGetTitle("ahk_id " mainHwnd)
        className := WinGetClass("ahk_id " mainHwnd)
        calibrationBusy := true
        ToolTip("请在 8 秒内把鼠标移到 CAXA【常用】选项卡中的“" label "”属性下拉框上，不要点击。")
        SetTimer(() => ToolTip(), -8200)
        SetTimer(FinishPropertyComboCalibration.Bind(mainHwnd, expectedSignature,
            slot, label, title, className, workFile), -8000)
        return true
    } catch as e {
        calibrationBusy := false
        autoTip("启动属性栏校准失败：" e.Message)
        return false
    }
}

FinishPropertyComboCalibration(mainHwnd, expectedSignature, slot, label, title, className, workFile) {
    global cfgFile, jobFile, calibrationBusy
    calibrationBusy := false
    try {
        if !WinExist("ahk_id " mainHwnd)
          || WinGetID("A") != mainHwnd
          || WinGetTitle("ahk_id " mainHwnd) != title
          || WinGetClass("ahk_id " mainHwnd) != className
          || !titleHasExactWorkFile(WinGetTitle("ahk_id " mainHwnd), workFile)
          || !FileExist(jobFile)
          || IniRead(jobFile, "active", "job_signature", "") != expectedSignature
          || !verifyBeforeAction(expectedSignature) {
            autoTip("校准期间图纸或窗口发生变化；未保存控件")
            return false
        }
        MouseGetPos(&x, &y, &hoverHwnd, &controlName, 2)
        if hoverHwnd != mainHwnd || controlName = "" {
            autoTip("鼠标未停在 CAXA 属性下拉框上；未保存校准")
            return false
        }
        controlHwnd := ControlGetHwnd(controlName, "ahk_id " mainHwnd)
        if !controlHwnd {
            autoTip("未识别到【" label "】下拉框；未保存校准")
            return false
        }
        controlClass := WinGetClass("ahk_id " controlHwnd)
        if controlClass != "ComboBox" && controlClass != "ComboBoxEx32" {
            autoTip("【" label "】不是受支持的标准下拉框；不会猜测坐标修改")
            return false
        }
        IniWrite controlName, cfgFile, slot, "control"
        IniWrite controlClass, cfgFile, slot, "control_class"
        IniWrite className, cfgFile, slot, "class"
        IniWrite title, cfgFile, slot, "title"
        autoTip("【" label "】属性下拉框校准完成")
        return true
    } catch as e {
        autoTip("保存属性栏校准失败：" e.Message)
        return false
    }
}

isPropertyComboSlot(slot) {
    return slot = "layerCombo" || slot = "colorCombo"
        || slot = "linetypeCombo" || slot = "lineweightCombo"
}

comboHasExactItem(ctrl, hwnd, wanted) {
    try items := ControlGetItems(ctrl, "ahk_id " hwnd)
    catch
        return false
    for item in items {
        if StrLower(Trim(item)) = StrLower(wanted)
            return true
    }
    return false
}

; Apply the Excel-selected target layer and ByLayer overrides to the current
; CAXA selection. No modal confirmation, no new selection, and no save.
applyColorLayer(expectedSignature, targetLayer, targetColor, targetLinetype, linetypeScale, targetLineweight) {
    global jobFile, cadExe, cfgFile, isPaused
    if isPaused || !FileExist(jobFile) || cadExe = "" {
        autoTip("CAD 辅助已暂停或没有活动工作副本；未修改选集")
        return false
    }
    if targetLayer = "" || StrLen(targetLayer) > 64
      || RegExMatch(targetLayer, "[\r\n\t=;#\[\]|]")
      || targetColor = "" || targetLinetype = "" || targetLineweight = ""
      || !IsNumber(linetypeScale) || Float(linetypeScale) <= 0 {
        autoTip("Excel 特性规则缺少有效目标值；已拒绝修改")
        return false
    }
    try {
        sig := IniRead(jobFile, "active", "job_signature", "")
        workFile := IniRead(jobFile, "active", "working_file", "")
        if sig != expectedSignature || workFile = "" {
            autoTip("当前图纸任务与面板请求不一致；未修改属性")
            return false
        }
        hwnd := findUniqueWorkWindow(workFile)
        if !hwnd || StrLower(WinGetProcessName("ahk_id " hwnd)) != StrLower(cadExe)
          || !jobWindowMatches(hwnd, workFile) {
            autoTip("未能唯一定位当前工作副本；未修改属性")
            return false
        }
        if !verifyBeforeAction(sig) || !FileExist(jobFile)
          || IniRead(jobFile, "active", "job_signature", "") != sig
          || !WinExist("ahk_id " hwnd) || !jobWindowMatches(hwnd, workFile) {
            autoTip("归层前安全核验未通过；未修改属性")
            return false
        }
        selectionCount := readSelectedEntityCount(hwnd)
        if selectionCount < 1 {
            autoTip("左侧特性栏未识别到非空选集；请先框选对象并保持特性栏打开，未修改属性")
            return false
        }
        targetScale := Float(linetypeScale)
        currentScale := readSelectedLinetypeScale(hwnd)
        if currentScale = "" {
            autoTip("无法从左侧特性栏读取选集线型比例；未修改任何属性")
            return false
        }
        if Abs(currentScale - targetScale) > 0.000001 {
            autoTip("选集线型比例为 " currentScale "，Excel 要求 " targetScale "；当前未自动改写比例，未修改其他属性")
            return false
        }
        fieldPlan := [
            Map("slot","colorCombo","value",targetColor,"label","颜色"),
            Map("slot","linetypeCombo","value",targetLinetype,"label","线型"),
            Map("slot","lineweightCombo","value",targetLineweight,"label","线宽"),
            Map("slot","layerCombo","value",targetLayer,"label","图层")
        ]
        ; Preflight every control and target item before changing the selection.
        seenControlHandles := Map()
        for field in fieldPlan {
            slot := field["slot"]
            ctrl := IniRead(cfgFile, slot, "control", "")
            expectedClass := IniRead(cfgFile, slot, "control_class", "")
            if ctrl = "" || (expectedClass != "ComboBox" && expectedClass != "ComboBoxEx32") {
                autoTip("首次使用请在设置中校准【" field["label"] "】属性下拉框；未修改选集")
                return false
            }
            ctrlHwnd := 0
            try ctrlHwnd := ControlGetHwnd(ctrl, "ahk_id " hwnd)
            if !ctrlHwnd || WinGetClass("ahk_id " ctrlHwnd) != expectedClass
              || !DllCall("IsWindowVisible", "ptr", ctrlHwnd, "int") {
                autoTip("【" field["label"] "】属性下拉框与校准状态不符或不可见；未修改选集")
                return false
            }
            if seenControlHandles.Has(ctrlHwnd) {
                autoTip("多个属性项指向同一个 CAXA 下拉框；校准可能重复，未修改选集")
                return false
            }
            seenControlHandles[ctrlHwnd] := field["label"]
            if !comboHasExactItem(ctrl, hwnd, field["value"]) {
                autoTip("【" field["label"] "】下拉框中找不到【" field["value"] "】；未修改选集")
                return false
            }
        }
        WinActivate("ahk_id " hwnd)
        if !WinWaitActive("ahk_id " hwnd, , 2) || WinGetID("A") != hwnd
          || !jobWindowMatches(hwnd, workFile)
          || !verifyBeforeAction(sig) {
            autoTip("属性修改前最终安全核验未通过；未修改选集")
            return false
        }
        for field in fieldPlan {
            slot := field["slot"]
            ctrl := IniRead(cfgFile, slot, "control", "")
            value := field["value"]
            ControlChooseString value, ctrl, "ahk_id " hwnd
            Sleep 120
            observed := Trim(ControlGetText(ctrl, "ahk_id " hwnd))
            if StrLower(observed) != StrLower(value) {
                autoTip("【" field["label"] "】读回不一致；可能尚未修改或已部分修改，请检查左侧特性栏")
                return false
            }
            if WinGetID("A") != hwnd || !jobWindowMatches(hwnd, workFile) {
                autoTip("属性修改期间 CAXA 窗口发生变化；请检查左侧特性栏")
                return false
            }
            currentCount := readSelectedEntityCount(hwnd)
            if currentCount != selectionCount {
                autoTip("修改期间选集数量发生变化；请检查左侧特性栏，可能已部分修改")
                return false
            }
        }
        autoTip("已向当前 " selectionCount " 个选中对象写入 Excel 特性；线型比例 " targetScale " 已核对。请检查左侧特性栏，未自动保存")
        return true
    } catch as e {
        autoTip("一键设置特性失败：" e.Message "；请检查左侧特性栏")
        return false
    }
}

; Read-only, targeted diagnostics for the native CAXA pick-filter dialog.
; Only the dialog's control labels, IDs, classes, states and geometry are read.
; No drawing text, entity data, screenshots, clicks or property changes are captured.
probePickFilterDialog(expectedSignature, sourceColor := "") {
    global jobFile, cadExe, dataDir, isPaused
    if isPaused || cadExe = "" || !FileExist(jobFile)
        return false
    workFile := IniRead(jobFile, "active", "working_file", "")
    if workFile = "" || !verifyBeforeAction(expectedSignature)
        return false
    mainHwnd := findUniqueWorkWindow(workFile)
    if !mainHwnd || !titleHasExactWorkFile(WinGetTitle("ahk_id " mainHwnd), workFile)
        return false
    pid := WinGetPID("ahk_id " mainHwnd)
    Sleep 350
    dialogHwnd := 0
    for hwnd in WinGetList("ahk_pid " pid) {
        try {
            title := WinGetTitle("ahk_id " hwnd)
            if InStr(title, "拾取过滤") {
                dialogHwnd := hwnd
                break
            }
        } catch {
        }
    }
    if !dialogHwnd {
        autoTip("已打开 CAXA 拾取设置，但未定位到独立的“拾取过滤”窗口；未读取或更改任何控件")
        return false
    }
    if !verifyBeforeAction(expectedSignature)
      || !WinExist("ahk_id " dialogHwnd)
      || WinGetPID("ahk_id " dialogHwnd) != pid
      || !titleHasExactWorkFile(WinGetTitle("ahk_id " mainHwnd), workFile) {
        autoTip("拾取过滤对话框身份核验未通过；未读取控件")
        return false
    }
    report := "CAXA 拾取过滤对话框只读诊断" . Chr(13) . Chr(10)
    report .= "工作副本：" . workFile . Chr(13) . Chr(10)
    report .= "面板选择颜色：" . sourceColor . Chr(13) . Chr(10)
    report .= "窗口标题：" . WinGetTitle("ahk_id " dialogHwnd) . Chr(13) . Chr(10)
    report .= "仅包含该对话框的控件文字、类别、ID、勾选状态与位置；没有读取图纸内容。" . Chr(13) . Chr(10) . Chr(13) . Chr(10)
    try controls := WinGetControls("ahk_id " dialogHwnd)
    catch {
        autoTip("拾取过滤对话框控件枚举失败；未保存报告")
        return false
    }
    for index, ctrl in controls {
        try {
            controlHwnd := ControlGetHwnd(ctrl, "ahk_id " dialogHwnd)
            controlText := ""
            controlClass := "unavailable"
            controlId := "unavailable"
            checked := "n/a"
            itemsText := ""
            try controlText := ControlGetText(ctrl, "ahk_id " dialogHwnd)
            try controlClass := WinGetClass("ahk_id " controlHwnd)
            try controlId := String(DllCall("GetDlgCtrlID", "Ptr", controlHwnd, "Int"))
            try checked := String(ControlGetChecked(ctrl, "ahk_id " dialogHwnd))
            try {
                items := ControlGetItems(ctrl, "ahk_id " dialogHwnd)
                for _, item in items
                    itemsText .= (itemsText = "" ? "" : " | ") . item
            }
            cx := 0, cy := 0, cw := 0, ch := 0
            try ControlGetPos(&cx, &cy, &cw, &ch, ctrl, "ahk_id " dialogHwnd)
            report .= "#" . index . " | " . ctrl . " | HWND=" . controlHwnd
                . " | ID=" . controlId . " | Class=" . controlClass
                . " | Checked=" . checked . " | Rect=" . cx . "," . cy . "," . cw . "," . ch
                . " | Text=" . StrReplace(StrReplace(controlText, Chr(13), " "), Chr(10), " ")
                . " | Items=" . itemsText
                . Chr(13) . Chr(10)
        } catch as e {
            report .= "#" . index . " | " . ctrl . " | read error: " . e.Message . Chr(13) . Chr(10)
        }
    }
    if !verifyBeforeAction(expectedSignature)
      || !WinExist("ahk_id " dialogHwnd)
      || WinGetPID("ahk_id " dialogHwnd) != pid {
        autoTip("拾取过滤诊断期间窗口发生变化；报告未保存")
        return false
    }
    reportPath := dataDir "\pick_filter_dialog_probe.txt"
    try {
        if FileExist(reportPath)
            FileDelete reportPath
        FileAppend(report, reportPath, "UTF-8")
        autoTip("拾取过滤对话框诊断已保存到助手数据目录；未更改任何设置")
        return true
    } catch as e {
        autoTip("诊断报告保存失败：" . e.Message)
        return false
    }
}

; or edits properties. Commands are allow-listed and bound to the published
; work-copy window and the live workbench lease.
runPublishedNativeCommand(expectedSignature, command, label) {
    global jobFile, isPaused, cadExe
    allowed := Map("objectset", true)
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
; Automatic name-field filling is disabled; copy the verified name from the assistant and paste it manually.



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
    global galleryFillPendingSignature, galleryFillPendingSince, galleryDialogNoticeShown
    guideMainHwnd := 0
    guideItems := []
    guideIndex := 0
    guideFilename := ""
    guideSignature := ""
    guideWorkFile := ""
    guidePlan := ""
    galleryFillPendingSignature := ""
    galleryFillPendingSince := 0
    galleryDialogNoticeShown := false
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
