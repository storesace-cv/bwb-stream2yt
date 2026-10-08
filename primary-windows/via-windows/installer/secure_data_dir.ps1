param(
    [Parameter(Mandatory = $true)][string]$DataDir,
    [Parameter(Mandatory = $true)][string]$BinDir
)

$ErrorActionPreference = "Stop"

function Set-RestrictedAcl {
    param(
        [string]$Path,
        [switch]$WritableByUsers
    )
    if (-not (Test-Path -LiteralPath $Path)) {
        New-Item -ItemType Directory -Path $Path -Force | Out-Null
    }
    # Remover herança; SYSTEM/Admins full; serviço; Authenticated Users RX ou M.
    icacls $Path /inheritance:r | Out-Null
    icacls $Path /grant:r "SYSTEM:(OI)(CI)F" | Out-Null
    icacls $Path /grant:r "Administrators:(OI)(CI)F" | Out-Null
    if ($WritableByUsers) {
        icacls $Path /grant:r "NT AUTHORITY\LOCAL SERVICE:(OI)(CI)M" | Out-Null
        icacls $Path /grant:r "NT AUTHORITY\NETWORK SERVICE:(OI)(CI)M" | Out-Null
        icacls $Path /grant:r "Authenticated Users:(OI)(CI)M" | Out-Null
    }
    else {
        icacls $Path /grant:r "NT AUTHORITY\LOCAL SERVICE:(OI)(CI)RX" | Out-Null
        icacls $Path /grant:r "NT AUTHORITY\NETWORK SERVICE:(OI)(CI)RX" | Out-Null
        icacls $Path /grant:r "Authenticated Users:(OI)(CI)RX" | Out-Null
    }
}

Set-RestrictedAcl -Path $DataDir -WritableByUsers
Set-RestrictedAcl -Path $BinDir
Write-Output "ACLs aplicadas em data/bin."
