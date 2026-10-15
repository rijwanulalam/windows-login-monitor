@echo off
REM ---------------------------------------------------------------
REM Runs collector.py and appends everything it prints to a log file.
REM Task Scheduler calls this file.
REM ---------------------------------------------------------------

REM Move into the folder this .bat file lives in.
cd /d "%~dp0"

REM Full path to python.exe (SYSTEM can't use your user's PATH).
REM The quotes around the whole  "PYTHON=..."  stop stray spaces
REM at the end of the line from breaking the path.
set "PYTHON=C:\Program Files\Python314\python.exe"

if not exist output mkdir output

REM Write a timestamp so each run is easy to find in the log.
echo ===== Task run %date% %time% ===== >> output\collector_log.txt

REM Stop early with a clear message if python.exe isn't where we expect.
if not exist "%PYTHON%" (
    echo ERROR: python.exe not found at "%PYTHON%" >> output\collector_log.txt
    exit /b 1
)

"%PYTHON%" collector.py >> output\collector_log.txt 2>&1