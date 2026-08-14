# Build da imagem Docker no Windows via WSL (Docker Engine do Linux).
# Uso:
#   .\build.ps1          # build + tag local
#   .\build.ps1 prod     # build + login + push Docker Hub
param(
    [Parameter(Position = 0)]
    [ValidateSet("", "prod")]
    [string]$Mode = ""
)

$ErrorActionPreference = "Stop"

function ConvertTo-WslPath {
    param([string]$WinPath)
    $full = [System.IO.Path]::GetFullPath($WinPath)
    if ($full -notmatch '^([A-Za-z]):\\(.*)$') {
        throw "Path Windows inválido para WSL: $WinPath"
    }
    $drive = $Matches[1].ToLowerInvariant()
    $rest = ($Matches[2] -replace '\\', '/')
    return "/mnt/$drive/$rest"
}

function Assert-WslDocker {
    $null = Get-Command wsl -ErrorAction Stop
    wsl -e docker version *> $null
    if ($LASTEXITCODE -ne 0) {
        throw @"
Docker não respondeu dentro do WSL.
Neste PC o Docker Engine está no WSL (não há Docker Desktop no PATH do Windows).
Abra o WSL e confira: docker version
"@
    }
}

$here = $PSScriptRoot
$wslDir = ConvertTo-WslPath $here
$script = Join-Path $here "build.sh"

if (-not (Test-Path $script)) {
    throw "build.sh não encontrado em $here"
}

Assert-WslDocker

$raw = [System.IO.File]::ReadAllText($script)
$normalized = $raw -replace "`r`n", "`n" -replace "`r", "`n"
if ($raw.Contains("`r")) {
    $utf8NoBom = New-Object System.Text.UTF8Encoding $false
    [System.IO.File]::WriteAllText($script, $normalized, $utf8NoBom)
}

$arg = if ($Mode) { $Mode } else { "" }
$bashCmd = "cd '$wslDir' && chmod +x ./build.sh && ./build.sh $arg"

Write-Host "WSL: $wslDir"
Write-Host "Comando: ./build.sh $(if ($Mode) { $Mode } else { '(local)' })"
wsl -e bash -lc $bashCmd
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
