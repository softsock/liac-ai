param([string]$Python = 'python')
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot

# Build dependencies: pip install pyinstaller '.[desktop,nemotron]' -r requirements-luna.txt
$previousPath = $env:PATH
try {
    # Qt uses Windows ICU; unrelated vendor ICU DLLs on PATH have incompatible exports.
    $env:PATH = "$env:SystemRoot/System32;$previousPath"
    & $Python -m PyInstaller --clean --noconfirm --onefile --windowed --noupx `
        --name LIAC-Inspector --distpath $repoRoot `
        --workpath (Join-Path $repoRoot 'build/inspector/work') `
        --specpath (Join-Path $repoRoot 'build/inspector') `
        --paths (Join-Path $repoRoot 'src') `
        --add-data "${repoRoot}/src/vtuber/minds/character.md:vtuber/minds" `
        --add-data "${repoRoot}/src/vtuber/minds/deep.md:vtuber/minds" `
        --collect-submodules omp_rpc --hidden-import tokenizers `
        (Join-Path $repoRoot 'src/vtuber/desktop/__main__.py')
    if ($LASTEXITCODE -ne 0) { throw "Inspector build failed with exit code $LASTEXITCODE" }
} finally {
    $env:PATH = $previousPath
}
Get-Item -LiteralPath (Join-Path $repoRoot 'LIAC-Inspector.exe')
