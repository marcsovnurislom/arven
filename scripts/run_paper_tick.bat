@echo off
REM Stage 8: one scheduled paper-signal tick. Idempotent and catch-up capable (arven.paper.runs.run_paper_tick) -
REM safe to run on any cadence, including after a gap. Invoked by the "ARVEN Paper Run" Windows Scheduled Task.
cd /d C:\Users\Victus\arven
.venv\Scripts\python.exe -m arven paper run >> data\paper\scheduled_run.log 2>&1
