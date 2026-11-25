@echo off
setlocal EnableExtensions DisableDelayedExpansion
pushd "%~dp0" >nul 2>&1
if errorlevel 1 goto PATH_ERROR

echo ==========================================
echo CAXA Library Helper - migrate to E:
echo ==========================================
echo.
echo This tool copies the Git repository and private UserData to the E: drive.
echo The destination folder is configured inside the Python migration tool.
echo.
echo The original C: files will NOT be deleted.
echo Close the CAXA helper panel. If the AutoHotkey tray icon remains, exit it first.
echo.

if not exist "devtools\migrate_to_e.py" goto MISSING_SCRIPT

set "PY="
where py.exe >nul 2>&1
if not errorlevel 1 (
    py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>&1
    if not errorlevel 1 set "PY=py -3"
)
if not defined PY (
    where python.exe >nul 2>&1
    if not errorlevel 1 (
        python -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>&1
        if not errorlevel 1 set "PY=python"
    )
)
if not defined PY goto NO_PYTHON

rem Check E: through Python to avoid CMD drive-root sentinel issues.
%PY% -c "import os,sys; sys.exit(0 if os.path.isdir('E:/') else 1)" >nul 2>&1
if errorlevel 1 goto NO_E_DRIVE

rem Let Python resolve the Unicode destination path; do not pass it through CMD.
%PY% "devtools\migrate_to_e.py"
set "RC=%ERRORLEVEL%"
echo.
if "%RC%"=="0" (
    echo Migration finished. Your original C: files were kept.
) else (
    echo Migration stopped. No original C: files were deleted.
)
echo.
pause
popd
exit /b %RC%

:NO_E_DRIVE
echo ERROR: Python cannot access the E: drive from this session.
echo Check whether E: is connected and accessible in File Explorer.
goto FAIL

:MISSING_SCRIPT
echo ERROR: devtools\migrate_to_e.py is missing.
goto FAIL

:NO_PYTHON
echo ERROR: Python 3.10 or newer was not found.
goto FAIL

:PATH_ERROR
echo ERROR: Windows could not open this folder.
pause
exit /b 1

:FAIL
pause
popd
exit /b 1
