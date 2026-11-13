# daily_status_check.ps1 -- runs daily Tue-Sun. Does NOT touch pull_weekly_stats.py
# (that's auto_weekly.ps1's job, once, on Tuesday) -- this script only re-pulls
# THIS week's DK salaries (once the draft group ID is known) and reports what
# changed since yesterday's pull: Status (O/Q/D/etc.) and DraftAlerts changes.
#
# Draft group ID: reuses data\current_draft_group.json if it's for the current
# week; otherwise auto-detects the week's full Thu-Mon Classic slate with
# find_dk_draft_group.py (no curl pasting needed). Skips cleanly if DK hasn't
# posted the week's slates yet, and retries on the next run.

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$py = Join-Path $root "venv\Scripts\python.exe"
$logDir = Join-Path $root "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logPath = Join-Path $logDir "daily_status_check.log"

function Log($msg) {
    $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $msg
    Write-Host $line
    Add-Content -Path $logPath -Value $line
}

Log "=== daily_status_check.ps1 starting ==="

if (-not (Test-Path $py)) {
    Log "ERROR: venv python not found at $py -- aborting."
    exit 1
}

$Season = 2026

$calJson = & $py "$root\scripts\nfl_calendar.py" --json 2>&1 | Out-String
try { $cal = $calJson | ConvertFrom-Json } catch {
    Log "ERROR: couldn't parse nfl_calendar.py --json output: $calJson"
    exit 1
}
if ($null -eq $cal.week) {
    Log "Today doesn't fall inside a known NFL week -- nothing to do."
    exit 0
}
$Week = [int]$cal.week

$statePath = Join-Path $root "data\current_draft_group.json"
$draftGroupId = $null
if (Test-Path $statePath) {
    $state = Get-Content $statePath -Raw | ConvertFrom-Json
    if ([int]$state.week -eq $Week) {
        $draftGroupId = $state.draft_group_id
        Log "Using known draft group ID $draftGroupId for Week $Week (recorded $($state.updated_at))"
    } else {
        Log "Draft group ID on record is for Week $($state.week), current week is $Week -- auto-detecting this week's."
    }
}
if (-not $draftGroupId) {
    # Continue (not Stop) so the finder's stderr "not found yet" note can't abort the script.
    $ErrorActionPreference = "Continue"
    $found = & $py "$root\scripts\find_dk_draft_group.py" 2>$null
    $findExit = $LASTEXITCODE
    $ErrorActionPreference = "Stop"
    if ($findExit -ne 0 -or -not $found) {
        Log "Couldn't find a DK Classic draft group for Week $Week yet (DK may not have posted this week's slates) -- skipping, will retry next run."
        exit 0
    }
    $draftGroupId = ([string]$found).Trim()
    Log "Auto-detected Week $Week draft group ID $draftGroupId (full-week Classic slate)."
}

$salariesPath = Join-Path $root "data\dk_salaries\DKSalaries_wk$Week.csv"
Log "Re-pulling Week $Week salaries..."
& $py "$root\scripts\pull_dk_salaries.py" --draft-group-id $draftGroupId --out $salariesPath --season $Season --week $Week 2>&1 | ForEach-Object { Log "  $_" }
if ($LASTEXITCODE -ne 0) {
    Log "ERROR: pull_dk_salaries.py failed -- stopping (leaving yesterday's data in place)."
    exit 1
}

$today = Get-Date -Format "yyyyMMdd"
$reportPath = Join-Path $root "data\status_reports\status_report_wk${Week}_$today.md"
Log "Diffing against the prior snapshot..."
& $py "$root\scripts\diff_dk_status.py" --week $Week --out $reportPath 2>&1 | ForEach-Object { Log "  $_" }

Log "Pulling ESPN status (real-time Out/Doubtful/Questionable cross-check)..."
& $py "$root\scripts\pull_espn_status.py" --season $Season --week $Week 2>&1 | ForEach-Object { Log "  $_" }
if ($LASTEXITCODE -ne 0) {
    Log "WARNING: pull_espn_status.py failed -- continuing without it (gold-mine alerts will be skipped this run)."
}

Log "Pulling ESPN depth charts..."
& $py "$root\scripts\pull_espn_depthchart.py" --season $Season --week $Week 2>&1 | ForEach-Object { Log "  $_" }
if ($LASTEXITCODE -ne 0) {
    Log "WARNING: pull_espn_depthchart.py failed -- continuing without it."
}

Log "Rebuilding projections + dashboard with today's data..."
& $py "$root\scripts\build_projections.py" --season $Season --week $Week --salaries $salariesPath 2>&1 | ForEach-Object { Log "  $_" }
if ($LASTEXITCODE -ne 0) {
    Log "ERROR: build_projections.py failed."
    exit 1
}

$yy = $Season % 100
$outHtml = Join-Path $root ("Tinker{0:D2}W{1:D2}.html" -f $yy, $Week)
$projPath = Join-Path $root "data\projections_wk$Week.csv"
& $py "$root\scripts\generate_dashboard.py" --season $Season --week $Week --projections $projPath --out $outHtml 2>&1 | ForEach-Object { Log "  $_" }
if ($LASTEXITCODE -ne 0) {
    Log "ERROR: generate_dashboard.py failed."
    exit 1
}

$goldMinePath = Join-Path $root "data\gold_mine_alerts_wk$Week.md"
Log "Checking for gold-mine backup-value alerts..."
& $py "$root\scripts\gold_mine_alerts.py" --season $Season --week $Week --out $goldMinePath 2>&1 | ForEach-Object { Log "  $_" }

Log "Done. Dashboard refreshed: $outHtml -- status report (if any changes): $reportPath -- gold-mine alerts: $goldMinePath"
