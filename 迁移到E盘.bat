@echo off
setlocal EnableExtensions DisableDelayedExpansion
pushd "%~dp0" >nul 2>&1
if errorlevel 1 goto PATH_ERROR

echo ==========================================
echo CAXA Library Helper - migrate to E:
echo ==========================================
echo.
echo This tool copies the Git repository and private UserData to:
echo E:\CAXA助手
echo.
echo The original C: files will NOT be deleted.
echo Close the CAXA helper panel before continuing.
echo.

if not exist "E:\NUL" goto NO_E_DRIVE
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

%PY% "devtools\migrate_to_e.py" --target-root "E:\CAXA助手"
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
echo ERROR: E: drive was not found.
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
