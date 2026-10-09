# Run from an elevated PowerShell only if the phone cannot open its Bluetooth backup link.
$ErrorActionPreference = 'Stop'
$ruleName = 'Phone Slide Remote Bluetooth'
if (-not (Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Action Allow -Protocol TCP `
        -LocalPort 8765 -InterfaceAlias 'Bluetooth Network Connection' -RemoteAddress LocalSubnet -Profile Any | Out-Null
}
Get-NetFirewallRule -DisplayName $ruleName | Select-Object DisplayName,Enabled,Direction,Action
