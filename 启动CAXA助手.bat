@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
set "PY="
where py >nul 2>nul
if not errorlevel 1 (
    py -3 -c "import sys, tkinter; sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>nul
    if not errorlevel 1 set "PY=py -3"
)
if not defined PY (
    where python >nul 2>nul
    if not errorlevel 1 (
        python -c "import sys, tkinter; sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>nul
        if not errorlevel 1 set "PY=python"
    )
)
if not defined PY goto :no_python
%PY% "%~dp0runtime\launcher.py"
if errorlevel 1 goto :failed
exit /b 0
:no_python
echo [无法启动] 未检测到 Python 3.10+ 或 Tkinter。
echo 请安装包含 Tcl/Tk 的 Python 3.10 或更高版本，然后再次双击本文件。
pause
exit /b 1
:failed
echo [启动失败] 请查看 logs\launcher.log。
pause
exit /b 1
