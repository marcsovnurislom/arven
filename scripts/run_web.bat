@echo off
REM ARVEN web app (read-only API + React app) on http://127.0.0.1:8000. Close this window to stop it.
cd /d C:\Users\Victus\arven
.venv\Scripts\python.exe -m arven web >> data\live\web.log 2>&1
