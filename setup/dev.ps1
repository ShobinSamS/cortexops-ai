param([ValidateSet('start','stop','status')][string]$Action = 'start')
$ErrorActionPreference = 'Stop'
$projectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$statePath = Join-Path $projectRoot '.data\dev-services.json'
$pythonPath = Join-Path $projectRoot 'backend\.venv\Scripts\python.exe'

function Stop-OwnedTree([int]$ProcessId) {
    Get-CimInstance Win32_Process -Filter "ParentProcessId=$ProcessId" -ErrorAction SilentlyContinue | ForEach-Object { Stop-OwnedTree $_.ProcessId }
    Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
}

if ($Action -eq 'stop') {
    if (Test-Path -LiteralPath $statePath) {
        foreach ($entry in (Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json)) {
            $process = Get-Process -Id $entry.ProcessId -ErrorAction SilentlyContinue
            if ($process -and $process.StartTime.ToUniversalTime().Ticks -eq $entry.StartTicks) { Stop-OwnedTree $entry.ProcessId }
        }
        Remove-Item -LiteralPath $statePath
    }
    Write-Output 'Owned development processes stopped; database volumes preserved.'
    exit
}
if ($Action -eq 'status') {
    if (Test-Path -LiteralPath $statePath) {
        Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json | Select-Object Name,ProcessId,Port
    } else { Write-Output 'No launcher-owned processes are recorded.' }
    exit
}
if (Test-Path -LiteralPath $statePath) { throw 'Launcher state already exists. Use -Action status or -Action stop first.' }
$previousLocation = Get-Location
Set-Location -LiteralPath $projectRoot
try {
    & $pythonPath 'setup\configure-app.py'
    docker compose -f compose.prerequisites.yml up -d --wait
    if ($LASTEXITCODE -ne 0) { throw 'Docker services failed. Open Docker Desktop and retry.' }
    Push-Location backend
    try {
        & $pythonPath -m alembic upgrade head
        if ($LASTEXITCODE -ne 0) { throw 'Database migration failed.' }
        & $pythonPath -m app.cli setup-analytics
        if ($LASTEXITCODE -ne 0) { throw 'Analytics role setup failed.' }
        & $pythonPath -m app.cli sync-endpoints
    } finally { Pop-Location }
    $definitions = @(
        @{Name='api';Port=8000;Exe=$pythonPath;Args=@('-m','app');Directory='backend'},
        @{Name='worker';Port=0;Exe=$pythonPath;Args=@('-m','celery','-A','app.workers.celery_app:celery','worker','--pool=solo','--concurrency=1','--loglevel=info','--hostname=documents@%h');Directory='backend'},
        @{Name='investigation-worker';Port=0;Exe=$pythonPath;Args=@('-m','celery','-A','app.workers.celery_app:celery','worker','--pool=solo','--concurrency=1','--loglevel=info','-Q','cortexops.investigations','--hostname=investigations@%h');Directory='backend'},
        @{Name='frontend';Port=5173;Exe=(Get-Command node).Source;Args=@('.\node_modules\vite\bin\vite.js');Directory='frontend'}
    )
    $kinds = @('github','analytics','knowledge','monitoring','incidents')
    for ($i=0;$i -lt $kinds.Count;$i++) { $kind=$kinds[$i]; $definitions += @{Name="mcp-$kind";Port=(8101+$i);Exe=$pythonPath;Args=@('-m','app.mcp.server','--kind',$kind);Directory='backend'} }
    foreach ($definition in $definitions) {
        if ($definition.Port -and (Get-NetTCPConnection -LocalPort $definition.Port -State Listen -ErrorAction SilentlyContinue)) { throw "Port $($definition.Port) is already in use. Stop the existing service before starting this launcher." }
    }
    $entries = @()
    New-Item -ItemType Directory -Path (Join-Path $projectRoot '.data') -Force | Out-Null
    foreach ($definition in $definitions) {
        $process = Start-Process -FilePath $definition.Exe -ArgumentList $definition.Args -WorkingDirectory (Join-Path $projectRoot $definition.Directory) -WindowStyle Hidden -RedirectStandardOutput (Join-Path $PSScriptRoot "dev-$($definition.Name).log") -RedirectStandardError (Join-Path $PSScriptRoot "dev-$($definition.Name)-errors.log") -PassThru
        $entries += @{Name=$definition.Name;ProcessId=$process.Id;StartTicks=$process.StartTime.ToUniversalTime().Ticks;Port=$definition.Port}
        $entries | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $statePath -Encoding utf8
    }
    Write-Output 'Development processes started. Open http://127.0.0.1:5173 after API readiness; logs are in setup/dev-*.log.'
} finally { Set-Location -LiteralPath $previousLocation.Path }
