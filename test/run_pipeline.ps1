<#
.SYNOPSIS
    Functional/smoke test battery for Universal Tool Updater.

.DESCRIPTION
    This is NOT pytest/unittest and NOT a unit/integration test suite in the
    formal sense. It drives the REAL src/UpdateManager.py the way the
    maintainer actually drives it: a tools.ini plus CLI flags, from a clean
    scratch working directory, and asserts end-to-end outcomes (files on
    disk, exit codes, log output).

    Run from anywhere:
        pwsh -File test\run_pipeline.ps1
        (or, from repo root)  .\test\run_pipeline.ps1

    See test\README.md for what each scenario covers and known gaps.
#>

[CmdletBinding()]
param()

# ---------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------
$TestDir    = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot   = Split-Path -Parent $TestDir
$SrcDir     = Join-Path $RepoRoot 'src'
$ScratchDir = Join-Path $TestDir '.run'
$ToolsDir   = Join-Path $ScratchDir 'tools'
$LogsDir    = Join-Path $ScratchDir 'logs'
$MarkersLog = Join-Path $ScratchDir 'markers.log'
$IniPath    = Join-Path $ScratchDir 'tools.ini'
$VerifyHelper = Join-Path $TestDir 'verify_helpers.py'
$FixturesHelper = Join-Path $TestDir 'fixtures.py'

$FixturePort = 18971
$FixtureHealthUrl = "http://127.0.0.1:$FixturePort/health"

# ---------------------------------------------------------------------
# Pass/fail bookkeeping
# ---------------------------------------------------------------------
$script:PassCount = 0
$script:FailCount = 0
$script:SkipCount = 0
$script:FailureMessages = New-Object System.Collections.Generic.List[string]

function Format-ProcessArguments {
    # Start-Process -ArgumentList does NOT auto-quote array elements that
    # contain spaces (unlike the call operator "&"), so paths like
    # "C:\Program Files\WinRAR\Rar.exe" get silently split into two argv
    # entries. Build one pre-quoted command-line string instead.
    param([string[]]$Arguments)
    ($Arguments | ForEach-Object {
        if ($_ -match '[\s"]') {
            '"' + ($_ -replace '"', '\"') + '"'
        } else {
            $_
        }
    }) -join ' '
}

function Write-Section {
    param([string]$Title)
    Write-Host ""
    Write-Host "==== $Title ====" -ForegroundColor Cyan
}

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if ($Condition) {
        $script:PassCount++
        Write-Host "  PASS: $Message" -ForegroundColor Green
    } else {
        $script:FailCount++
        $script:FailureMessages.Add($Message)
        Write-Host "  FAIL: $Message" -ForegroundColor Red
    }
}

function Assert-Skip {
    param([string]$Message)
    $script:SkipCount++
    Write-Host "  SKIP: $Message" -ForegroundColor Yellow
}

# A network-tolerant assertion: if the condition is false but the log shows
# evidence of a network-level failure for the given tool, downgrade to SKIP
# instead of FAIL, so this battery stays meaningful when run offline or
# against a flaky third-party host.
function Assert-TrueOrNetworkSkip {
    param([bool]$Condition, [string]$Message, [string]$Combined, [string]$ToolName)
    if ($Condition) {
        $script:PassCount++
        Write-Host "  PASS: $Message" -ForegroundColor Green
        return
    }
    $networkFailure = $Combined -match [regex]::Escape("$ToolName`:") -and
        ($Combined -match 'ConnectionError|Timeout|NameResolutionError|getaddrinfo|Max retries exceeded|ConnectTimeout|SSLError|HTTPSConnectionPool')
    if ($networkFailure) {
        Assert-Skip "$Message (network failure talking to a real third-party host)"
    } else {
        Assert-True $false $Message
    }
}

# ---------------------------------------------------------------------
# Running the real UpdateManager.py
# ---------------------------------------------------------------------
function Invoke-Updater {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [string[]]$Arguments = @()
    )

    New-Item -ItemType Directory -Force -Path $LogsDir | Out-Null
    $stdoutFile = Join-Path $LogsDir "$Name.stdout.log"
    $stderrFile = Join-Path $LogsDir "$Name.stderr.log"

    Write-Host ("  running: python UpdateManager.py " + ($Arguments -join ' ')) -ForegroundColor DarkGray

    $proc = Start-Process -FilePath 'python' `
        -ArgumentList (Format-ProcessArguments (@('UpdateManager.py') + $Arguments)) `
        -WorkingDirectory $ScratchDir `
        -NoNewWindow -PassThru -Wait `
        -RedirectStandardOutput $stdoutFile `
        -RedirectStandardError $stderrFile

    $stdout = ''
    $stderr = ''
    if (Test-Path $stdoutFile) { $stdout = Get-Content -Raw -Path $stdoutFile -ErrorAction SilentlyContinue }
    if (Test-Path $stderrFile) { $stderr = Get-Content -Raw -Path $stderrFile -ErrorAction SilentlyContinue }
    if (-not $stdout) { $stdout = '' }
    if (-not $stderr) { $stderr = '' }

    [PSCustomObject]@{
        Name     = $Name
        ExitCode = $proc.ExitCode
        StdOut   = $stdout
        StdErr   = $stderr
        Combined = "$stdout`n$stderr"
    }
}

# Runs the Ctrl+C/graceful-shutdown scenario via shutdown_scenario.py, which
# owns the whole spawn-child/wait/send-CTRL_C_EVENT/wait-for-exit dance
# itself (see that script's docstring for why this can't be done reliably
# from PowerShell directly). Mirrors Invoke-Updater's return shape so the
# same Assert-* helpers work unchanged.
function Invoke-ShutdownScenario {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string[]]$Tools,
        [double]$DelaySeconds = 2.0,
        [double]$TimeoutSeconds = 15
    )

    New-Item -ItemType Directory -Force -Path $LogsDir | Out-Null
    $stdoutFile = Join-Path $LogsDir "$Name.stdout.log"
    $stderrFile = Join-Path $LogsDir "$Name.stderr.log"
    $helperScript = Join-Path $TestDir 'shutdown_scenario.py'

    $argList = @($helperScript, '--scratch-dir', $ScratchDir, '--delay', $DelaySeconds, '--timeout', $TimeoutSeconds, '--tools') + $Tools

    Write-Host ("  running: python shutdown_scenario.py --delay $DelaySeconds --tools " + ($Tools -join ' ')) -ForegroundColor DarkGray

    $proc = Start-Process -FilePath 'python' `
        -ArgumentList (Format-ProcessArguments $argList) `
        -WorkingDirectory $TestDir `
        -NoNewWindow -PassThru -Wait `
        -RedirectStandardOutput $stdoutFile `
        -RedirectStandardError $stderrFile

    $stdout = if (Test-Path $stdoutFile) { Get-Content -Raw -Path $stdoutFile -ErrorAction SilentlyContinue } else { '' }
    $stderr = if (Test-Path $stderrFile) { Get-Content -Raw -Path $stderrFile -ErrorAction SilentlyContinue } else { '' }
    if (-not $stdout) { $stdout = '' }
    if (-not $stderr) { $stderr = '' }

    [PSCustomObject]@{
        Name     = $Name
        ExitCode = $proc.ExitCode
        Combined = "$stdout`n$stderr"
    }
}

# ---------------------------------------------------------------------
# Fixture server lifecycle
# ---------------------------------------------------------------------
function Stop-PortOwner {
    param([int]$Port)
    try {
        $conns = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
        foreach ($c in $conns) {
            Write-Host "  Killing stale process on port $Port (PID $($c.OwningProcess))" -ForegroundColor Yellow
            Stop-Process -Id $c.OwningProcess -Force -ErrorAction SilentlyContinue
        }
    } catch {
        # Get-NetTCPConnection may not exist on very old systems; ignore.
    }
}

function Start-FixtureServer {
    Stop-PortOwner -Port $FixturePort

    New-Item -ItemType Directory -Force -Path $LogsDir | Out-Null
    $stdoutFile = Join-Path $LogsDir 'fixture_server.stdout.log'
    $stderrFile = Join-Path $LogsDir 'fixture_server.stderr.log'

    $argList = @('fixture_server.py')

    $proc = Start-Process -FilePath 'python' -ArgumentList (Format-ProcessArguments $argList) `
        -WorkingDirectory $TestDir -NoNewWindow -PassThru `
        -RedirectStandardOutput $stdoutFile -RedirectStandardError $stderrFile

    $ready = $false
    for ($i = 0; $i -lt 40; $i++) {
        Start-Sleep -Milliseconds 500
        try {
            $resp = Invoke-WebRequest -Uri $FixtureHealthUrl -UseBasicParsing -TimeoutSec 2
            if ($resp.StatusCode -eq 200) { $ready = $true; break }
        } catch {
            if ($proc.HasExited) {
                throw "Fixture server process exited early (see $stdoutFile / $stderrFile)"
            }
        }
    }

    if (-not $ready) {
        throw "Fixture server did not become ready in time. See $stdoutFile / $stderrFile"
    }

    Write-Host "  Fixture server ready on http://127.0.0.1:$FixturePort" -ForegroundColor DarkGray
    return $proc
}

# ---------------------------------------------------------------------
# Scratch directory setup
# ---------------------------------------------------------------------
function Initialize-ScratchDir {
    if (Test-Path $ScratchDir) {
        Remove-Item -Recurse -Force $ScratchDir -ErrorAction Stop
    }
    New-Item -ItemType Directory -Force -Path $ScratchDir | Out-Null
    New-Item -ItemType Directory -Force -Path $ToolsDir | Out-Null
    New-Item -ItemType Directory -Force -Path $LogsDir | Out-Null

    # Copy the real source tree into the scratch dir itself and run it from
    # there with a BARE filename ("UpdateManager.py", no directory prefix).
    # This matters: UpdateManager.change_current_directory() does
    #   os.chdir(os.path.dirname(sys.argv[0]))
    # which, if we ran "python I:\...\src\UpdateManager.py" from the
    # scratch dir, would silently chdir AWAY from our scratch dir and back
    # into the real src\ folder (dirname(sys.argv[0]) is non-empty). With a
    # bare filename and the scratch dir already as CWD, dirname("") is
    # falsy, so no chdir happens and the scratch dir stays authoritative
    # for tools.ini / mutex.lock / updates\ / install folders. This is
    # exactly the isolation trick the task's constraints call for, given
    # there is no --config flag.
    Copy-Item -Path (Join-Path $SrcDir 'UpdateManager.py') -Destination $ScratchDir -ErrorAction Stop
    Copy-Item -Path (Join-Path $SrcDir 'universal_updater') -Destination $ScratchDir -Recurse -ErrorAction Stop
    Copy-Item -Path (Join-Path $SrcDir 'pypdl_extend') -Destination $ScratchDir -Recurse -ErrorAction Stop

    Copy-Item -Path (Join-Path $TestDir 'tools.ini') -Destination $ScratchDir -ErrorAction Stop
    Copy-Item -Path (Join-Path $TestDir 'scripts') -Destination $ScratchDir -Recurse -ErrorAction Stop

    $unrarSrc = Join-Path $RepoRoot 'unrar.exe'
    if (Test-Path $unrarSrc) {
        Copy-Item -Path $unrarSrc -Destination $ScratchDir -ErrorAction Stop
    } else {
        Write-Host "  WARNING: $unrarSrc not found; RAR unpacking will not work in this run." -ForegroundColor Yellow
    }

    Get-ChildItem -Path $ScratchDir -Recurse -Directory -Filter '__pycache__' -ErrorAction SilentlyContinue |
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
}

function Initialize-MergeSeed {
    $mergeFolder = Join-Path $ToolsDir 'FixtureMerge'
    New-Item -ItemType Directory -Force -Path $mergeFolder | Out-Null
    $dest = Join-Path $mergeFolder 'FixtureMerge - 1.0.0.7z'
    & python $FixturesHelper 'seed-merge' $dest | Out-Null
    if (-not (Test-Path $dest)) {
        throw "Failed to seed merge fixture at $dest"
    }
    Write-Host "  Seeded merge fixture: $dest" -ForegroundColor DarkGray
}

# ---------------------------------------------------------------------
# Archive inspection helpers (reuse py7zr/zipfile/rarfile via verify_helpers.py)
# ---------------------------------------------------------------------
function Find-FirstFile {
    param([string]$Directory, [string]$Pattern)
    if (-not (Test-Path $Directory)) { return $null }
    $item = Get-ChildItem -Path $Directory -Filter $Pattern -File -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($item) { return $item.FullName }
    return $null
}

function Get-ExtractedArchive {
    param([string]$ArchivePath, [string]$Password)
    $destDir = Join-Path $LogsDir ("extract_" + [guid]::NewGuid().ToString('N'))
    $argList = @($VerifyHelper, 'extract', $ArchivePath, $destDir)
    if ($Password) { $argList += $Password }
    & python $argList | Out-Null
    if ($LASTEXITCODE -ne 0) { return $null }
    return $destDir
}

function Assert-ArchiveContainsFiles {
    param(
        [string]$ArchivePath,
        [string[]]$ExpectedRelativeFiles,
        [string]$Description,
        [string]$Password = $null
    )
    if (-not $ArchivePath -or -not (Test-Path $ArchivePath)) {
        Assert-True $false "$Description (archive not found: $ArchivePath)"
        return
    }
    $destDir = Get-ExtractedArchive -ArchivePath $ArchivePath -Password $Password
    if (-not $destDir) {
        Assert-True $false "$Description (extraction failed for $ArchivePath)"
        return
    }
    $ok = $true
    $missing = @()
    foreach ($rel in $ExpectedRelativeFiles) {
        $full = Join-Path $destDir $rel
        if (-not (Test-Path $full)) { $ok = $false; $missing += $rel }
    }
    if ($ok) {
        Assert-True $true "$Description"
    } else {
        Assert-True $false "$Description (missing: $($missing -join ', '))"
    }
}

function Get-ConfigValue {
    param([string]$IniFile, [string]$Section, [string]$Key)
    $val = & python $VerifyHelper 'get-config' $IniFile $Section $Key 2>$null
    if ($LASTEXITCODE -ne 0) { return $null }
    return "$val".Trim()
}

# =======================================================================
# MAIN
# =======================================================================
$overallStopwatch = [System.Diagnostics.Stopwatch]::StartNew()
$fixtureProc = $null

try {
    Write-Section "Setup"
    Write-Host "  Repo root:   $RepoRoot"
    Write-Host "  Scratch dir: $ScratchDir"
    Initialize-ScratchDir
    Initialize-MergeSeed

    $fixtureProc = Start-FixtureServer

    # -------------------------------------------------------------
    # Scenario 1: full --dry-run pass over everything
    # -------------------------------------------------------------
    Write-Section "Scenario 1: --dry-run over everything (no downloads)"
    $r1 = Invoke-Updater -Name 's1_dry_run_all' -Arguments @('--dry-run')

    Assert-True ($r1.ExitCode -eq 0) "s1: exit code is 0 (got $($r1.ExitCode))"
    foreach ($tool in @('FixtureWeb', 'FixtureNested', 'FixtureContentTypeReject', 'FixtureContentTypeAllowed',
                         'FixtureContentDisposition', 'FixtureMerge', 'FixturePasswordProtected',
                         'FixtureRepackOverride', 'FixtureRar')) {
        Assert-True ($r1.Combined -match [regex]::Escape("$tool`: [dry-run] update available")) `
            "s1: $tool reports [dry-run] update available"
    }
    foreach ($tool in @('Portmon', 'malunpack', 'OUI', 'mitmproxy')) {
        Assert-TrueOrNetworkSkip ($r1.Combined -match [regex]::Escape("$tool`: [dry-run] update available")) `
            "s1: $tool (real network) reports [dry-run] update available" $r1.Combined $tool
    }
    Assert-True (-not (Test-Path (Join-Path $ScratchDir 'updates'))) "s1: no updates\ folder was created during dry-run"
    Assert-True (-not (Test-Path (Join-Path $ToolsDir 'FixtureWeb'))) "s1: FixtureWeb install folder not created during dry-run"
    Assert-True (-not (Test-Path (Join-Path $ToolsDir 'FixtureNested'))) "s1: FixtureNested install folder not created during dry-run"

    # pre_update hooks run even during --dry-run (Updater.pre_update() runs
    # before the dry_run early-return); post_update/post_unpack/global
    # hooks must NOT have fired yet.
    $markersAfterS1 = if (Test-Path $MarkersLog) { Get-Content -Raw $MarkersLog } else { '' }
    Assert-True ($markersAfterS1 -match 'hook_pre_update\.bat') "s1: pre_update hook fired during dry-run"
    Assert-True ($markersAfterS1 -notmatch 'hook_post_update\.bat') "s1: post_update hook did NOT fire during dry-run"
    Assert-True ($markersAfterS1 -notmatch 'hook_post_unpack_bare\.ps1') "s1: post_unpack hook did NOT fire during dry-run"
    Assert-True ($markersAfterS1 -notmatch 'hook_global_post_update\.bat') "s1: global_post_update hook did NOT fire during dry-run"

    # -------------------------------------------------------------
    # Scenario 2: real run over the local-fixture-backed + merge entries
    # -------------------------------------------------------------
    Write-Section "Scenario 2: real run, fixture-backed + merge entries, default flags"
    $s2Tools = @('FixtureWeb', 'FixtureNested', 'FixtureContentTypeReject', 'FixtureContentTypeAllowed',
                 'FixtureContentDisposition', 'FixtureMerge', 'FixturePasswordProtected', 'FixtureRepackOverride',
                 'FixtureRar')
    $r2 = Invoke-Updater -Name 's2_real_fixture_run' -Arguments (@('-u') + $s2Tools)

    Assert-True ($r2.ExitCode -eq 0) "s2: exit code is 0 (got $($r2.ExitCode))"

    # FixtureWeb: basic zip, repacked (default), .bat pre/post_update hooks
    $webArchive = Find-FirstFile (Join-Path $ToolsDir 'FixtureWeb') 'FixtureWeb - *.7z'
    Assert-ArchiveContainsFiles -ArchivePath $webArchive -ExpectedRelativeFiles @('readme.txt', 'bin\tool.exe') `
        -Description "s2: FixtureWeb archive contains readme.txt + bin\tool.exe"
    Assert-True ($r2.Combined -match [regex]::Escape('FixtureWeb: update complete')) "s2: FixtureWeb: update complete logged"

    # FixtureNested: zip-inside-zip unpacked correctly
    $nestedArchive = Find-FirstFile (Join-Path $ToolsDir 'FixtureNested') 'FixtureNested - *.7z'
    Assert-ArchiveContainsFiles -ArchivePath $nestedArchive -ExpectedRelativeFiles @('data.txt', 'notes\readme.txt') `
        -Description "s2: FixtureNested archive contains nested zip-in-zip payload"

    # FixtureContentTypeReject: must FAIL, no install folder created
    Assert-True ($r2.Combined -match [regex]::Escape('FixtureContentTypeReject') -and $r2.Combined -match 'invalid download.*Content-Type') `
        "s2: FixtureContentTypeReject download rejected for bad Content-Type"
    Assert-True (-not (Test-Path (Join-Path $ToolsDir 'FixtureContentTypeReject'))) `
        "s2: FixtureContentTypeReject install folder was never created"

    # FixtureContentTypeAllowed: disable_content_type_check lets the same
    # misreported endpoint through
    $ctaArchive = Find-FirstFile (Join-Path $ToolsDir 'FixtureContentTypeAllowed') 'FixtureContentTypeAllowed - *.7z'
    Assert-ArchiveContainsFiles -ArchivePath $ctaArchive -ExpectedRelativeFiles @('content.txt') `
        -Description "s2: FixtureContentTypeAllowed archive contains content.txt (check bypassed)"

    # FixtureContentDisposition: tricky filename=/filename*=/path traversal
    # header must not escape the tool folder. disable_repack=true -> raw
    # folder save.
    $cdFolder = Join-Path $ToolsDir 'FixtureContentDisposition'
    Assert-True (Test-Path (Join-Path $cdFolder 'readme.txt')) "s2: FixtureContentDisposition folder has readme.txt (traversal defused)"
    Assert-True (-not (Test-Path (Join-Path $ScratchDir 'evil.zip'))) "s2: no evil.zip escaped to the scratch root"
    Assert-True (-not (Test-Path (Join-Path (Split-Path $ScratchDir -Parent) 'evil.zip'))) "s2: no evil.zip escaped above the scratch dir"

    # FixtureMerge: old (seeded) + new (fixture server) content merged
    $mergeArchive = Find-FirstFile (Join-Path $ToolsDir 'FixtureMerge') 'FixtureMerge - *.7z'
    Assert-ArchiveContainsFiles -ArchivePath $mergeArchive -ExpectedRelativeFiles @('old_marker.txt', 'new_marker.txt') `
        -Description "s2: FixtureMerge archive contains BOTH old_marker.txt and new_marker.txt"

    # FixturePasswordProtected: encrypted 7z extracted with update_file_pass
    $pwArchive = Find-FirstFile (Join-Path $ToolsDir 'FixturePasswordProtected') 'FixturePasswordProtected - *.7z'
    Assert-ArchiveContainsFiles -ArchivePath $pwArchive -ExpectedRelativeFiles @('secret.txt') `
        -Description "s2: FixturePasswordProtected archive contains secret.txt (password unlocked source archive)"

    # FixtureRepackOverride: per-tool disable_repack=true wins over the
    # global (enabled) default
    $rpoFolder = Join-Path $ToolsDir 'FixtureRepackOverride'
    Assert-True (Test-Path (Join-Path $rpoFolder 'readme.txt')) "s2: FixtureRepackOverride saved as raw files (readme.txt present)"
    Assert-True (-not (Test-Path (Join-Path $rpoFolder 'FixtureRepackOverride - 1.4.2.7z'))) "s2: FixtureRepackOverride was NOT repacked into a .7z"

    # FixtureRar: static, committed .rar fixture unpacked via the repo's own
    # unrar.exe - no Rar.exe/WinRAR compressor needed at test-run time, so
    # this runs the same everywhere, including CI.
    $rarArchive = Find-FirstFile (Join-Path $ToolsDir 'FixtureRar') 'FixtureRar - *.7z'
    Assert-ArchiveContainsFiles -ArchivePath $rarArchive -ExpectedRelativeFiles @('rar_marker.txt') `
        -Description "s2: FixtureRar archive contains rar_marker.txt (real .rar unpacked via unrar.exe)"

    # Hook scripts: all wired hooks must have fired by now
    $markersAfterS2 = if (Test-Path $MarkersLog) { Get-Content -Raw $MarkersLog } else { '' }
    Assert-True ($markersAfterS2 -match 'hook_post_update\.bat') "s2: FixtureWeb post_update .bat hook fired"
    Assert-True ($markersAfterS2 -match 'hook_post_unpack_bare\.ps1') "s2: FixtureNested bare .ps1 post_unpack hook fired"
    Assert-True ($markersAfterS2 -match 'hook_post_update_multiword\.ps1') "s2: FixtureMerge multi-word post_update command fired"
    Assert-True ($markersAfterS2 -match 'hook_global_post_update\.bat') "s2: global_post_update hook fired"

    # -------------------------------------------------------------
    # Scenario 3: real run over the real public tools (requires network)
    # -------------------------------------------------------------
    Write-Section "Scenario 3: real run, real public tools (requires network)"
    $r3 = Invoke-Updater -Name 's3_real_network_run' -Arguments @('-u', 'Portmon', 'malunpack', 'OUI')

    Assert-True ($r3.ExitCode -eq 0) "s3: exit code is 0 (got $($r3.ExitCode))"
    Assert-TrueOrNetworkSkip ([bool](Find-FirstFile (Join-Path $ToolsDir 'Portmon') 'Portmon - *.7z')) `
        "s3: Portmon (from=web) produced a repacked archive" $r3.Combined 'Portmon'
    Assert-TrueOrNetworkSkip ([bool](Find-FirstFile (Join-Path $ToolsDir 'malunpack') 'malunpack - *.7z')) `
        "s3: malunpack (from=github, re_download_x64 arch override) produced a repacked archive" $r3.Combined 'malunpack'
    Assert-TrueOrNetworkSkip ([bool](Find-FirstFile (Join-Path $ToolsDir 'OUI') 'OUI - *.7z')) `
        "s3: OUI (from=http, disable_content_type_check) produced a repacked archive" $r3.Combined 'OUI'

    # -------------------------------------------------------------
    # Scenario 4: save_format_type variants (full / version / name)
    # -------------------------------------------------------------
    Write-Section "Scenario 4: save_format_type variants (full / version / name)"

    $r4a = Invoke-Updater -Name 's4a_sft_full' -Arguments @('-u', 'FixtureWeb', '-f', '-sft', 'full')
    Assert-True ($r4a.ExitCode -eq 0) "s4a: exit code is 0"
    Assert-True (Test-Path (Join-Path $ToolsDir 'FixtureWeb\FixtureWeb - 1.4.2.7z')) `
        "s4a: -sft full produces '<name> - <version>.7z'"

    $r4b = Invoke-Updater -Name 's4b_sft_version' -Arguments @('-u', 'FixtureWeb', '-f', '-sft', 'version')
    Assert-True ($r4b.ExitCode -eq 0) "s4b: exit code is 0"
    Assert-True (Test-Path (Join-Path $ToolsDir 'FixtureWeb\1.4.2.7z')) `
        "s4b: -sft version produces '<version>.7z'"

    $r4c = Invoke-Updater -Name 's4c_sft_name' -Arguments @('-u', 'FixtureWeb', '-f', '-sft', 'name')
    Assert-True ($r4c.ExitCode -eq 0) "s4c: exit code is 0"
    Assert-True (Test-Path (Join-Path $ToolsDir 'FixtureWeb\FixtureWeb.7z')) `
        "s4c: -sft name produces '<name>.7z'"

    # -------------------------------------------------------------
    # Scenario 5: -dr (global disable-repack)
    # -------------------------------------------------------------
    Write-Section "Scenario 5: -dr (global --disable-repack)"
    $r5 = Invoke-Updater -Name 's5_disable_repack' -Arguments @('-u', 'FixtureWeb', 'FixtureNested', '-dr', '-f')

    Assert-True ($r5.ExitCode -eq 0) "s5: exit code is 0 (got $($r5.ExitCode))"
    $webFolder = Join-Path $ToolsDir 'FixtureWeb'
    $nestedFolder = Join-Path $ToolsDir 'FixtureNested'
    $webHasArchive = (Get-ChildItem -Path $webFolder -Filter '*.7z' -File -ErrorAction SilentlyContinue).Count -gt 0
    $nestedHasArchive = (Get-ChildItem -Path $nestedFolder -Filter '*.7z' -File -ErrorAction SilentlyContinue).Count -gt 0
    Assert-True (-not $webHasArchive) "s5: FixtureWeb folder has no .7z after global -dr"
    Assert-True (Test-Path (Join-Path $webFolder 'readme.txt')) "s5: FixtureWeb folder has raw readme.txt after global -dr"
    Assert-True (-not $nestedHasArchive) "s5: FixtureNested folder has no .7z after global -dr"
    Assert-True (Test-Path (Join-Path $nestedFolder 'data.txt')) "s5: FixtureNested folder has raw data.txt after global -dr"

    # -------------------------------------------------------------
    # Scenario 6: -pw 4 (parallel workers / concurrent repack)
    # -------------------------------------------------------------
    Write-Section "Scenario 6: -pw 4 (parallel workers, concurrent repack temp dirs)"
    $s6Tools = @('FixtureWeb', 'FixtureNested', 'FixtureMerge', 'FixturePasswordProtected',
                 'FixtureContentTypeAllowed', 'FixtureRepackOverride')
    $r6 = Invoke-Updater -Name 's6_parallel_workers' -Arguments (@('-u') + $s6Tools + @('-pw', '4', '-f'))

    Assert-True ($r6.ExitCode -eq 0) "s6: exit code is 0 (got $($r6.ExitCode))"
    foreach ($tool in $s6Tools) {
        Assert-True ($r6.Combined -match [regex]::Escape("$tool`: update complete")) "s6: $tool completed successfully under -pw 4"
    }
    Assert-True ($r6.Combined -notmatch 'FileExistsError|PermissionError|WinError 183') `
        "s6: no temp-path-collision errors in the log under concurrency"
    $mergeArchive6 = Find-FirstFile (Join-Path $ToolsDir 'FixtureMerge') 'FixtureMerge - *.7z'
    Assert-ArchiveContainsFiles -ArchivePath $mergeArchive6 -ExpectedRelativeFiles @('old_marker.txt', 'new_marker.txt') `
        -Description "s6: FixtureMerge archive still contains both markers after a forced re-run under -pw 4"

    # -------------------------------------------------------------
    # Scenario 7: corrupted mutex.lock
    # -------------------------------------------------------------
    Write-Section "Scenario 7: corrupted mutex.lock"
    Set-Content -Path (Join-Path $ScratchDir 'mutex.lock') -Value 'not-a-real-pid-#@!' -NoNewline
    $r7 = Invoke-Updater -Name 's7_corrupt_mutex' -Arguments @('--dry-run', '-u', 'FixtureWeb')

    Assert-True ($r7.ExitCode -eq 0) "s7: exit code is 0 despite a corrupted mutex.lock (got $($r7.ExitCode))"
    Assert-True ($r7.Combined -match 'Stale mutex detected') "s7: corrupted mutex.lock is treated as stale, not fatal"
    Assert-True (-not (Test-Path (Join-Path $ScratchDir 'mutex.lock'))) "s7: mutex.lock cleaned up after the run"

    # -------------------------------------------------------------
    # Scenario 8: -udp (persist default params into [UpdaterConfig])
    # -------------------------------------------------------------
    Write-Section "Scenario 8: -udp (--update-default-params persistence)"
    $r8 = Invoke-Updater -Name 's8_update_default_params' -Arguments @('-udp', '-pw', '2', '-sft', 'name', '--dry-run', '-u', 'FixtureWeb')

    Assert-True ($r8.ExitCode -eq 0) "s8: exit code is 0 (got $($r8.ExitCode))"
    $persistedWorkers = Get-ConfigValue -IniFile $IniPath -Section 'UpdaterConfig' -Key 'parallel_workers'
    $persistedFormat  = Get-ConfigValue -IniFile $IniPath -Section 'UpdaterConfig' -Key 'save_format_type'
    Assert-True ($persistedWorkers -eq '2') "s8: [UpdaterConfig] parallel_workers persisted as 2 (got '$persistedWorkers')"
    Assert-True ($persistedFormat -eq 'name') "s8: [UpdaterConfig] save_format_type persisted as name (got '$persistedFormat')"

    # -------------------------------------------------------------
    # Scenario 9: Ctrl+C mid-run stops promptly instead of finishing the batch
    # -------------------------------------------------------------
    # DISABLED - does not run in CI. shutdown_scenario.py sends a real
    # CTRL_C_EVENT via os.kill(pid, signal.CTRL_C_EVENT), which requires a
    # real attached Win32 console (GenerateConsoleCtrlEvent). GitHub-hosted
    # windows-latest runners' PowerShell job steps don't reliably have one,
    # so this aborts the whole script with a terminating error before it can
    # even report PASS/FAIL for this scenario (confirmed via a real CI run).
    # The underlying behavior IS verified working: a real Ctrl+C against the
    # actual CLI, on an interactive console on the machine this was built on,
    # correctly stopped the batch in ~2s instead of running it to completion
    # (see git history for that manual verification). Re-enable this block
    # (and shutdown_scenario.py / Invoke-ShutdownScenario, both left in place
    # unused) if a reliable way to deliver Ctrl+C from a CI job step is ever
    # found - possibly allocating a console via ctypes (kernel32.AllocConsole)
    # before spawning the child, though that hasn't been tried/verified.
    <#
    Write-Section "Scenario 9: Ctrl+C (graceful shutdown) mid-run"
    if (Test-Path (Join-Path $ScratchDir 'mutex.lock')) { Remove-Item -Force (Join-Path $ScratchDir 'mutex.lock') }
    $r9 = Invoke-ShutdownScenario -Name 's9_shutdown' -Tools @('FixtureSlow1', 'FixtureSlow2', 'FixtureSlow3') -DelaySeconds 2.0 -TimeoutSeconds 15

    Assert-True ($r9.ExitCode -eq 0) "s9: exit code is 0 (got $($r9.ExitCode))"
    Assert-True ($r9.Combined -match 'Shutting down gracefully') "s9: graceful-shutdown message logged"

    $harnessMatch = [regex]::Match($r9.Combined, 'SHUTDOWN_HARNESS: elapsed=(?<elapsed>[\d.]+) exit_code=(?<exit>\S+) timed_out=(?<timedout>\S+) mutex_cleaned=(?<mutex>\S+)')
    Assert-True $harnessMatch.Success "s9: shutdown_scenario.py summary line present in output"
    if ($harnessMatch.Success) {
        $elapsed = [double]$harnessMatch.Groups['elapsed'].Value
        # each FixtureSlow route sleeps 2s server-side; Ctrl+C is sent at t=2s
        # (mid FixtureSlow1's response). Finishing that one response plus a
        # prompt shutdown should land comfortably under 5s - if the process
        # instead ran all 3 tools to completion (the pre-fix behavior) this
        # would take 6s+ instead.
        Assert-True ($elapsed -lt 5.0) "s9: process exited well before the full batch would finish (elapsed ${elapsed}s, expected < 5s)"
        Assert-True ($harnessMatch.Groups['timedout'].Value -eq 'False') "s9: process exited on its own, was not force-killed after timeout"
        Assert-True ($harnessMatch.Groups['mutex'].Value -eq 'True') "s9: mutex.lock was cleaned up after a Ctrl+C shutdown"
    }
    Assert-True ($r9.Combined -notmatch [regex]::Escape('FixtureSlow3: [dry-run] update available')) `
        "s9: FixtureSlow3 (the last queued tool) never started"
    #>

} finally {
    Write-Section "Cleanup"
    if ($fixtureProc -and -not $fixtureProc.HasExited) {
        Write-Host "  Stopping fixture server (PID $($fixtureProc.Id))" -ForegroundColor DarkGray
        Stop-Process -Id $fixtureProc.Id -Force -ErrorAction SilentlyContinue
    }
}

# ---------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------
$overallStopwatch.Stop()
Write-Section "Summary"
Write-Host ("  Elapsed: {0:N1}s" -f $overallStopwatch.Elapsed.TotalSeconds)
Write-Host "  PASS: $script:PassCount" -ForegroundColor Green
Write-Host "  SKIP: $script:SkipCount" -ForegroundColor Yellow
Write-Host "  FAIL: $script:FailCount" -ForegroundColor $(if ($script:FailCount -gt 0) { 'Red' } else { 'Green' })

if ($script:FailCount -gt 0) {
    Write-Host ""
    Write-Host "Failed assertions:" -ForegroundColor Red
    foreach ($msg in $script:FailureMessages) {
        Write-Host "  - $msg" -ForegroundColor Red
    }
    Write-Host ""
    Write-Host "Scratch dir left in place for inspection: $ScratchDir" -ForegroundColor Yellow
    Write-Host "OVERALL: FAIL" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "OVERALL: PASS" -ForegroundColor Green
exit 0
