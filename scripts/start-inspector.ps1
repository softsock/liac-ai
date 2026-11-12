param([string]$Python)
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
try {
    if (-not $Python) {
        $Python = Join-Path $repoRoot '.venv/Scripts/python.exe'
        if (-not (Test-Path -LiteralPath $Python)) {
            $commonGit = (& git -C $repoRoot rev-parse --path-format=absolute --git-common-dir).Trim()
            $Python = Join-Path (Split-Path -Parent $commonGit) '.venv/Scripts/python.exe'
        }
    }
    if (-not (Test-Path -LiteralPath $Python)) {
        throw 'Python virtual environment not found. Run this script with -Python PATH, or create .venv and install .[desktop,nemotron].'
    }
    $env:PYTHONPATH = (Join-Path $repoRoot 'src') + [IO.Path]::PathSeparator + $env:PYTHONPATH
    & $Python -c 'import PySide6.QtWidgets, vtuber.desktop' 2>$null
    if ($LASTEXITCODE -ne 0) { throw 'Install desktop dependencies: python -m pip install -e ".[desktop,nemotron]"' }
    $launchData = Join-Path $repoRoot '.data/desktop'
    New-Item -ItemType Directory -Force $launchData | Out-Null
    $pythonWindowed = Join-Path (Split-Path -Parent $Python) 'pythonw.exe'
    if (-not (Test-Path -LiteralPath $pythonWindowed)) { $pythonWindowed = $Python }
    $arguments = @('-m', 'vtuber.desktop', '--root', ('"' + $repoRoot + '"'))
    Start-Process -FilePath $pythonWindowed -ArgumentList $arguments -WorkingDirectory $repoRoot `
        -WindowStyle Normal -RedirectStandardOutput (Join-Path $launchData 'stdout.log') `
        -RedirectStandardError (Join-Path $launchData 'stderr.log') | Out-Null
} catch {
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.MessageBox]::Show($_.Exception.Message, 'LIAC inspector setup') | Out-Null
    exit 1
}
