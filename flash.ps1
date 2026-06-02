<#
.SYNOPSIS
    One-command build & flash for the Plai firmware (ESP-IDF 5.5.x / esp32s3 / M5Stack CardPuter).

.DESCRIPTION
    Run `.\flash.ps1` and the firmware ends up on the device. The script is idempotent:
    it performs any missing one-time setup (clone Meshtastic protobufs, create the nanopb
    generator venv, generate the protobuf code), activates the ESP-IDF environment, builds,
    auto-detects the device's COM port, warns before it wipes the NVS mesh keys, then flashes.

    See docs\BUILD.md for the manual steps this automates and for troubleshooting.

.EXAMPLE
    .\flash.ps1
    First-time / full flash. Sets up what's missing, builds, prompts before wiping NVS, flashes.

.EXAMPLE
    .\flash.ps1 -AppOnly
    Routine update that flashes only the app partition and KEEPS the device's mesh keys.

.EXAMPLE
    .\flash.ps1 -Yes -Monitor
    Full flash without the confirmation prompt, then open the serial monitor.

.NOTES
    Windows PowerShell 5.1+. If execution is blocked:
        powershell -ExecutionPolicy Bypass -File .\flash.ps1
#>

[CmdletBinding()]
param(
    [string] $Port,                          # "COM4"; auto-detect (USB VID 303A) when omitted
    [switch] $AppOnly,                        # idf.py app-flash (app only; preserves NVS keys)
    [switch] $Full,                           # explicit full flash (default when neither set)
    [switch] $Monitor,                        # open idf.py monitor after flashing (exit Ctrl+])
    [switch] $Regen,                          # force-regenerate the nanopb protobuf code
    [switch] $Clean,                          # idf.py fullclean before building
    [switch] $SetupOnly,                      # one-time setup only; no build/flash
    [Alias('BuildOnly')][switch] $NoFlash,    # build (and set up) but do not flash
    [Alias('Force')]   [switch] $Yes,         # non-interactive: skip the NVS-wipe confirmation
    [string] $SysPython,                      # system python.exe used to create tools\protovenv
    [switch] $Help
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# --- Constants -------------------------------------------------------------------------------

$RepoRoot = if ($PSScriptRoot) { $PSScriptRoot } else { (Get-Location).Path }
$ProtobufsUrl = 'https://github.com/meshtastic/protobufs.git'

# Known EIM install defaults (this machine). Used to recreate tools\activate-idf.ps1 if missing.
$IdfDefaults = @{
    Profile   = 'C:\Espressif\tools\Microsoft.v5.5.4.PowerShell_profile.ps1'
    IdfPath   = 'C:\esp\v5.5.4\esp-idf'
    ToolsPath = 'C:\Espressif\tools'
    PyEnvPath = 'C:\Espressif\tools\python\v5.5.4\venv'
}

# --- Small output helpers --------------------------------------------------------------------

function Step    { param([string]$m) Write-Host "`n==> $m" -ForegroundColor Cyan }
function Detail  { param([string]$m) Write-Host "    $m"   -ForegroundColor DarkGray }
function Good    { param([string]$m) Write-Host "    $m"   -ForegroundColor Green }
function Caution { param([string]$m) Write-Host "    $m"   -ForegroundColor Yellow }

# Throw if the most recent native command set a non-zero exit code. (Native exes set
# $LASTEXITCODE; PowerShell functions/cmdlets do not, so this reads the real last result.)
function Assert-Exit {
    param([Parameter(Mandatory)][string] $What)
    if ($LASTEXITCODE -ne 0) { throw "$What failed (exit code $LASTEXITCODE)." }
}

function Show-Help {
@"
flash.ps1 - one-command build & flash for Plai (ESP-IDF / esp32s3 / M5Stack CardPuter)

USAGE
  .\flash.ps1 [options]

  With no options:  set up (if needed) -> build -> detect port -> confirm -> FULL flash.

OPTIONS
  -Port <COMx>    Target serial port. Auto-detected (USB VID 303A) when omitted.
  -AppOnly        Flash only the app partition (idf.py app-flash). Preserves NVS / mesh keys.
  -Full           Force a full flash (the default when neither -AppOnly nor -Full is given).
  -Monitor        Open the serial monitor after flashing (exit with Ctrl+]).
  -Regen          Force-regenerate the nanopb protobuf code.
  -Clean          Run 'idf.py fullclean' before building.
  -SetupOnly      Only do one-time setup (protobufs + generator venv + codegen); no build/flash.
  -NoFlash        Build (and set up) but do not flash. Alias: -BuildOnly.
  -Yes            Non-interactive: skip the NVS-wipe confirmation. Alias: -Force.
  -SysPython <p>  Path to a system python.exe used to create tools\protovenv.
  -Help           Show this help.

EXAMPLES
  .\flash.ps1                   First-time / full flash (prompts before wiping NVS)
  .\flash.ps1 -AppOnly          Routine update that keeps your mesh keys
  .\flash.ps1 -Yes -Monitor     Full flash without prompting, then watch logs
  .\flash.ps1 -NoFlash          Just build
  .\flash.ps1 -Regen -NoFlash   Regenerate protobufs and build

NOTES
  - NVS holds your mesh/channel + security keys. A FULL flash resets NVS to nvs.csv defaults
    (keys wiped). Back up first on-device via Settings -> Export, or use -AppOnly.
  - If PowerShell blocks the script:  powershell -ExecutionPolicy Bypass -File .\flash.ps1
"@ | Write-Host
}

# --- Prerequisite discovery ------------------------------------------------------------------

function Assert-RepoRoot {
    foreach ($m in @('CMakeLists.txt', 'partitions.csv', 'nvs.csv', 'main\CMakeLists.txt')) {
        if (-not (Test-Path (Join-Path $RepoRoot $m))) {
            throw "This doesn't look like the Plai repo root (missing '$m'). Keep flash.ps1 in the repo root."
        }
    }
}

# Does $Exe run as a working Python? (Avoids the noisy Windows Store alias stub.)
function Test-PythonExe {
    param([string] $Exe)
    if (-not $Exe) { return $false }
    try {
        $null = & $Exe --version
        return ($LASTEXITCODE -eq 0)
    }
    catch { return $false }
}

# Locate a system Python to build tools\protovenv. NEVER the ESP-IDF venv (kept pristine).
# Resolve this BEFORE activation, which prepends the IDF venv to PATH. Returns $null if none.
function Get-SystemPython {
    if ($SysPython) {
        if ((Test-Path $SysPython) -and (Test-PythonExe $SysPython)) { return (Resolve-Path $SysPython).Path }
        throw "-SysPython '$SysPython' is not a working Python interpreter."
    }
    $base = Join-Path $env:LOCALAPPDATA 'Programs\Python'
    if (Test-Path $base) {
        $dirs = @(Get-ChildItem -Path $base -Filter 'Python*' -Directory -ErrorAction SilentlyContinue |
                  Sort-Object Name -Descending)
        foreach ($d in $dirs) {
            $exe = Join-Path $d.FullName 'python.exe'
            if ((Test-Path $exe) -and (Test-PythonExe $exe)) { return $exe }
        }
    }
    if (Get-Command py -ErrorAction SilentlyContinue) {
        try {
            $exe = & py -3 -c "import sys; print(sys.executable)" | Select-Object -First 1
            if ($LASTEXITCODE -eq 0 -and $exe -and (Test-Path $exe) -and (Test-PythonExe $exe)) { return $exe }
        }
        catch { }
    }
    $pyc = Get-Command python -ErrorAction SilentlyContinue
    if ($pyc -and $pyc.Source -and ($pyc.Source -notmatch 'WindowsApps') -and (Test-PythonExe $pyc.Source)) {
        return $pyc.Source
    }
    return $null
}

# --- ESP-IDF activation ----------------------------------------------------------------------

# Write a local (gitignored) tools\activate-idf.ps1 from the known EIM defaults.
function New-ActivateIdfHelper {
    param([string] $Path)
    $dir = Split-Path -Parent $Path
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    $content = @"
# Auto-generated by flash.ps1 - activates the EIM-installed ESP-IDF environment.
# The EIM profile activates the venv but does not export these three vars; idf.py needs them.
. $($IdfDefaults.Profile) *>`$null
`$env:IDF_PATH            = "$($IdfDefaults.IdfPath)"
`$env:IDF_TOOLS_PATH      = "$($IdfDefaults.ToolsPath)"
`$env:IDF_PYTHON_ENV_PATH = "$($IdfDefaults.PyEnvPath)"
"@
    Set-Content -Path $Path -Value $content -Encoding UTF8
}

# Return the path to a .ps1 the caller must dot-source (at SCRIPT scope) to put idf.py on PATH,
# or $null if idf.py is already available. Throws with guidance if it cannot be resolved.
function Resolve-ActivationScript {
    if (Get-Command idf.py -ErrorAction SilentlyContinue) {
        Detail "ESP-IDF already active ($((Get-Command idf.py).Source))."
        return $null
    }
    $helper = Join-Path $RepoRoot 'tools\activate-idf.ps1'
    if (Test-Path $helper) {
        Detail "Using tools\activate-idf.ps1"
        return $helper
    }
    if (Test-Path $IdfDefaults.Profile) {
        Detail "tools\activate-idf.ps1 missing; recreating it from the EIM defaults."
        New-ActivateIdfHelper -Path $helper
        return $helper
    }
    if ($env:IDF_PATH -and (Test-Path (Join-Path $env:IDF_PATH 'export.ps1'))) {
        Detail "Using `$env:IDF_PATH\export.ps1 (legacy)."
        return (Join-Path $env:IDF_PATH 'export.ps1')
    }
    throw @"
ESP-IDF environment not found and could not be auto-activated.
Create tools\activate-idf.ps1 (see docs\BUILD.md, Step 1) that dot-sources your EIM PowerShell
profile and sets IDF_PATH / IDF_TOOLS_PATH / IDF_PYTHON_ENV_PATH, or run your ESP-IDF export
script in this shell before re-running flash.ps1.
"@
}

# --- Protobuf setup (idempotent) -------------------------------------------------------------

function Ensure-Protos {
    $protoDir  = Join-Path $RepoRoot 'protobufs'
    $protoGlob = Join-Path $RepoRoot 'protobufs\meshtastic\*.proto'
    $genDir    = Join-Path $RepoRoot 'main\meshtastic'
    $venvDir   = Join-Path $RepoRoot 'tools\protovenv'
    $venvPy    = Join-Path $venvDir 'Scripts\python.exe'

    # 1. Proto sources (the .gitmodules submodule is broken; clone directly).
    $protoFiles = @(Get-ChildItem -Path $protoGlob -ErrorAction SilentlyContinue)
    if ($protoFiles.Count -eq 0) {
        if (Test-Path $protoDir) {
            throw "protobufs\ exists but has no meshtastic\*.proto. Delete protobufs\ and re-run."
        }
        if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
            throw "git not found on PATH; it's needed to clone the Meshtastic protobufs."
        }
        Step "Cloning Meshtastic protobufs"
        git clone --depth 1 $ProtobufsUrl $protoDir
        Assert-Exit "git clone protobufs"
        $protoFiles = @(Get-ChildItem -Path $protoGlob -ErrorAction SilentlyContinue)
    }
    else {
        Detail "Proto sources present ($($protoFiles.Count) .proto files)."
    }

    # 2. Isolated nanopb generator venv (grpcio-tools provides protoc; keeps the IDF venv pristine).
    if (-not (Test-Path $venvPy)) {
        if (-not $script:SystemPython) {
            throw "No system Python found to create tools\protovenv. Install Python 3, or pass -SysPython <python.exe>."
        }
        Step "Creating protobuf generator venv (tools\protovenv)"
        Detail "Using system Python: $script:SystemPython"
        if (-not (Test-Path (Split-Path -Parent $venvDir))) {
            New-Item -ItemType Directory -Path (Split-Path -Parent $venvDir) -Force | Out-Null
        }
        & $script:SystemPython -m venv $venvDir
        Assert-Exit "python -m venv"
        & $venvPy -m pip install --upgrade pip
        Assert-Exit "pip install --upgrade pip"
        & $venvPy -m pip install grpcio-tools
        Assert-Exit "pip install grpcio-tools"
    }
    else {
        Detail "Generator venv present."
    }

    # 3. Generate code when missing/stale/forced (headers count != protos count catches half runs).
    $genHeaders = @(Get-ChildItem -Path (Join-Path $genDir '*.pb.h') -ErrorAction SilentlyContinue)
    $needGen = $Regen -or ($genHeaders.Count -eq 0) -or ($genHeaders.Count -ne $protoFiles.Count)
    if ($needGen) {
        if ($Regen -and (Test-Path $genDir)) {
            Detail "Clearing existing generated files (main\meshtastic\*)."
            Remove-Item -Path (Join-Path $genDir '*') -Force -ErrorAction SilentlyContinue
        }
        if (-not (Test-Path $genDir)) { New-Item -ItemType Directory -Path $genDir -Force | Out-Null }
        Step "Generating nanopb protobuf code ($($protoFiles.Count) protos)"
        $generator = Join-Path $RepoRoot 'components\Nanopb\generator\nanopb_generator.py'
        # Relative paths matched to '-I protobufs' so output lands in main\meshtastic\.
        $protoArgs = $protoFiles | ForEach-Object { "protobufs\meshtastic\$($_.Name)" }
        & $venvPy $generator -S .cpp -I protobufs -D main @protoArgs
        Assert-Exit "nanopb generator"
        $made = @(Get-ChildItem -Path (Join-Path $genDir '*.pb.h') -ErrorAction SilentlyContinue)
        Good "Generated $($made.Count) protobuf headers."
    }
    else {
        Detail "Protobuf code up to date ($($genHeaders.Count)/$($protoFiles.Count))."
    }
}

# --- Build / port / flash / monitor ----------------------------------------------------------

function Invoke-Build {
    if ($Clean) {
        Step "idf.py fullclean"
        idf.py fullclean
        Assert-Exit "idf.py fullclean"
    }
    Step "Building firmware (the first build can take several minutes)"
    idf.py build
    Assert-Exit "idf.py build"
    Good "Build complete."
}

# ESP32-S3 native USB exposes VID 303A. Match the VID + a COM number; never match the friendly
# name's words (it's localized, e.g. the Russian 'Последовательный порт (COM4)').
function Get-EspPorts {
    @(Get-CimInstance Win32_PnPEntity -ErrorAction SilentlyContinue |
        Where-Object { $_.DeviceID -match 'VID_303A' -and $_.Name -match 'COM\d+' } |
        ForEach-Object {
            [pscustomobject]@{
                Port = [regex]::Match($_.Name, 'COM\d+').Value
                Name = $_.Name
            }
        } | Sort-Object Port -Unique)
}

function Resolve-Port {
    if ($Port) {
        if ($Port -notmatch '^COM\d+$') { throw "Invalid -Port '$Port' (expected e.g. COM4)." }
        if (-not (Get-EspPorts | Where-Object { $_.Port -eq $Port })) {
            Caution "$Port is not currently detected as an ESP32-S3; trying it anyway."
        }
        return $Port
    }
    $ports = @(Get-EspPorts)
    if ($ports.Count -eq 0) {
        throw @"
No ESP32-S3 (USB VID 303A) serial device found.
 - Plug the CardPuter into USB-C with a DATA cable (not charge-only).
 - Close any serial monitor / app that may be holding the port.
 - Or specify it explicitly:  .\flash.ps1 -Port COM4
"@
    }
    if ($ports.Count -eq 1) {
        Detail "Found device on $($ports[0].Port) ($($ports[0].Name))."
        return $ports[0].Port
    }
    if ($Yes) {
        throw "Multiple ESP32-S3 devices found; pick one with -Port. Detected: $(($ports | ForEach-Object { $_.Port }) -join ', ')."
    }
    Write-Host "Multiple ESP32-S3 devices found:" -ForegroundColor Yellow
    for ($i = 0; $i -lt $ports.Count; $i++) {
        Write-Host ("  [{0}] {1}  {2}" -f $i, $ports[$i].Port, $ports[$i].Name)
    }
    $sel = Read-Host "Select device number"
    if ($sel -notmatch '^\d+$' -or [int]$sel -ge $ports.Count) { throw "Invalid selection." }
    return $ports[[int]$sel].Port
}

function Confirm-Wipe {
    if ($FlashMode -eq 'App') { return }
    if ($Yes) {
        Caution "-Yes set: full flash will reset NVS to nvs.csv defaults (mesh keys wiped)."
        return
    }
    Write-Host ""
    Write-Host "  ========================== FULL FLASH - NVS WIPE ==========================" -ForegroundColor Yellow
    Write-Host "  A full flash rewrites bootloader + partition table + NVS + ota_data + app."  -ForegroundColor Yellow
    Write-Host "  Your mesh/channel keys and X25519 security keys live in NVS and WILL BE"      -ForegroundColor Red
    Write-Host "  ERASED, replaced by the factory defaults baked from nvs.csv."                 -ForegroundColor Red
    Write-Host ""
    Write-Host "  Back them up FIRST on the device:  Settings -> Export  (writes to the SD card)." -ForegroundColor Yellow
    Write-Host "  Node DB and chat history are SD-backed and will survive."                     -ForegroundColor DarkGray
    Write-Host "  For a routine update that KEEPS your keys, cancel and use:  .\flash.ps1 -AppOnly" -ForegroundColor DarkGray
    Write-Host "  ===========================================================================" -ForegroundColor Yellow
    Write-Host ""
    $ans = Read-Host "Type Y to wipe NVS and full-flash (anything else cancels)"
    if ($ans -notmatch '^(y|yes)$') {
        Write-Host "Cancelled - nothing flashed." -ForegroundColor Cyan
        exit 0
    }
}

function Invoke-Flash {
    param([Parameter(Mandatory)][string] $ResolvedPort)
    if ($FlashMode -eq 'App') {
        if (-not (Test-Path (Join-Path $RepoRoot 'build\flasher_args.json'))) {
            Caution "No prior full build detected - a blank device needs a full flash. If it doesn't boot, re-run without -AppOnly."
        }
        Step "Flashing app partition only (NVS preserved) on $ResolvedPort"
        idf.py -p $ResolvedPort app-flash
        Assert-Exit "idf.py app-flash"
    }
    else {
        Step "Full-flashing $ResolvedPort"
        idf.py -p $ResolvedPort flash
        Assert-Exit "idf.py flash"
    }
    Good "Flash complete - the device will reboot into the new firmware."
}

function Invoke-Monitor {
    param([Parameter(Mandatory)][string] $ResolvedPort)
    Step "Opening serial monitor on $ResolvedPort (exit with Ctrl+])"
    idf.py -p $ResolvedPort monitor   # interactive; a Ctrl+] exit is not a failure
}

function Write-Summary {
    param([string] $ResolvedPort)
    Write-Host ""
    Good "Done."
    if ($ResolvedPort) {
        Write-Host "  Flashed to:   $ResolvedPort  ($FlashMode flash)" -ForegroundColor DarkGray
        Write-Host "  Monitor:      idf.py -p $ResolvedPort monitor   (or re-run with -Monitor)" -ForegroundColor DarkGray
    }
    if ($FlashMode -eq 'Full') {
        Write-Host "  Reminder:     NVS was reset - re-import your keys if you exported them." -ForegroundColor DarkGray
    }
    Write-Host "  Next time:    .\flash.ps1 -AppOnly  keeps NVS keys (routine app update)." -ForegroundColor DarkGray
}

# --- Orchestration (runs at SCRIPT scope so dot-sourced activation persists) -----------------

$OrigLocation = Get-Location
try {
    if ($Help) { Show-Help; exit 0 }

    # Argument precedence / validation (fail fast, before any slow work).
    if ($AppOnly -and $Full) { throw "-AppOnly and -Full are mutually exclusive." }
    $FlashMode = if ($AppOnly) { 'App' } else { 'Full' }
    $doMonitor = [bool]$Monitor
    if ($doMonitor -and $NoFlash) {
        Caution "-Monitor ignored because -NoFlash was given (nothing to monitor)."
        $doMonitor = $false
    }

    Assert-RepoRoot
    Set-Location $RepoRoot

    # Resolve a system Python BEFORE activation (activation changes which 'python' is on PATH).
    $script:SystemPython = Get-SystemPython

    # Activate ESP-IDF. Dot-source at SCRIPT scope so any idf.py function/alias and PATH the
    # profile defines persist for the rest of the run. Shield the vendor profile from this
    # script's StrictMode / Stop preference while sourcing.
    Step "Preparing ESP-IDF environment"
    $activation = Resolve-ActivationScript
    if ($activation) {
        $savedEAP = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        Set-StrictMode -Off
        . $activation
        Set-StrictMode -Version Latest
        $ErrorActionPreference = $savedEAP
        if (-not (Get-Command idf.py -ErrorAction SilentlyContinue)) {
            throw "Activation ran but idf.py is still unavailable. Check the paths in tools\activate-idf.ps1 (see docs\BUILD.md)."
        }
    }
    idf.py --version
    Assert-Exit "idf.py --version"

    Ensure-Protos

    if ($SetupOnly) {
        Good "Setup complete (-SetupOnly). Run .\flash.ps1 to build & flash."
        exit 0
    }

    Invoke-Build

    if ($NoFlash) {
        Good "Build complete (-NoFlash). Skipping flash."
        Write-Host "  To flash:  .\flash.ps1           (full flash, prompts before wiping NVS)" -ForegroundColor DarkGray
        Write-Host "             .\flash.ps1 -AppOnly  (app only, preserves NVS keys)" -ForegroundColor DarkGray
        exit 0
    }

    $resolvedPort = Resolve-Port
    Confirm-Wipe
    Invoke-Flash -ResolvedPort $resolvedPort
    if ($doMonitor) { Invoke-Monitor -ResolvedPort $resolvedPort }
    Write-Summary -ResolvedPort $resolvedPort
}
catch {
    Write-Host ""
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
finally {
    Set-Location $OrigLocation -ErrorAction SilentlyContinue
}
