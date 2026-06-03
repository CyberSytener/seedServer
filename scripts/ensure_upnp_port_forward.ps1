param(
    [string]$InternalIp = "",
    [switch]$SkipUdp443
)

$ErrorActionPreference = "Stop"

function Resolve-InternalIp {
    if ($InternalIp) {
        return $InternalIp
    }

    $defaultRoute = Get-NetRoute -DestinationPrefix "0.0.0.0/0" -ErrorAction SilentlyContinue |
        Sort-Object -Property RouteMetric |
        Select-Object -First 1

    if ($defaultRoute) {
        $candidate = Get-NetIPAddress -AddressFamily IPv4 -InterfaceIndex $defaultRoute.InterfaceIndex -ErrorAction SilentlyContinue |
            Where-Object { $_.IPAddress -notlike "169.254.*" } |
            Select-Object -First 1
        if ($candidate) {
            return $candidate.IPAddress
        }
    }

    $fallback = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254.*" } |
        Select-Object -First 1
    if ($fallback) {
        return $fallback.IPAddress
    }

    throw "Could not determine internal IPv4 address."
}

function Ensure-Mapping {
    param(
        [Parameter(Mandatory = $true)][object]$Maps,
        [Parameter(Mandatory = $true)][int]$ExternalPort,
        [Parameter(Mandatory = $true)][string]$Protocol,
        [Parameter(Mandatory = $true)][int]$InternalPort,
        [Parameter(Mandatory = $true)][string]$InternalClient,
        [Parameter(Mandatory = $true)][string]$Description
    )

    $existing = $null
    foreach ($m in $Maps) {
        if ($m.ExternalPort -eq $ExternalPort -and $m.Protocol -eq $Protocol) {
            $existing = $m
            break
        }
    }

    if ($existing -ne $null) {
        if ($existing.InternalClient -ne $InternalClient -or $existing.InternalPort -ne $InternalPort -or -not $existing.Enabled) {
            try { $Maps.Remove($ExternalPort, $Protocol) } catch {}
            $Maps.Add($ExternalPort, $Protocol, $InternalPort, $InternalClient, $true, $Description) | Out-Null
            Write-Host "UPDATED $Protocol $ExternalPort -> $InternalClient`:$InternalPort"
        } else {
            Write-Host "OK $Protocol $ExternalPort -> $InternalClient`:$InternalPort"
        }
        return
    }

    $Maps.Add($ExternalPort, $Protocol, $InternalPort, $InternalClient, $true, $Description) | Out-Null
    Write-Host "ADDED $Protocol $ExternalPort -> $InternalClient`:$InternalPort"
}

$resolvedIp = Resolve-InternalIp

$nat = New-Object -ComObject HNetCfg.NATUPnP
$maps = $nat.StaticPortMappingCollection
if ($null -eq $maps) {
    throw "Router does not expose UPnP port mapping collection."
}

Ensure-Mapping -Maps $maps -ExternalPort 80 -Protocol "TCP" -InternalPort 80 -InternalClient $resolvedIp -Description "NeoEats Caddy HTTP"
Ensure-Mapping -Maps $maps -ExternalPort 443 -Protocol "TCP" -InternalPort 443 -InternalClient $resolvedIp -Description "NeoEats Caddy HTTPS"

if (-not $SkipUdp443) {
    Ensure-Mapping -Maps $maps -ExternalPort 443 -Protocol "UDP" -InternalPort 443 -InternalClient $resolvedIp -Description "NeoEats Caddy HTTP3"
}

Write-Host "UPnP forwarding is set for host $resolvedIp." -ForegroundColor Green
