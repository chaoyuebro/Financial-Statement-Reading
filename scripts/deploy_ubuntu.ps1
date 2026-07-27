param(
    [string]$HostName = "192.168.31.199",
    [string]$RemoteDir = "/srv/financial-reader"
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$currentCommit = (& git -C $projectRoot rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or -not $currentCommit) {
    throw "Cannot read current Git commit."
}

$dirty = & git -C $projectRoot status --porcelain
if ($dirty) {
    throw "Working tree is dirty. Commit changes before deployment."
}

$remoteCommit = (& ssh "root@$HostName" "cat '$RemoteDir/.deploy_commit' 2>/dev/null || true").Trim()
$incremental = $false
$changed = @()
$deleted = @()

if ($remoteCommit) {
    & git -C $projectRoot cat-file -e "$remoteCommit^{commit}" 2>$null
    $remoteCommitExists = $LASTEXITCODE -eq 0
}
if ($remoteCommit -and $remoteCommitExists) {
    & git -C $projectRoot merge-base --is-ancestor $remoteCommit $currentCommit
    if ($LASTEXITCODE -eq 0) {
        $incremental = $true
        $changed = @(& git -C $projectRoot -c core.quotepath=false diff --name-only --diff-filter=ACMRT $remoteCommit $currentCommit)
        $deleted = @(& git -C $projectRoot -c core.quotepath=false diff --name-only --diff-filter=D $remoteCommit $currentCommit)
    }
}

if (-not $incremental) {
    $changed = @(& git -C $projectRoot -c core.quotepath=false ls-tree -r --name-only HEAD)
    $deleted = @()
}

$changed = @($changed | Where-Object { $_ })
$deleted = @($deleted | Where-Object { $_ })
$archiveName = "financial-reader-$([guid]::NewGuid().ToString('N')).tar.gz"
$archivePath = Join-Path $env:TEMP $archiveName
$remoteArchive = "/tmp/$archiveName"
$remoteRunner = "/tmp/financial-reader-remote-deploy.sh"
$payload = @{
    full = -not $incremental
    changed = $changed
    deleted = $deleted
} | ConvertTo-Json -Compress
$payloadBase64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($payload))

try {
    if ($changed.Count -gt 0) {
        Write-Host "1/4 Packaging $($changed.Count) changed files..."
        & git -C $projectRoot archive --format=tar.gz --output=$archivePath HEAD -- @changed
        if ($LASTEXITCODE -ne 0) { throw "Cannot create deployment archive." }

        Write-Host "2/4 Uploading incremental archive to $HostName..."
        & scp -q $archivePath "root@${HostName}:$remoteArchive"
        if ($LASTEXITCODE -ne 0) { throw "Upload failed." }
    } else {
        Write-Host "1/4 No added or modified files."
        $remoteArchive = "-"
        Write-Host "2/4 Skipping upload."
    }

    Write-Host "3/4 Deploying affected services..."
    & scp -q (Join-Path $projectRoot "scripts/remote_deploy.sh") "root@${HostName}:$remoteRunner"
    if ($LASTEXITCODE -ne 0) { throw "Cannot upload remote deployment runner." }
    & ssh "root@$HostName" "mkdir -p '$RemoteDir' && bash '$remoteRunner' '$RemoteDir' '$currentCommit' '$payloadBase64' '$remoteArchive'; code=`$?; rm -f '$remoteRunner'; exit `$code"
    if ($LASTEXITCODE -ne 0) { throw "Incremental deployment failed." }

    Write-Host "4/4 Done: $remoteCommit -> $currentCommit"
    Write-Host "URL: http://${HostName}:3001"
}
finally {
    if (Test-Path -LiteralPath $archivePath) {
        Remove-Item -LiteralPath $archivePath -Force
    }
}
