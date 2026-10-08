# Checks locais pós-instalação (PowerShell — sem Python no cliente).
param(
    [Parameter(Mandatory = $true)][string]$BinDir,
    [Parameter(Mandatory = $true)][string]$DataDir,
    [switch]$RequireGStreamer,
    [string]$HelperPath = ""
)

$ErrorActionPreference = "Stop"
$report = [ordered]@{ ok = $false; checks = [ordered]@{} }

function Test-ExeVersion([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) {
        return @{ ok = $false; summary = "Ausente: $Path" }
    }
    try {
        $p = Start-Process -FilePath $Path -ArgumentList "-version" -NoNewWindow -Wait -PassThru `
            -RedirectStandardOutput "$env:TEMP\bwb-ver-out.txt" -RedirectStandardError "$env:TEMP\bwb-ver-err.txt"
        $line = ""
        if (Test-Path "$env:TEMP\bwb-ver-out.txt") {
            $line = (Get-Content "$env:TEMP\bwb-ver-out.txt" -TotalCount 1 -ErrorAction SilentlyContinue)
        }
        return @{ ok = ($p.ExitCode -eq 0); summary = "$line" }
    }
    catch {
        return @{ ok = $false; summary = $_.Exception.GetType().Name }
    }
}

$ffmpeg = Join-Path $BinDir "ffmpeg\bin\ffmpeg.exe"
$ffprobe = Join-Path $BinDir "ffmpeg\bin\ffprobe.exe"
$ff = Test-ExeVersion $ffmpeg
$fp = Test-ExeVersion $ffprobe
$report.checks.ffmpeg = @{ ok = ($ff.ok -and $fp.ok); ffmpeg = $ff.summary; ffprobe = $fp.summary }

# Dados: presença/leitura sem expor chaves
$configPath = Join-Path $DataDir "effective_config.json"
$keys = @(Get-ChildItem -Path $DataDir -Filter "stream_key_*.dpapi" -ErrorAction SilentlyContinue)
$keyReadable = $null
if ($keys.Count -gt 0) {
    try {
        $bytes = [System.IO.File]::ReadAllBytes($keys[0].FullName)
        $keyReadable = ($bytes.Length -ge 4)
        $bytes = $null
    }
    catch { $keyReadable = $false }
}
$report.checks.data = @{
    ok            = $true
    config_present = (Test-Path -LiteralPath $configPath)
    key_present   = ($keys.Count -gt 0)
    key_readable  = $keyReadable
}

# GStreamer helper prove
if (-not $HelperPath) {
    $HelperPath = Join-Path $BinDir "gst_rtmps_helper.exe"
}
$gstRoot = Join-Path $BinDir "gstreamer"
$env:BWB_GST_ROOT = $gstRoot
$env:PATH = (Join-Path $gstRoot "bin") + ";" + $env:PATH
$gstOk = $false
$gstDetail = $null
if (Test-Path -LiteralPath $HelperPath) {
    try {
        $out = & $HelperPath --prove 2>&1 | Out-String
        $gstDetail = $out.Trim()
        $obj = $gstDetail | ConvertFrom-Json
        $gstOk = [bool]$obj.ok
    }
    catch {
        $gstDetail = $_.Exception.Message
        $gstOk = $false
    }
}
else {
    $gstDetail = "auxiliar ausente"
}
$report.checks.gstreamer = @{ ok = $gstOk; detail = $gstDetail }

$ok = [bool]$report.checks.ffmpeg.ok -and [bool]$report.checks.data.ok
if ($RequireGStreamer) { $ok = $ok -and $gstOk }
$report.ok = $ok

$report | ConvertTo-Json -Depth 6
if (-not $ok) { exit 1 }
exit 0
