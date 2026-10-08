# Download HTTPS verificado a partir do manifesto (sem Python/pip no cliente).
param(
    [Parameter(Mandatory = $true)][string]$ManifestPath,
    [Parameter(Mandatory = $true)][string]$CacheDir,
    [string[]]$Component = @("ffmpeg", "gstreamer_runtime"),
    [switch]$Force
)

$ErrorActionPreference = "Stop"

function Assert-NoPlaceholder([string]$Value, [string]$Field) {
    if ($Value -match "REPLACE_WITH_|YOUR_|TODO_|XXX_|changeme") {
        throw "Manifesto inválido: $Field contém placeholder."
    }
}

function Get-Sha256Lower([string]$Path) {
    return (Get-FileHash -Algorithm SHA256 -Path $Path).Hash.ToLowerInvariant()
}

if (-not (Test-Path -LiteralPath $ManifestPath)) {
    throw "Manifesto ausente: $ManifestPath"
}
$manifest = Get-Content -LiteralPath $ManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
New-Item -ItemType Directory -Force -Path $CacheDir | Out-Null

foreach ($name in $Component) {
    $comp = $manifest.components.$name
    if ($null -eq $comp) { throw "Componente desconhecido: $name" }
    if ($comp.bundled_with_app -eq $true) {
        Write-Host "SKIP $name (empacotado com a app)"
        continue
    }
    $url = [string]$comp.url
    $sha = ([string]$comp.sha256).ToLowerInvariant()
    $cacheName = [string]$comp.offline_cache_name
    Assert-NoPlaceholder $url "url"
    Assert-NoPlaceholder $sha "sha256"
    if ($url -notmatch "^https://") { throw "Apenas HTTPS permitido ($name)" }
    if ($sha -notmatch "^[0-9a-f]{64}$") { throw "SHA256 inválido ($name)" }

    $dest = Join-Path $CacheDir $cacheName
    if ((Test-Path -LiteralPath $dest) -and -not $Force) {
        $actual = Get-Sha256Lower $dest
        if ($actual -ne $sha) {
            throw "Cache inválida para $name (hash). Use -Force ou apague o ficheiro."
        }
        Write-Host "OK cache $name"
        continue
    }

    $partial = "$dest.partial"
    Write-Host "A descarregar $name …"
    try {
        Invoke-WebRequest -Uri $url -OutFile $partial -UseBasicParsing
    }
    catch {
        if (Test-Path -LiteralPath $partial) { Remove-Item -LiteralPath $partial -Force }
        throw "Falha no download de $name. Pode repetir."
    }
    $actual = Get-Sha256Lower $partial
    if ($actual -ne $sha) {
        Remove-Item -LiteralPath $partial -Force
        throw "Hash SHA256 não coincide para $name. Instalação interrompida."
    }
    Move-Item -LiteralPath $partial -Destination $dest -Force
    Write-Host "OK $name -> $dest"
}
