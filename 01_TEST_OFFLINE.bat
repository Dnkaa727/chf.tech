@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ====== ALL 25 RUBRICS + 150 OFFLINE CASES ======
py run.py check
if errorlevel 1 goto fail
py run.py test
if errorlevel 1 goto fail
py run.py mock PG-QUERY-01 partial
if errorlevel 1 goto fail
echo ====== OFFLINE CHECKS PASSED ======
pause
exit /b 0
:fail
echo FAILED - save or send this console output
pause
exit /b 1
