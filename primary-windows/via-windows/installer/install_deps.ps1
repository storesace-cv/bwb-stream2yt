# Extrai/instala deps verificadas para bin_dir (usado no build CI e repair).
param(
    [Parameter(Mandatory = $true)][string]$ManifestPath,
    [Parameter(Mandatory = $true)][string]$CacheDir,
    [Parameter(Mandatory = $true)][string]$BinDir,
    [switch]$SkipDownload
)

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path

if (-not $SkipDownload) {
    & (Join-Path $here "download_deps.ps1") -ManifestPath $ManifestPath -CacheDir $CacheDir
}

$manifest = Get-Content -LiteralPath $ManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
New-Item -ItemType Directory -Force -Path $BinDir | Out-Null

# --- FFmpeg ---
$ff = $manifest.components.ffmpeg
$ffZip = Join-Path $CacheDir $ff.offline_cache_name
if (-not (Test-Path -LiteralPath $ffZip)) { throw "FFmpeg em falta na cache: $ffZip" }
$ffStage = Join-Path $env:TEMP ("bwb-ff-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path $ffStage | Out-Null
try {
    Expand-Archive -LiteralPath $ffZip -DestinationPath $ffStage -Force
    $inner = Join-Path $ffStage $ff.zip_inner_prefix
    if (-not (Test-Path -LiteralPath $inner)) {
        $inner = Get-ChildItem -Directory $ffStage | Select-Object -First 1 -ExpandProperty FullName
    }
    $ffDest = Join-Path $BinDir "ffmpeg"
    if (Test-Path -LiteralPath $ffDest) { Remove-Item -Recurse -Force $ffDest }
    New-Item -ItemType Directory -Force -Path $ffDest | Out-Null
    Copy-Item -Path (Join-Path $inner "*") -Destination $ffDest -Recurse -Force
    foreach ($rel in $ff.required_files) {
        $path = Join-Path $ffDest $rel
        if (-not (Test-Path -LiteralPath $path)) { throw "Ficheiro FFmpeg em falta: $rel" }
    }
    Write-Host "FFmpeg instalado em $ffDest"
}
finally {
    Remove-Item -Recurse -Force $ffStage -ErrorAction SilentlyContinue
}

# --- GStreamer (MSI oficial: extract administrativo para árvore local) ---
$gst = $manifest.components.gstreamer_runtime
$gstMsi = Join-Path $CacheDir $gst.offline_cache_name
if (-not (Test-Path -LiteralPath $gstMsi)) { throw "GStreamer em falta na cache: $gstMsi" }
$gstDest = Join-Path $BinDir "gstreamer"
$gstExtract = Join-Path $env:TEMP ("bwb-gst-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path $gstExtract | Out-Null
try {
    # /a = administrative install (extrai ficheiros sem serviço/arranque)
    $msiArgs = @(
        "/a", "`"$gstMsi`"",
        "/qn",
        "TARGETDIR=`"$gstExtract`""
    )
    $p = Start-Process -FilePath "msiexec.exe" -ArgumentList $msiArgs -Wait -PassThru
    if ($p.ExitCode -ne 0) {
        throw "msiexec /a falhou com código $($p.ExitCode). Instalação interrompida."
    }
    # Procurar árvore com gst-launch-1.0.exe
    $launch = Get-ChildItem -Path $gstExtract -Recurse -Filter "gst-launch-1.0.exe" -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if (-not $launch) {
        throw "gst-launch-1.0.exe não encontrado após extract do MSI."
    }
    $extractedRoot = $launch.Directory.Parent.FullName
    if (Test-Path -LiteralPath $gstDest) { Remove-Item -Recurse -Force $gstDest }
    New-Item -ItemType Directory -Force -Path $gstDest | Out-Null
    Copy-Item -Path (Join-Path $extractedRoot "*") -Destination $gstDest -Recurse -Force
    Write-Host "GStreamer runtime instalado em $gstDest"
}
finally {
    Remove-Item -Recurse -Force $gstExtract -ErrorAction SilentlyContinue
}
