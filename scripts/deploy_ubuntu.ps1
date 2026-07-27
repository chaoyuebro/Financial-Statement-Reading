param(
    [string]$HostName = "192.168.31.199",
    [string]$RemoteDir = "/srv/financial-reader"
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$archiveName = "financial-reader-$([guid]::NewGuid().ToString('N')).tar.gz"
$archivePath = Join-Path $env:TEMP $archiveName
$remoteArchive = "/tmp/$archiveName"

try {
    Write-Host "1/4 打包代码..."
    & tar -czf $archivePath `
        --exclude=node_modules `
        --exclude=.next `
        --exclude='.next*' `
        --exclude=.git `
        --exclude=.pytest_cache `
        --exclude=__pycache__ `
        --exclude=tmp `
        --exclude=apps/worker/.pdf_cache `
        --exclude=.env `
        --exclude='*.tsbuildinfo' `
        --exclude=apps/web/public/nutrient-viewer-lib `
        --exclude=apps/web/public/nutrient-viewer.js `
        -C $projectRoot .
    if ($LASTEXITCODE -ne 0) { throw "代码打包失败" }

    Write-Host "2/4 上传到 $HostName..."
    & scp -q $archivePath "root@${HostName}:$remoteArchive"
    if ($LASTEXITCODE -ne 0) { throw "上传失败" }

    Write-Host "3/4 更新服务器代码并构建..."
    & ssh "root@$HostName" "mkdir -p '$RemoteDir' && tar -xzf '$remoteArchive' -C '$RemoteDir' && rm -f '$remoteArchive' && bash '$RemoteDir/scripts/remote_deploy.sh' '$RemoteDir'"
    if ($LASTEXITCODE -ne 0) { throw "服务器构建或启动失败" }

    Write-Host "4/4 完成"
    Write-Host "访问地址：http://${HostName}:3001"
}
finally {
    if (Test-Path -LiteralPath $archivePath) {
        Remove-Item -LiteralPath $archivePath -Force
    }
}
