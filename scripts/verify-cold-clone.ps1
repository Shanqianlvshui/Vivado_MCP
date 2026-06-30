param(
    [string]$RepoUrl = "https://github.com/Shanqianlvshui/Vivado_CLI.git",
    [string]$WorkRoot = "",
    [switch]$Full
)

function Assert-NativeSuccess {
    param([string]$StepName)

    if ($LASTEXITCODE -ne 0) {
        throw "$StepName failed with exit code $LASTEXITCODE"
    }
}

$ErrorActionPreference = "Stop"

if (-not $WorkRoot) {
    $WorkRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("vivado-cli-cold-clone-" + [guid]::NewGuid().ToString("N"))
}

$workRootFull = [System.IO.Path]::GetFullPath($WorkRoot)
if (Test-Path -LiteralPath $workRootFull) {
    $resolved = (Resolve-Path -LiteralPath $workRootFull).Path
    $tempFull = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
    if (-not $resolved.StartsWith($tempFull, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to remove existing WorkRoot outside the temp directory: $resolved"
    }
    Remove-Item -LiteralPath $resolved -Recurse -Force
}

New-Item -ItemType Directory -Path $workRootFull | Out-Null
$repoDir = Join-Path $workRootFull "Vivado_CLI"

Write-Host "Cloning $RepoUrl"
git clone --depth 1 $RepoUrl $repoDir
Assert-NativeSuccess "git clone"

Push-Location $repoDir
try {
    Write-Host "Creating virtual environment"
    python -m venv .venv
    Assert-NativeSuccess "python -m venv"
    $python = Join-Path $repoDir ".venv\Scripts\python.exe"
    $vivadoCli = Join-Path $repoDir ".venv\Scripts\vivado-cli.exe"

    & $python -m pip install --upgrade pip
    Assert-NativeSuccess "python -m pip install --upgrade pip"
    & $python -m pip install -e ".[dev]"
    Assert-NativeSuccess "python -m pip install -e .[dev]"

    Write-Host "Running CLI smoke checks"
    $env:PYTHONIOENCODING = "utf-8"

    & $vivadoCli --help | Out-Null
    Assert-NativeSuccess "vivado-cli --help"
    & $vivadoCli tools list | Out-Null
    Assert-NativeSuccess "vivado-cli tools list"
    & $vivadoCli tcl help create_clock | Out-Null
    Assert-NativeSuccess "vivado-cli tcl help create_clock"

    Write-Host "Compiling sources and tests"
    & $python -m compileall -q src tests
    Assert-NativeSuccess "python -m compileall"

    if ($Full) {
        Write-Host "Running full unit suite"
        & $python -m pytest tests/unit -q
        Assert-NativeSuccess "python -m pytest tests/unit -q"
    }
    else {
        Write-Host "Running cold-clone smoke tests"
        & $python -m pytest tests/unit/test_help_skills.py tests/unit/test_tcl_assist.py tests/unit/test_state_diff.py -q
        Assert-NativeSuccess "python -m pytest smoke"
        & $python -m pytest tests/unit/test_cli.py -k "tools_list_and_describe or fileset or constraint" -q
        Assert-NativeSuccess "python -m pytest cli smoke"
    }
}
finally {
    Pop-Location
}

Write-Host "Cold-clone verification passed in $repoDir"
