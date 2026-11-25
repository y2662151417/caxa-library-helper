#Requires AutoHotkey v2.0
#SingleInstance Force
#Include %A_ScriptDir%\CAXA_视图断点.ahk

; Executes the SAME persistence code as the live helper, with fabricated data.
; Never opens/reads an EXB and never sends CAD keys, mouse clicks, or network calls.
testFile := A_Temp "\CAXA_guide_checkpoint_test_" DllCall("GetCurrentProcessId", "UInt") ".ini"
sig := "a" . "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
; Exactly 64 hex digits: a + 63 b.
workFile := "D-001_虚构图__图库制作.exb"
plan := "主视图·带尺寸|俯视图·带尺寸|左视图·带尺寸"
checks := 0
try {
    if !guideCheckpointSave(testFile, sig, workFile, plan, 2, 3)
        throw Error("checkpoint did not save")
    if guideCheckpointRead(testFile, sig, workFile, plan, 3) != 2
        throw Error("valid resume point was not restored")
    checks += 1
    if guideCheckpointRead(testFile, "c" . SubStr(sig, 2), workFile, plan, 3) != 0
        throw Error("other job signature was accepted")
    checks += 1
    if guideCheckpointRead(testFile, sig, "OTHER.exb", plan, 3) != 0
        throw Error("other working file was accepted")
    checks += 1
    if guideCheckpointRead(testFile, sig, workFile, plan "|extra", 3) != 0
        throw Error("other view order was accepted")
    checks += 1
    if guideCheckpointRead(testFile, sig, workFile, plan, 4) != 0
        throw Error("other count was accepted")
    checks += 1
    if guideCheckpointSave(testFile, sig, workFile, plan, 5, 3)
        throw Error("out of range cursor was saved")
    checks += 1
    if !guideCheckpointSave(testFile, sig, workFile, plan, 4, 3)
       || guideCheckpointRead(testFile, sig, workFile, plan, 3) != 4
        throw Error("all-views-acknowledged cursor was lost")
    checks += 1
    IniWrite "N/A", testFile, "guide", "cursor"
    if guideCheckpointRead(testFile, sig, workFile, plan, 3) != 0
        throw Error("invalid cursor was accepted")
    checks += 1
    if !guideCheckpointClear(testFile) || guideCheckpointRead(testFile, sig, workFile, plan, 3) != 0
        throw Error("end guide did not clear checkpoint")
    checks += 1
    MsgBox "视图断点自测通过（" checks " 项）。仅是 AHK v2 离线检查，不代表已在 CAXA 中执行任何图符操作。", "无 CAD 自测"
    ExitApp 0
} catch as e {
    guideCheckpointClear(testFile)
    MsgBox "视图断点自测失败：" e.Message, "无 CAD 自测", "Iconx"
    ExitApp 1
}
