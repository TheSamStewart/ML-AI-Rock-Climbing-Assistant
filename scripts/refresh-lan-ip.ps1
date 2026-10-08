<#
.SYNOPSIS
  Detects this machine's current LAN IPv4 address, writes it to .env as
  HOST_LAN_IP, and (if the stack is already running) recreates just the
  frontend container so Metro/Expo picks it up.

.DESCRIPTION
  docker-compose.yml passes HOST_LAN_IP to the frontend container as
  REACT_NATIVE_PACKAGER_HOSTNAME, because a container on Windows Docker
  Desktop can't see the host's real Wi-Fi/Ethernet adapter - only its own
  internal bridge IP. Whenever you switch networks (new Wi-Fi, DHCP
  renewal, docking/undocking, etc.) that advertised IP goes stale and
  Expo Go reports "Could not connect to server" even though everything
  else is healthy.

  Run this any time that happens instead of hand-editing .env or
  docker-compose.yml:

      powershell -File scripts/refresh-lan-ip.ps1

  This only ever changes an environment variable, never the image, so it
  does NOT rebuild anything - recreating the container takes seconds, not
  the minutes a `docker compose up --build` would.

.NOTES
  If your phone and PC are on different physical networks (e.g. phone on
  a guest/extended Wi-Fi node, PC on Ethernet through the main router),
  no single "LAN IP" will work for both - they need to share one network.
#>

$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
$envPath = Join-Path $repoRoot '.env'

# Candidate physical adapters: real DHCP/manual IPv4 addresses, excluding
# loopback, link-local (APIPA, 169.254.x.x), and virtual adapters Docker
# Desktop/WSL/VPNs create (these never carry LAN traffic from a phone).
$excludePattern = 'Loopback|vEthernet|WSL|Docker|Virtual|Hyper-V|Tailscale|VPN'

$candidates = Get-NetIPAddress -AddressFamily IPv4 |
    Where-Object {
        $_.InterfaceAlias -notmatch $excludePattern -and
        $_.IPAddress -notlike '169.254.*' -and
        $_.IPAddress -ne '127.0.0.1'
    }

if (-not $candidates) {
    Write-Error "No candidate LAN IPv4 address found. Run 'ipconfig' and set HOST_LAN_IP in .env manually."
    exit 1
}

# Prefer a Wi-Fi adapter (phones almost always join over Wi-Fi) if one is
# among the candidates; otherwise fall back to whatever was found.
$chosen = $candidates | Where-Object { $_.InterfaceAlias -match 'Wi-?Fi' } | Select-Object -First 1
if (-not $chosen) { $chosen = $candidates | Select-Object -First 1 }

if ($candidates.Count -gt 1) {
    Write-Host "Multiple network adapters found:" -ForegroundColor Yellow
    $candidates | ForEach-Object { Write-Host "  $($_.InterfaceAlias): $($_.IPAddress)" }
    Write-Host "Using $($chosen.InterfaceAlias) ($($chosen.IPAddress)) - your phone must be on the same network as this adapter." -ForegroundColor Yellow
}

$ip = $chosen.IPAddress
Write-Host "Detected LAN IP: $ip ($($chosen.InterfaceAlias))" -ForegroundColor Cyan

# Update (or add) HOST_LAN_IP in .env, preserving every other line as-is.
if (Test-Path $envPath) {
    $lines = Get-Content $envPath
} else {
    $lines = @()
}

$pattern = '^HOST_LAN_IP=.*$'
if ($lines -match $pattern) {
    $lines = $lines -replace $pattern, "HOST_LAN_IP=$ip"
} else {
    $lines += "HOST_LAN_IP=$ip"
}
Set-Content -Path $envPath -Value $lines -Encoding utf8

Write-Host "Updated .env: HOST_LAN_IP=$ip" -ForegroundColor Green

# If the stack is already up, recreate just the frontend container (env-var
# only change - no rebuild) so Metro re-advertises the new address.
Push-Location $repoRoot
try {
    $running = docker compose ps -q frontend 2>$null
    if ($running) {
        Write-Host "Recreating frontend container..." -ForegroundColor Cyan
        docker compose up -d --force-recreate frontend
    } else {
        Write-Host "Frontend container isn't running - it'll pick up HOST_LAN_IP next time you run 'docker compose up'." -ForegroundColor Yellow
    }
} finally {
    Pop-Location
}
