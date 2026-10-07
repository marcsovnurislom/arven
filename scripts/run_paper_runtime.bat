@echo off
REM Phase 5 (ARVEN_MASTER_PROMPT.md): launches the always-on paper runtime as one long-running process,
REM instead of Stage 8's "re-invoke once an hour" pattern (scripts\run_paper_tick.bat, still used for the
REM legacy, externally-scheduled path). Meant to be the Action of a Windows Scheduled Task configured to
REM restart on failure (see docs/RUNTIME_OPERATIONS.md) - if the process dies for any reason, the task
REM definition relaunches it; run_paper_tick's own idempotency means a restart loses nothing.
cd /d C:\Users\Victus\arven
.venv\Scripts\python.exe -m arven paper runtime --stop-file data\paper\runtime.stop >> data\paper\runtime_process.log 2>&1
