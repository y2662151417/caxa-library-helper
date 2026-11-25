@echo off
setlocal EnableExtensions DisableDelayedExpansion

rem Use the batch file's own folder. Do not rely on the caller's working directory.
pushd "%~dp0" >nul 2>&1
if errorlevel 1 goto PATH_ERROR

if not exist "logs\" mkdir "logs" >nul 2>&1
if not exist "logs\" goto LOG_ERROR
set "LOG=logs\startup.log"

> "%LOG%" echo [START] %DATE% %TIME%
>>"%LOG%" echo [START] Install folder: %CD%
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
%PY% -c "import json,pathlib; p=pathlib.Path('updates/update_source.json'); d=json.loads(p.read_text(encoding='utf-8')) if p.exists() else {}; d.setdefault('app_id','CAXA_Library_Helper'); d.setdefault('channel','stable'); d.setdefault('auto_check',True); d.setdefault('timeout_seconds',3); d['manifest_url']=str(d.get('manifest_url') or '').strip() or 'https://raw.githubusercontent.com/y2662151417/caxa-library-helper/main/updates/manifest.json'; p.parent.mkdir(parents=True,exist_ok=True); p.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\\n',encoding='utf-8')" >>"%LOG%" 2>&1
if errorlevel 1 goto CONFIG_ERROR

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

:PATH_ERROR
echo ERROR: Windows could not open the folder containing this BAT file.
echo Do not move this BAT file away from the app, runtime, logs and updates folders.
pause
exit /b 1

:LOG_ERROR
echo ERROR: Cannot create or access the logs folder.
echo Check whether this folder is read-only or blocked by Windows security.
pause
popd
exit /b 1

:SHOW_LOG
echo.
echo ---------------- startup.log ----------------
type "%LOG%"
echo.
echo Log file: %CD%\logs\startup.log
pause
popd
exit /b 1

:DONE
popd
exit /b 0
