param([string]$Python = 'python')

$ErrorActionPreference = 'Stop'
Push-Location -LiteralPath $PSScriptRoot
try {
    & $Python -m PyInstaller --noconfirm --distpath dist --workpath build B2962B_Console.spec
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed with exit code $LASTEXITCODE"
    }
    $config = Join-Path $PSScriptRoot 'dist\b2962b_scan.toml'
    if (-not (Test-Path -LiteralPath $config)) {
        Copy-Item -LiteralPath 'b2962b_scan.example.toml' -Destination $config
    }
}
finally {
    Pop-Location
}
