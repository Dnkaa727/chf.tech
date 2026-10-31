@echo off
chcp 65001 >nul
cd /d "%~dp0"
py -m pip install -r requirements.txt
if errorlevel 1 goto fail
py run.py serve
exit /b %errorlevel%
:fail
echo Could not install/start API
pause
exit /b 1
