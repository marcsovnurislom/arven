@echo off
REM ARVEN live signals in a console window, for a manual run (docs/LIVE_SIGNALS.md). The "ARVEN Live" scheduled task
REM runs the same command windowless (pythonw); if it is already running, this copy exits at once (data\live\live.lock).
REM Stop: create data\live\live.stop (the process stays stopped until the file is deleted).
cd /d C:\Users\Victus\arven
if not exist data\live mkdir data\live
.venv\Scripts\python.exe -m arven live run --stop-file data\live\live.stop
