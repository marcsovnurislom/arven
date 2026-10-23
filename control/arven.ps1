# ARVEN control panel: status / start / stop / restart / check / backup / site / logs.
# Double-click the .bat buttons next to this file (they call this script). Nothing here changes a strategy or a result.
param([Parameter(Mandatory = $true)][ValidateSet("status", "start", "stop", "restart", "check", "backup", "site", "logs")][string]$Action)

$ErrorActionPreference = "Continue"
$Repo = Split-Path -Parent $PSScriptRoot
Set-Location $Repo
$Py = Join-Path $Repo ".venv\Scripts\python.exe"
$StopFile = Join-Path $Repo "data\live\live.stop"
$env:PYTHONPATH = "src"
$env:PYTHONIOENCODING = "utf-8"
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}

function Say($text, $color = "Gray") { Write-Host $text -ForegroundColor $color }
function Head($text) { Write-Host ""; Write-Host "=== $text ===" -ForegroundColor Cyan }

function LiveProcs { Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" | Where-Object { $_.CommandLine -like "*arven live run*" } }
function WebProcs { Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" | Where-Object { $_.CommandLine -like "*arven web*" } }

function SiteOk {
    try { return (Invoke-WebRequest -UseBasicParsing -TimeoutSec 5 "http://127.0.0.1:8000/api/health").StatusCode -eq 200 } catch { return $false }
}

function StopLive {
    New-Item -ItemType File -Path $StopFile -Force | Out-Null
    $deadline = (Get-Date).AddMinutes(4)
    while ((LiveProcs) -and (Get-Date) -lt $deadline) { Start-Sleep -Seconds 3 }
    if (LiveProcs) { Say "Сигналы: процесс ещё заканчивает работу (до 4 минут) - он остановится сам." "Yellow" }
    else { Say "Сигналы: остановлены." "Green" }
}

function StartLive {
    Remove-Item $StopFile -ErrorAction SilentlyContinue
    Enable-ScheduledTask -TaskName "ARVEN Live" -ErrorAction SilentlyContinue | Out-Null
    Start-ScheduledTask -TaskName "ARVEN Live" -ErrorAction SilentlyContinue
    Say "Сигналы: запуск..." "Green"
}

function StopWeb([bool]$disable) {
    if ($disable) { Disable-ScheduledTask -TaskName "ARVEN Web" -ErrorAction SilentlyContinue | Out-Null }
    WebProcs | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Say "Сайт: остановлен." "Green"
}

function StartWeb {
    Enable-ScheduledTask -TaskName "ARVEN Web" -ErrorAction SilentlyContinue | Out-Null
    Start-ScheduledTask -TaskName "ARVEN Web" -ErrorAction SilentlyContinue
    Say "Сайт: запуск..." "Green"
}

function Status {
    $problems = @()
    Head "Сигналы (live-процесс)"
    $task = Get-ScheduledTask -TaskName "ARVEN Live" -ErrorAction SilentlyContinue
    if (-not $task) { Say "Задача 'ARVEN Live' не найдена - см. docs/ARVEN_BEZ_CLAUDE.md, раздел 'Если задачи пропали'." "Red"; $problems += "нет задачи ARVEN Live" }
    elseif ($task.State -eq "Disabled") { Say "Задача 'ARVEN Live' выключена." "Red"; $problems += "задача ARVEN Live выключена" }
    if (Test-Path $StopFile) { Say "Есть файл остановки data\live\live.stop - сигналы остановлены вручную (кнопка 'Запустить всё' уберёт его)." "Yellow"; $problems += "сигналы остановлены вручную" }
    if (LiveProcs) { Say "Процесс работает." "Green" } else { Say "Процесс не запущен." "Red"; $problems += "процесс сигналов не запущен" }
    & $Py -m arven live heartbeat
    if ($LASTEXITCODE -ne 0) { $problems += "heartbeat устарел или с ошибкой (ноутбук спал? нет интернета?)" }

    Head "Сайт"
    if (SiteOk) { Say "Сайт отвечает: http://127.0.0.1:8000" "Green" } else { Say "Сайт не отвечает." "Red"; $problems += "сайт не отвечает" }

    Head "Бэкапы"
    $b = Get-ChildItem (Join-Path $Repo "data\backups") -File -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($b) {
        $age = [math]::Round(((Get-Date) - $b.LastWriteTime).TotalHours, 1)
        Say "Последний: $($b.Name) ($age ч назад, $([math]::Round($b.Length / 1MB, 1)) МБ)" $(if ($age -gt 48) { "Yellow" } else { "Green" })
        if ($age -gt 48) { $problems += "бэкапу больше 2 суток" }
    } else { Say "Бэкапов нет." "Yellow"; $problems += "нет бэкапов" }

    Head "Диск"
    $d = Get-PSDrive -Name ($Repo.Substring(0, 1))
    $free = [math]::Round($d.Free / 1GB, 1)
    Say "Свободно: $free ГБ" $(if ($free -lt 5) { "Red" } else { "Green" })
    if ($free -lt 5) { $problems += "мало места на диске" }

    Head "Итог"
    if ($problems.Count -eq 0) { Say "ВСЁ РАБОТАЕТ." "Green" }
    else {
        Say "Есть проблемы:" "Red"
        $problems | ForEach-Object { Say " - $_" "Red" }
        Say "Что делать: docs/ARVEN_BEZ_CLAUDE.md, раздел 'Если что-то не так'. Чаще всего помогает кнопка 'Перезапустить'." "Yellow"
    }
}

function Check {
    Head "Проверка настроек (config/live.yaml)"
    & $Py scripts\check_config.py | Out-Host  # on screen, not into the return value
    if ($LASTEXITCODE -eq 0) { Say "Настройки в порядке - можно нажать 'Перезапустить', чтобы они вступили в силу." "Green"; return $true }
    Say "В настройках ошибка - НЕ перезапускайте, пока не исправите (старый процесс продолжает работать со старыми настройками)." "Red"
    return $false
}

switch ($Action) {
    "status" { Status }
    "start" { Head "Запуск"; StartLive; StartWeb; Start-Sleep -Seconds 15; Status }
    "stop" { Head "Остановка"; StopLive; StopWeb $true; Say "Всё остановлено. Сигналов не будет, пока не нажмёте 'Запустить всё'." "Yellow" }
    "restart" {
        if (-not (Check)) { break }
        Head "Перезапуск"
        StopLive; StartLive
        StopWeb $false; StartWeb
        Start-Sleep -Seconds 15
        Status
    }
    "check" { Check | Out-Null }
    "backup" {
        Head "Бэкап (сигналы, состояние, настройки)"
        & $Py -m arven backup
        Say "Готово. Папка: $Repo\data\backups - время от времени копируйте её на флешку или в облако." "Green"
    }
    "site" { Start-Process "http://127.0.0.1:8000"; if (-not (SiteOk)) { Say "Сайт не отвечает - нажмите 'Запустить всё' или 'Перезапустить'." "Yellow" } }
    "logs" { Start-Process explorer.exe (Join-Path $Repo "data\live") }
}
