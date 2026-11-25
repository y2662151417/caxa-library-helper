#Requires AutoHotkey v2.0
#SingleInstance Force
#Include %A_ScriptDir%\CAXA_标题匹配.ahk

; Standalone Windows smoke test. Does not launch CAXA or read any EXB.
; It checks the SAME helper included by CAXA_半自动辅助.ahk.
cases := [
    ["A.exb - CAXA", "A.exb", true],
    ["备份A.exb - CAXA", "A.exb", false],
    ["备份-A.exb - CAXA", "A.exb", false],
    ["BA.exb - CAXA", "A.exb", false],
    ["A.exb.bak - CAXA", "A.exb", false],
    ["A.exbx - CAXA", "A.exb", false],
    ["A.EXB - CAXA", "a.exb", true],
    ["C:\图纸\A.exb - CAXA", "A.exb", true],
    ["备份A.exb | A.exb - CAXA", "A.exb", true],
    ["错误.EXB - CAXA", "A.exb", false],
    ["A.exb - CAXA", "A", false]
]
for index, item in cases {
    actual := titleHasExactWorkFile(item[1], item[2])
    if actual != item[3] {
        MsgBox "标题匹配自测失败，样例 " index "：" item[1], "AHK v2 本地自测", "Iconx"
        ExitApp 1
    }
}
MsgBox "标题匹配自测通过（" cases.Length " 例）。这不是 CAXA 实机验收。", "AHK v2 本地自测"
ExitApp 0