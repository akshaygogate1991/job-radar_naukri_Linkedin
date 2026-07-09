@echo off
REM ============================================================
REM  job_agent_scheduler.bat
REM  
REM  Double-click this ONCE to register the Windows Task.
REM  After that, the agent runs automatically every day at 10 AM
REM  even if you are not at your laptop (as long as laptop is ON).
REM
REM  TO USE:
REM  1. Right-click this file -> Run as Administrator
REM  2. Done - check Task Scheduler to confirm
REM ============================================================

SET TASK_NAME=JobApplicationAgent
SET PYTHON=python
SET SCRIPT_PATH=D:\Naukari CV\job automation\run_agent.py
SET LOG_PATH=D:\Naukari CV\job automation\logs\task_log.txt

echo Registering daily job agent task at 10:00 AM...

schtasks /create /tn "%TASK_NAME%" ^
  /tr "\"%PYTHON%\" \"%SCRIPT_PATH%\" >> \"%LOG_PATH%\" 2>&1" ^
  /sc DAILY ^
  /st 10:00 ^
  /f ^
  /rl HIGHEST

if %ERRORLEVEL% == 0 (
    echo.
    echo SUCCESS! Task registered.
    echo The Job Agent will run automatically every day at 10:00 AM.
    echo.
    echo To verify: Open Task Scheduler ^> Task Scheduler Library ^> JobApplicationAgent
    echo To run now: schtasks /run /tn "%TASK_NAME%"
    echo To remove: schtasks /delete /tn "%TASK_NAME%" /f
) else (
    echo.
    echo FAILED. Try running this file as Administrator.
    echo Right-click the .bat file and select "Run as administrator"
)

pause
