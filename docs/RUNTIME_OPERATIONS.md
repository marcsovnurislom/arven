# ARVEN — always-on paper runtime: operations (Phase 5)

Covers `arven paper runtime` (`src/arven/paper/runtime.py`), the long-running process introduced in
Phase 5 of `docs/ARVEN_MASTER_PROMPT.md`. It never places a real order (CLAUDE.md rule 12 - this is
simulated paper trading on real market data, same as `arven paper run`) and is strictly additive: Stage 8's
own externally-scheduled `scripts/run_paper_tick.bat` / "ARVEN Paper Run" task keep working unchanged if
you prefer that simpler model instead.

## Running it directly (foreground, for a soak test or manual supervision)

```
.venv\Scripts\python.exe -m arven paper runtime --poll-seconds 15 --stop-file data\paper\runtime.stop
```

- Prints its heartbeat/log file paths on startup, then polls forever.
- **Ctrl+C** stops it. Every tick is a complete, atomic unit (`run_paper_tick` never writes anything
  partial), so an interrupt is always safe, even though it is not a signal-handler-graceful mid-tick stop
  (Windows' asyncio event loop does not support POSIX signal handlers, so this project does not rely on one).
- **`--stop-file`**: create the named file (e.g. `type nul > data\paper\runtime.stop`) to request a
  graceful stop from another window or a script, without needing to send a signal at all. The process
  checks for it about once a second. Delete the file again before the next start.
- Check it is alive and what it last did: `arven paper heartbeat` (reads `data/paper/heartbeat.json`;
  non-zero exit if the heartbeat is stale or its last status was `"error"` - suitable for a monitoring
  script or a Task Scheduler "on event" trigger).
- The tick-by-tick structured log is `data/paper/runtime.jsonl` (one JSON object per poll: `status`
  `"ticked"`/`"idle"`/`"error"`, `detail`, `run_id`, `end_ms`).

## Windows Task Scheduler: restart on failure

Unlike Stage 8's hourly task (which starts, ticks once, and exits - nothing to "restart" mid-run), this
process is meant to run continuously, so its scheduled task should **restart it if it ever exits**,
instead of running it on a repeating schedule.

```powershell
$action = New-ScheduledTaskAction -Execute "C:\Users\Victus\arven\scripts\run_paper_runtime.bat"
$trigger = New-ScheduledTaskTrigger -AtLogOn   # starts once, at logon - not a repeating interval
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Days 3650)   # effectively unlimited; see Stage 8's own note on this flag
Register-ScheduledTask -TaskName "ARVEN Paper Runtime" -Action $action -Trigger $trigger -Settings $settings `
    -Description "Phase 5: the always-on paper-signal runtime. Restarts automatically on failure; run_paper_tick is idempotent, so a restart loses nothing."
```

- `-RestartCount`/`-RestartInterval` is Task Scheduler's own "if the task's process exits, start it again"
  behaviour - this *is* the "restart on failure" recipe `ARVEN_MASTER_PROMPT.md` section 5.2 asks for; no
  separate watchdog process is needed.
- To stop it for good (not just one restart cycle): `Unregister-ScheduledTask -TaskName "ARVEN Paper
  Runtime"` **and** create the stop file first (`type nul > data\paper\runtime.stop`) so the *current*
  process also exits gracefully, rather than being killed by Task Scheduler ending the task.
- `arven paper heartbeat`'s non-zero exit code is suitable as a separate Task Scheduler health-check
  trigger (e.g. an hourly task that runs it and alerts if it fails) if you want monitoring independent of
  the restart mechanism itself.

## Power settings - "a sleeping laptop is not 24/7"

Task Scheduler restarting the process does nothing if Windows itself is asleep. For genuine 24/7 operation
on a laptop:

- **Settings > System > Power & battery > Screen and sleep**: set "When plugged in, put my device to sleep"
  to **Never**. Screen-off is fine (and saves power) - only *sleep/hibernate* stops the process.
- Keep the laptop plugged in; battery-only operation will eventually sleep regardless of the setting above
  on most Windows power plans, and a REST-polling + DuckDB process run for days is not something to risk
  running unattended on battery.
- A closed laptop lid usually forces sleep regardless of the setting above - check **Settings > System >
  Power & battery > Additional power settings > Choose what closing the lid does** and set it to
  "Do nothing" if the machine needs to stay up with the lid closed.
- Windows Update's own forced restarts are a separate real risk for a multi-day soak - the always-on
  process does not protect against the *machine* rebooting, only against its own crashes. Consider pausing
  updates for the duration of a soak test (Settings > Windows Update > Pause updates).

## Known limitation, honestly stated

Phase 5's own master-prompt gate is **"48 h soak on live public data: no duplicate/skipped events, correct
stale => NO_TRADE"**. That is a real-time, multi-day observation, not something any single interactive
session can complete synchronously - it was not run as part of landing this phase's code. See
`docs/current_state.md`'s "Phase 5" section for exactly what *was* validated (offline, against fakes) and
what this leaves as an explicit, acknowledged gap rather than a silently-skipped requirement.
