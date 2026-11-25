; Read-only document-caption identity helper shared by the main macro and
; the no-CAD Windows smoke test. A CAXA window caption is NOT a CAD API:
; captions that don't expose an unambiguous filename must fail closed.
;
; A plain InStr(title, "A.exb") matches "备份A.exb" and "BA.exb" too.
; Reject adjacent Unicode letters/digits and common filename characters
; on BOTH sides of the entire .exb filename (not just after .exb).
titleHasExactWorkFile(title, file) {
    if file = "" || !RegExMatch(file, "i)\.exb$")
        return false
    lowerTitle := StrLower(title)
    lowerFile := StrLower(file)
    searchFrom := 1
    Loop {
        at := InStr(lowerTitle, lowerFile, true, searchFrom)
        if at = 0
            return false
        before := at > 1 ? SubStr(lowerTitle, at - 1, 1) : ""
        afterPos := at + StrLen(lowerFile)
        after := afterPos <= StrLen(lowerTitle) ? SubStr(lowerTitle, afterPos, 1) : ""
        ; Filename characters on either side mean that this is a SUBSTRING.
        ; The Unicode categories prevent 备份A.exb matching A.exb.
        if (before = "" || !RegExMatch(before, "^[\p{L}\p{N}_.-]$")) && (after = "" || !RegExMatch(after, "^[\p{L}\p{N}_.-]$"))
            return true
        ; The first hit may be embedded but a later one may be the real EXB.
        searchFrom := at + 1
    }
}
