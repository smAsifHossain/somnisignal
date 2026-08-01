[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$projectRoot = Split-Path -Parent $PSScriptRoot
$healthUrl = "http://127.0.0.1:8000/health"
$environmentFile = Join-Path $projectRoot ".env"
$cloudflaredPath = Join-Path $projectRoot ".tools\bin\cloudflared.exe"
$wranglerEntryPoint = Join-Path $projectRoot "worker\node_modules\wrangler\bin\wrangler.js"
$tunnelPidFile = Join-Path $projectRoot ".cloudflare-tunnel.pid"
$bundledNodePath = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe"

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
        "RESEARCH_DEMO_UPLOADS_ENABLED=true"
        "REGULATORY_REVIEW_COMPLETE=false"
        "LOCAL_UI_ENABLED=true"
    ) | Set-Content -LiteralPath $environmentFile -Encoding utf8
    Write-Host "Created a private API token in .env. Public uploads remain disabled."
}

if (-not (Select-String -LiteralPath $environmentFile -Pattern '^RESEARCH_DEMO_UPLOADS_ENABLED=' -Quiet)) {
    Add-Content -LiteralPath $environmentFile -Value "RESEARCH_DEMO_UPLOADS_ENABLED=true" -Encoding utf8
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
for ($attempt = 1; $attempt -le 45; $attempt++) {
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

if ((Test-Path -LiteralPath $cloudflaredPath) -and (Test-Path -LiteralPath $wranglerEntryPoint)) {
    $resolvedCloudflaredPath = (Resolve-Path -LiteralPath $cloudflaredPath).Path
    $existingTunnel = Get-CimInstance Win32_Process -Filter "Name = 'cloudflared.exe'" |
        Where-Object { $_.ExecutablePath -eq $resolvedCloudflaredPath }
    if (-not $existingTunnel) {
        $nodeCommand = Get-Command node.exe -ErrorAction SilentlyContinue
        if ($nodeCommand) {
            $nodePath = $nodeCommand.Source
        }
        elseif (Test-Path -LiteralPath $bundledNodePath) {
            $nodePath = $bundledNodePath
        }
        else {
            throw "Node.js is required to retrieve the authenticated tunnel credentials."
        }

        Write-Host "Starting the authenticated HTTPS tunnel..."
        $processInfo = New-Object System.Diagnostics.ProcessStartInfo
        $processInfo.FileName = $nodePath
        $processInfo.Arguments = "`"$wranglerEntryPoint`" tunnel run somnisignal-ml-origin --log-level error"
        $processInfo.WorkingDirectory = Join-Path $projectRoot "worker"
        $processInfo.UseShellExecute = $false
        $processInfo.CreateNoWindow = $true
        $processInfo.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Hidden
        $processInfo.EnvironmentVariables["CLOUDFLARED_PATH"] = $resolvedCloudflaredPath
        $processInfo.EnvironmentVariables["WRANGLER_LOG"] = "error"
        $tunnelProcess = [System.Diagnostics.Process]::Start($processInfo)
        if ($null -eq $tunnelProcess) {
            throw "The HTTPS tunnel failed to start."
        }
        Set-Content -LiteralPath $tunnelPidFile -Value $tunnelProcess.Id -Encoding ascii
        Start-Sleep -Seconds 4
        if ($tunnelProcess.HasExited) {
            throw "The HTTPS tunnel stopped before it connected. Run 'wrangler login' again if Cloudflare authorization expired."
        }
    }
    Write-Host "Authenticated HTTPS tunnel is running." -ForegroundColor Green
}
else {
    Write-Host "Cloudflare tunnel tools are not installed; the app is available locally only." -ForegroundColor Yellow
}

Write-Host "Webapp: http://localhost:8000/"
Write-Host "API:    http://localhost:8000/api"
Write-Host "Docs: http://localhost:8000/docs"
