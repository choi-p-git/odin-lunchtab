param(
    [switch]$SkipInstaller
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

uv sync --locked
uv run --locked pytest -q
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked python scripts/write-version-info.py
uv run --locked pyinstaller --clean --noconfirm packaging/odin_lunchtab.spec

$executable = Join-Path $projectRoot "dist\OdinLunchtab\OdinLunchtab.exe"
$process = Start-Process -FilePath $executable -ArgumentList "--smoke-test" -Wait -PassThru -WindowStyle Hidden
if ($process.ExitCode -ne 0) {
    throw "Frozen application smoke test failed with exit code $($process.ExitCode)."
}

$version = (uv run --locked python -c "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])").Trim()
if (-not $SkipInstaller) {
    $iscc = Get-Command iscc.exe -ErrorAction SilentlyContinue
    if (-not $iscc) {
        $standardPaths = @(
            "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
            "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
        )
        $isccPath = $standardPaths | Where-Object { Test-Path $_ } | Select-Object -First 1
        if (-not $isccPath) {
            throw "Inno Setup Compiler (iscc.exe) was not found. Install Inno Setup or use -SkipInstaller."
        }
    } else {
        $isccPath = $iscc.Source
    }
    & $isccPath "/DAppVersion=$version" "packaging\installer.iss"
    if ($LASTEXITCODE -ne 0) {
        throw "Inno Setup compilation failed with exit code $LASTEXITCODE."
    }
    $installer = Join-Path $projectRoot "release\Odin-Lunchtab-Setup-$version-x64.exe"
    if (-not (Test-Path $installer)) {
        throw "Inno Setup did not produce the expected installer: $installer"
    }
    $checksum = Get-FileHash $installer -Algorithm SHA256
    "$($checksum.Hash)  $($checksum.Path | Split-Path -Leaf)" |
        Set-Content -Encoding ascii "$installer.sha256.txt"
}

Write-Host "Release build complete for version $version."
