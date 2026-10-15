@echo off
REM ---------------------------------------------------------------
REM Creates a scheduled task that runs the collector every hour.
REM Right-click this file -> "Run as administrator". Only needed once.
REM
REM /RU SYSTEM   runs it even when nobody is logged in
REM /RL HIGHEST  gives it the admin rights needed to read the Security log
REM /F           overwrites the task if it already exists
REM ---------------------------------------------------------------

schtasks /Create /TN "WindowsLoginMonitor" /TR "\"%~dp0run_collector.bat\"" /SC HOURLY /RU SYSTEM /RL HIGHEST /F

REM Run it once straight away so you can check it works.
schtasks /Run /TN "WindowsLoginMonitor"

echo.
echo Task created. Check output\collector_log.txt in a minute to see the result.
pause
