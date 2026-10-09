@echo off
REM Forward paper evaluation of S4/S5/S6 (broker/CFD costs). Idempotent and catch-up capable - safe on any cadence
REM (every 15 minutes is the natural one). The first run after a long gap replays all missed 15m closes and can take a while.
cd /d C:\Users\Victus\arven
.venv\Scripts\python.exe -m arven paper strategies >> data\paper\strategies_run.log 2>&1
