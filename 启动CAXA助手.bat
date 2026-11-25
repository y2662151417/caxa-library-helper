@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"

if not exist "logs" mkdir "logs" >nul 2>nul
set "LOG=%~dp0logs\startup.log"
echo.>>"%LOG%"
echo ============================================================>>"%LOG%"
echo [启动检查] %date% %time%>>"%LOG%"
echo [启动检查] 安装目录：%~dp0>>"%LOG%"

set "PY="
where py >nul 2>nul
if not errorlevel 1 (
    py -3 -c "import sys, tkinter; print('Python:',sys.version); print('Tkinter: OK'); sys.exit(0 if sys.version_info >= (3,10) else 1)" >>"%LOG%" 2>&1
    if not errorlevel 1 set "PY=py -3"
)

if not defined PY (
    where python >nul 2>nul
    if not errorlevel 1 (
        python -c "import sys, tkinter; print('Python:',sys.version); print('Tkinter: OK'); sys.exit(0 if sys.version_info >= (3,10) else 1)" >>"%LOG%" 2>&1
        if not errorlevel 1 set "PY=python"
    )
)

if not defined PY goto no_python
if not exist "runtime\launcher.py" goto missing_runtime
if not exist "app\app.py" goto missing_app

echo [启动检查] 使用解释器：%PY%>>"%LOG%"
echo [启动检查] 检查并补齐 GitHub 更新源配置。>>"%LOG%"
%PY% -c "import json,pathlib; p=pathlib.Path('updates/update_source.json'); d=json.loads(p.read_text(encoding='utf-8')) if p.exists() else {}; d.setdefault('app_id','CAXA_Library_Helper'); d.setdefault('channel','stable'); d.setdefault('auto_check',True); d.setdefault('timeout_seconds',3); d['manifest_url']=str(d.get('manifest_url') or '').strip() or 'https://raw.githubusercontent.com/y2662151417/caxa-library-helper/main/updates/manifest.json'; p.parent.mkdir(parents=True,exist_ok=True); p.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')" >>"%LOG%" 2>&1
if errorlevel 1 goto config_failed

echo [启动检查] 正在启动 CAXA 图库助手……>>"%LOG%"
%PY% "%~dp0runtime\launcher.py" >>"%LOG%" 2>&1
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" goto launch_failed
exit /b 0

:no_python
echo [无法启动] 未检测到 Python 3.10+ 或 Tkinter。
echo [无法启动] 未检测到 Python 3.10+ 或 Tkinter。>>"%LOG%"
echo 请安装包含 Tcl/Tk 的 Python 3.10 或更高版本，然后再次运行。
goto show_log

:missing_runtime
echo [程序文件缺失] 找不到 runtime\launcher.py。
echo [程序文件缺失] 找不到 runtime\launcher.py。>>"%LOG%"
goto show_log

:missing_app
echo [程序文件缺失] 找不到 app\app.py。
echo [程序文件缺失] 找不到 app\app.py。>>"%LOG%"
goto show_log

:config_failed
echo [配置失败] 无法写入 updates\update_source.json。
echo [配置失败] 无法写入 updates\update_source.json。>>"%LOG%"
goto show_log

:launch_failed
echo [启动失败] Python 返回错误代码：%RC%
echo [启动失败] Python 返回错误代码：%RC%>>"%LOG%"

:show_log
echo.
echo ---------------- 诊断日志 ----------------
type "%LOG%"
echo.
echo 日志文件：logs\startup.log
echo 请把这个日志发回给我。
pause
exit /b 1
