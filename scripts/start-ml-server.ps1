[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$projectRoot = Split-Path -Parent $PSScriptRoot
$healthUrl = "http://127.0.0.1:8000/health"
$environmentFile = Join-Path $projectRoot ".env"

if (-not (Test-Path -LiteralPath $environmentFile)) {
    $tokenBytes = New-Object byte[] 32
    $randomGenerator = [Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $randomGenerator.GetBytes($tokenBytes)
    }
    finally {
        $randomGenerator.Dispose()
    }
    $apiToken = -join ($tokenBytes | ForEach-Object { $_.ToString("x2") })
    @(
        "ML_API_TOKEN=$apiToken"
        "PUBLIC_UPLOADS_ENABLED=false"
        "REGULATORY_REVIEW_COMPLETE=false"
        "LOCAL_UI_ENABLED=true"
    ) | Set-Content -LiteralPath $environmentFile -Encoding utf8
    Write-Host "Created a private API token in .env. Public uploads remain disabled."
}

$existingKeepAlive = Get-CimInstance Win32_Process -Filter "Name = 'wsl.exe'" |
    Where-Object {
        $_.CommandLine -like "*--exec /usr/bin/tail -f /dev/null*"
    }

if (-not $existingKeepAlive) {
    Write-Host "Starting the hidden WSL keepalive process..."
    Start-Process `
        -FilePath "$env:SystemRoot\System32\wsl.exe" `
        -ArgumentList @("-d", "Ubuntu", "--exec", "/usr/bin/tail", "-f", "/dev/null") `
        -WindowStyle Hidden
    Start-Sleep -Seconds 2
}

Write-Host "Starting Ubuntu and Docker..."
& wsl.exe -d Ubuntu -u root -- systemctl start docker
if ($LASTEXITCODE -ne 0) {
    throw "Docker failed to start inside Ubuntu."
}

Write-Host "Starting the ML API container..."
& wsl.exe -d Ubuntu --cd $projectRoot -- docker compose up --build -d
if ($LASTEXITCODE -ne 0) {
    throw "Docker Compose failed to start the ML API."
}

Write-Host "Waiting for the ML API health check..."
$healthy = $false
for ($attempt = 1; $attempt -le 15; $attempt++) {
    try {
        $response = Invoke-RestMethod -Uri $healthUrl -TimeoutSec 2
        if ($response.status -eq "healthy") {
            $healthy = $true
            break
        }
    }
    catch {
        Start-Sleep -Seconds 1
    }
}

if (-not $healthy) {
    & wsl.exe -d Ubuntu --cd $projectRoot -- docker compose ps
    throw "The container started, but the health endpoint did not become ready."
}

Write-Host "ML server is healthy." -ForegroundColor Green
Write-Host "Webapp: http://localhost:8000/"
Write-Host "API:    http://localhost:8000/api"
Write-Host "Docs: http://localhost:8000/docs"
