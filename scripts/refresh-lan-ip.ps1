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

  Hotspots are picked up automatically, in this order of preference:
    1. This PC sharing its own Windows Mobile Hotspot (the phone joins the
       PC; the PC is 192.168.137.1).
    2. The PC joined to the phone's hotspot, over Wi-Fi or USB tethering
       (iPhone hotspots are 172.20.10.x; older Android ones 192.168.43.x;
       USB tethering shows up as an "Ethernet" adapter).
    3. Any other Wi-Fi, then wired Ethernet with an internet route.
  Only adapters that are connected count: Windows keeps an old address on
  a disconnected Wi-Fi adapter for a while, which used to get picked.

  To choose by hand:
      powershell -File scripts/refresh-lan-ip.ps1 -Interface WiFi
      powershell -File scripts/refresh-lan-ip.ps1 -Ip 172.20.10.13

.NOTES
  If your phone and PC are on different physical networks (e.g. phone on
  a guest/extended Wi-Fi node, PC on Ethernet through the main router),
  no single "LAN IP" will work for both - they need to share one network.
#>

param(
    # Use this adapter (its name as 'ipconfig' or Get-NetAdapter shows it).
    [string]$Interface,
    # Use this exact IPv4 address, skipping detection.
    [string]$Ip
)

$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
$envPath = Join-Path $repoRoot '.env'

# Virtual adapters never carry a phone's traffic. Matched on the adapter's
# description, not just its name ("Ethernet 2" can be VirtualBox). Not a bare
# 'Virtual': Windows Mobile Hotspot runs on the "Microsoft Wi-Fi Direct
# Virtual Adapter", which is exactly the one we want when hotspotting.
$virtualPattern = 'Hyper-V|VirtualBox|VMware|Docker|WSL|Loopback|TAP-|Tailscale|WireGuard|ZeroTier|VPN'

# Connected adapters only (a disconnected Wi-Fi adapter keeps its last
# address for up to its lease time).
$upAdapters = @{}
Get-NetAdapter -IncludeHidden -ErrorAction SilentlyContinue |
    Where-Object { $_.Status -eq 'Up' } |
    ForEach-Object { $upAdapters[$_.ifIndex] = $_ }

$withRoute = @(Get-NetRoute -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue | ForEach-Object { $_.InterfaceIndex })

$candidates = @(Get-NetIPAddress -AddressFamily IPv4 |
    Where-Object {
        $adapter = $upAdapters[$_.InterfaceIndex]
        $adapter -and
        "$($_.InterfaceAlias) $($adapter.InterfaceDescription)" -notmatch $virtualPattern -and
        $_.AddressState -in @('Preferred', 'Deprecated') -and
        $_.IPAddress -notlike '169.254.*' -and
        $_.IPAddress -ne '127.0.0.1'
    } |
    ForEach-Object {
        $description = $upAdapters[$_.InterfaceIndex].InterfaceDescription
        # Lower rank = preferred. See the description above for the order.
        $rank, $kind =
            if ($_.IPAddress -eq '192.168.137.1' -or $description -match 'Wi-Fi Direct') { 0, "this PC's Mobile Hotspot" }
            elseif ($_.IPAddress -like '172.20.10.*' -or $_.IPAddress -like '192.168.43.*' -or
                    $description -match 'Remote NDIS|RNDIS|Apple Mobile Device|iPhone|Android') { 1, "phone hotspot / tethering" }
            elseif ($_.InterfaceAlias -match 'Wi-?Fi|WLAN|Wireless' -or $description -match 'Wireless|Wi-?Fi|802\.11') { 2, 'Wi-Fi' }
            elseif ($withRoute -contains $_.InterfaceIndex) { 3, 'wired, with internet' }
            else { 4, 'other' }
        [pscustomobject]@{ Alias = $_.InterfaceAlias; IPAddress = $_.IPAddress; Rank = $rank; Kind = $kind; Description = $description }
    } |
    Sort-Object Rank)

if ($Ip) {
    $chosen = [pscustomobject]@{ Alias = '(given with -Ip)'; IPAddress = $Ip; Kind = 'manual' }
} elseif ($Interface) {
    $chosen = $candidates | Where-Object { $_.Alias -eq $Interface } | Select-Object -First 1
    if (-not $chosen) {
        Write-Error "No connected IPv4 address on adapter '$Interface'. Connected candidates: $(($candidates | ForEach-Object { $_.Alias }) -join ', ')"
        exit 1
    }
} else {
    if (-not $candidates) {
        Write-Error "No connected LAN IPv4 address found. Is Wi-Fi / the hotspot connected? Run 'ipconfig', then pass -Ip <address>."
        exit 1
    }
    $chosen = $candidates[0]
}

if ($candidates.Count -gt 1 -or $Ip -or $Interface) {
    Write-Host "Connected network adapters (best first):" -ForegroundColor Yellow
    $candidates | ForEach-Object { Write-Host ("  {0,-28} {1,-16} {2}" -f $_.Alias, $_.IPAddress, $_.Kind) }
    Write-Host "Using $($chosen.Alias) ($($chosen.IPAddress)) - your phone must be on the same network as this adapter. Pass -Interface <name> to choose another." -ForegroundColor Yellow
}

$ip = $chosen.IPAddress
Write-Host "Detected LAN IP: $ip ($($chosen.Alias), $($chosen.Kind))" -ForegroundColor Cyan

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
