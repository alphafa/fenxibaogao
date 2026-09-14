$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

Write-Host "[1/4] Checking PyInstaller..."
python -m PyInstaller --version *> $null
if ($LASTEXITCODE -ne 0) {
    python -m pip install --upgrade pyinstaller
}

Write-Host "[2/4] Building the portable backend..."
Remove-Item -Recurse -Force "$Root\build", "$Root\dist" -ErrorAction SilentlyContinue
python -m PyInstaller --clean --noconfirm "$Root\server\server.spec"

$Stage = Join-Path $Root "windows-release"
$Zip = Join-Path $Root "三笙AI-商品开品闭环-Windows-最终安装包.zip"
Write-Host "[3/4] Creating a clean release directory..."
Remove-Item -Recurse -Force $Stage -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Path $Stage | Out-Null
Copy-Item -Recurse "$Root\dist\SansongAI\*" $Stage
Copy-Item "$Root\start-windows.bat", "$Root\stop-windows.bat", "$Root\Windows使用说明.txt" $Stage
Copy-Item -Recurse "$Root\extension" (Join-Path $Stage "extension")
Copy-Item -Recurse "$Root\collector-extension-standalone" (Join-Path $Stage "collector-extension-standalone")

Write-Host "[4/4] Packaging $Zip..."
Remove-Item -Force $Zip -ErrorAction SilentlyContinue
Compress-Archive -Path "$Stage\*" -DestinationPath $Zip -CompressionLevel Optimal
Write-Host "Windows package created: $Zip"
