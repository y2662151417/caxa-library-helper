@echo off
setlocal EnableExtensions DisableDelayedExpansion

rem Use the batch file's own folder. Do not rely on the caller's working directory.
pushd "%~dp0" >nul 2>&1
if errorlevel 1 goto PATH_ERROR

rem A migrated E: installation has a marker beside the repository.
rem The original C: installation keeps using its existing LOCALAPPDATA data.
set "CAXA_HELPER_DATA_DIR="
if exist "%~dp0..\UserData\.caxa_userdata.json" (
    for %%I in ("%~dp0..\UserData") do set "CAXA_HELPER_DATA_DIR=%%~fI"
)
if not defined CAXA_HELPER_DATA_DIR (
    if defined LOCALAPPDATA set "CAXA_HELPER_DATA_DIR=%LOCALAPPDATA%\CAXA_Library_Helper"
)
if not defined CAXA_HELPER_DATA_DIR goto DATA_ERROR

if not exist "%CAXA_HELPER_DATA_DIR%\logs\NUL" mkdir "%CAXA_HELPER_DATA_DIR%\logs" >nul 2>&1
if not exist "%CAXA_HELPER_DATA_DIR%\logs\NUL" goto LOG_ERROR
set "LOG=%CAXA_HELPER_DATA_DIR%\logs\startup.log"

> "%LOG%" echo [START] %DATE% %TIME%
>>"%LOG%" echo [START] Install folder: %CD%
>>"%LOG%" echo [START] User data: %CAXA_HELPER_DATA_DIR%
echo CAXA Library Helper - startup check

echo Checking program files...
if not exist "runtime\launcher.py" goto MISSING_RUNTIME
if not exist "app\app.py" goto MISSING_APP

set "PY="
where py.exe >nul 2>&1
if not errorlevel 1 (
    py -3 -c "import sys, tkinter; print('Python:',sys.version); print('Tkinter: OK'); sys.exit(0 if sys.version_info >= (3,10) else 1)" >>"%LOG%" 2>&1
    if not errorlevel 1 set "PY=py -3"
)

if not defined PY (
    where python.exe >nul 2>&1
    if not errorlevel 1 (
        python -c "import sys, tkinter; print('Python:',sys.version); print('Tkinter: OK'); sys.exit(0 if sys.version_info >= (3,10) else 1)" >>"%LOG%" 2>&1
        if not errorlevel 1 set "PY=python"
    )
)

if not defined PY goto NO_PYTHON

>>"%LOG%" echo [START] Python command: %PY%
echo Checking GitHub update source...
if not exist "updates\update_source.json" (
    %PY% -c "import json,pathlib; p=pathlib.Path('updates/update_source.json'); d={'app_id':'CAXA_Library_Helper','channel':'stable','auto_check':True,'timeout_seconds':3,'manifest_url':'https://raw.githubusercontent.com/y2662151417/caxa-library-helper/main/updates/manifest.json'}; p.parent.mkdir(parents=True,exist_ok=True); p.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')" >>"%LOG%" 2>&1
    if errorlevel 1 goto CONFIG_ERROR
)

>>"%LOG%" echo [START] Launching runtime\launcher.py
echo Starting CAXA Library Helper...
%PY% "runtime\launcher.py" >>"%LOG%" 2>&1
set "RC=%ERRORLEVEL%"
if "%RC%"=="0" goto DONE
>>"%LOG%" echo [ERROR] Launcher exit code: %RC%
echo Startup failed. Details are shown below.
goto SHOW_LOG

:NO_PYTHON
>>"%LOG%" echo [ERROR] Python 3.10+ with Tkinter was not found.
echo Python 3.10+ with Tkinter was not found.
echo Install Python with Tcl/Tk, then run this file again.
goto SHOW_LOG

:MISSING_RUNTIME
>>"%LOG%" echo [ERROR] runtime\launcher.py is missing.
echo Missing file: runtime\launcher.py
goto SHOW_LOG

:MISSING_APP
>>"%LOG%" echo [ERROR] app\app.py is missing.
echo Missing file: app\app.py
goto SHOW_LOG

:CONFIG_ERROR
>>"%LOG%" echo [ERROR] Could not write updates\update_source.json.
echo Could not configure the GitHub update source.
goto SHOW_LOG

:DATA_ERROR
echo ERROR: Could not determine the CAXA user-data directory.
echo Check LOCALAPPDATA or complete the E: migration first.
pause
popd
exit /b 1

:PATH_ERROR
echo ERROR: Windows could not open the folder containing this BAT file.
echo Do not move this BAT file away from the app, runtime, logs and updates folders.
pause
exit /b 1

:LOG_ERROR
echo ERROR: Cannot create or access the user-data logs folder.
echo Check whether the selected drive is writable or blocked by Windows security.
pause
popd
exit /b 1

:SHOW_LOG
echo.
echo ---------------- startup.log ----------------
type "%LOG%"
echo.
echo Log file: %LOG%
pause
popd
exit /b 1

:DONE
popd
exit /b 0
