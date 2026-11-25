; AHK v2 helper for an operator-acknowledged view-guide checkpoint.
; It records ONLY the manual guide cursor, never CAD object/command state.
; No EXB content is read, no CAD keys are sent, no gallery is submitted.
;
guideCheckpointSave(path, signature, workingFile, plan, cursor, count) {
    if !RegExMatch(signature, "^[0-9a-f]{64}$") || workingFile = "" || plan = ""
        return false
    if !IsInteger(cursor) || !IsInteger(count) || count < 1 || count > 6 || cursor < 1 || cursor > count + 1
        return false
    ; Write a new checkpoint and replace the old one only once all fields exist.
    ; A partial/invalid checkpoint is never accepted by guideCheckpointRead.
    currentPid := DllCall("GetCurrentProcessId", "UInt")
    tmp := path ".pending_" currentPid "_" A_TickCount
    try {
        if FileExist(tmp)
            FileDelete tmp
        IniWrite signature, tmp, "guide", "signature"
        IniWrite workingFile, tmp, "guide", "working_file"
        IniWrite plan, tmp, "guide", "view_plan"
        IniWrite cursor, tmp, "guide", "cursor"
        IniWrite count, tmp, "guide", "count"
        FileMove tmp, path, true
        return true
    } catch {
        try {
            if FileExist(tmp)
                FileDelete tmp
        }
        return false
    }
}

guideCheckpointRead(path, signature, workingFile, plan, count) {
    ; 0 means missing, invalid, or a different task: never auto-resume.
    if !FileExist(path) || !RegExMatch(signature, "^[0-9a-f]{64}$")
        return 0
    if workingFile = "" || plan = "" || !IsInteger(count) || count < 1 || count > 6
        return 0
    try {
        if IniRead(path, "guide", "signature", "") != signature
          || IniRead(path, "guide", "working_file", "") != workingFile
          || IniRead(path, "guide", "view_plan", "") != plan
          || IniRead(path, "guide", "count", "") != (count "")
            return 0
        saved := IniRead(path, "guide", "cursor", "")
        if !RegExMatch(saved, "^[1-7]$")
            return 0
        index := Integer(saved)
        return index <= count + 1 ? index : 0
    } catch {
        return 0
    }
}

guideCheckpointClear(path) {
    try {
        if FileExist(path)
            FileDelete path
        return true
    } catch {
        return false
    }
}
