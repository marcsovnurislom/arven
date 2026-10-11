@echo off
REM ARVEN live signals (docs/LIVE_SIGNALS.md): one always-on process - fresh Binance data every 20 s, every enabled
REM strategy in config\live.yaml evaluated at each 15m close, signals stored and tracked, Telegram alerts, heartbeat.
REM It also runs the Stage 8 hourly paper run, so the "ARVEN Paper Run" scheduled task must be disabled while this runs
REM (one DuckDB writer). Meant as the action of a Windows Scheduled Task "at log on, restart on failure"
REM (docs/LIVE_SIGNALS.md section 4). Stop it gracefully: create data\live\live.stop
cd /d C:\Users\Victus\arven
if not exist data\live mkdir data\live
.venv\Scripts\python.exe -m arven live run --stop-file data\live\live.stop >> data\live\live_process.log 2>&1
