[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$projectRoot = Split-Path -Parent $PSScriptRoot
$composeFile = "deploy/compose.yaml"
$cloudflaredPath = Join-Path $projectRoot ".tools\bin\cloudflared.exe"
$tunnelPidFile = Join-Path $projectRoot ".cloudflare-tunnel.pid"

function Stop-ProcessTree {
    param([int]$RootProcessId)

    $processes = @(Get-CimInstance Win32_Process)
    $pending = New-Object System.Collections.Generic.Queue[int]
    $descendants = New-Object System.Collections.Generic.List[int]
    $pending.Enqueue($RootProcessId)
    while ($pending.Count -gt 0) {
        $parentId = $pending.Dequeue()
        foreach ($child in $processes | Where-Object { $_.ParentProcessId -eq $parentId }) {
            $descendants.Add([int]$child.ProcessId)
            $pending.Enqueue([int]$child.ProcessId)
        }
    }
    $descendantIds = $descendants.ToArray()
    [array]::Reverse($descendantIds)
    foreach ($processId in $descendantIds) {
        Stop-Process -Id $processId -ErrorAction SilentlyContinue
    }
    Stop-Process -Id $RootProcessId -ErrorAction SilentlyContinue
}

if (Test-Path -LiteralPath $tunnelPidFile) {
    $tunnelPidText = (Get-Content -LiteralPath $tunnelPidFile -Raw).Trim()
    if ($tunnelPidText -match '^\d+$') {
        Stop-ProcessTree -RootProcessId ([int]$tunnelPidText)
    }
    Set-Content -LiteralPath $tunnelPidFile -Value "" -Encoding ascii
}

if (Test-Path -LiteralPath $cloudflaredPath) {
    $resolvedCloudflaredPath = (Resolve-Path -LiteralPath $cloudflaredPath).Path
    Get-CimInstance Win32_Process -Filter "Name = 'cloudflared.exe'" |
        Where-Object { $_.ExecutablePath -eq $resolvedCloudflaredPath } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -ErrorAction SilentlyContinue }
}

& wsl.exe -d Ubuntu --cd $projectRoot -- docker compose --env-file .env -f $composeFile down
if ($LASTEXITCODE -ne 0) {
    throw "Docker Compose failed to stop the ML API."
}

Write-Host "SomniSignal and its HTTPS tunnel are stopped." -ForegroundColor Green
