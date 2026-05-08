param(
    [switch]$BootstrapOnly
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvDir = Join-Path $projectRoot ".venv"
$pythonExe = Join-Path $venvDir "Scripts\python.exe"
$mainFile = Join-Path $projectRoot "main.py"
$requirementsFile = Join-Path $projectRoot "requirements.txt"
$requirementsStamp = Join-Path $venvDir ".requirements.sha256"
$venvConfig = Join-Path $venvDir "pyvenv.cfg"

function Test-VenvHealthy {
    param(
        [string]$VenvPython,
        [string]$ConfigPath
    )

    if (-not (Test-Path $VenvPython) -or -not (Test-Path $ConfigPath)) {
        return $false
    }

    $configText = Get-Content $ConfigPath -Raw
    $exeMatch = [regex]::Match($configText, "(?m)^executable\s*=\s*(.+)\s*$")
    if ($exeMatch.Success) {
        $baseExe = $exeMatch.Groups[1].Value.Trim()
        if (-not (Test-Path $baseExe)) {
            return $false
        }
    } else {
        $homeMatch = [regex]::Match($configText, "(?m)^home\s*=\s*(.+)\s*$")
        if ($homeMatch.Success) {
            $homeDir = $homeMatch.Groups[1].Value.Trim()
            if (-not (Test-Path (Join-Path $homeDir "python.exe"))) {
                return $false
            }
        }
    }

    try {
        & $VenvPython -c "import sys; print(sys.version)" *> $null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    }
}

function Find-SystemPython {
    $candidates = @(
        @{ command = "py"; args = @("-3.13") },
        @{ command = "py"; args = @("-3") },
        @{ command = "py"; args = @() },
        @{ command = "python"; args = @() }
    )

    foreach ($candidate in $candidates) {
        $commandInfo = Get-Command $candidate.command -ErrorAction SilentlyContinue
        if (-not $commandInfo) {
            continue
        }
        try {
            & $candidate.command @($candidate.args + @("-c", "import sys; print(sys.executable)")) *> $null
            if ($LASTEXITCODE -eq 0) {
                return $candidate
            }
        } catch {
            continue
        }
    }

    throw "Python 3 was not found. Install Python 3.13.x for Windows and make sure 'py' or 'python' is available."
}

function Ensure-LocalVenv {
    if (Test-VenvHealthy -VenvPython $pythonExe -ConfigPath $venvConfig) {
        return
    }

    if (Test-Path $venvDir) {
        Write-Host "Detected a broken or foreign virtual environment. Recreating local .venv..."
        Remove-Item -LiteralPath $venvDir -Recurse -Force
    }

    $systemPython = Find-SystemPython
    Write-Host "Creating local virtual environment via $($systemPython.command) $($systemPython.args -join ' ')..."
    & $systemPython.command @($systemPython.args + @("-m", "venv", $venvDir))
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $pythonExe)) {
        throw "Failed to create virtual environment in $venvDir"
    }
}

function Install-ProjectRequirements {
    if (-not (Test-Path $requirementsFile)) {
        throw "requirements.txt was not found: $requirementsFile"
    }

    $requirementsHash = (Get-FileHash $requirementsFile -Algorithm SHA256).Hash
    if ((Test-Path $requirementsStamp) -and ((Get-Content $requirementsStamp -Raw).Trim() -eq $requirementsHash)) {
        Write-Host "Dependencies are up to date."
        return
    }

    Write-Host "Upgrading pip..."
    & $pythonExe -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to upgrade pip in the local environment."
    }

    Write-Host "Installing project dependencies..."
    & $pythonExe -m pip install -r $requirementsFile
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to install dependencies from requirements.txt."
    }

    [System.IO.File]::WriteAllText($requirementsStamp, $requirementsHash, [System.Text.Encoding]::ASCII)
}

if (-not (Test-Path $mainFile)) {
    throw "Main file was not found: $mainFile"
}

Ensure-LocalVenv
Install-ProjectRequirements

if ($BootstrapOnly) {
    Write-Host "Environment is ready. You can run python -m app.main, main.py, or this script."
    exit 0
}

& $pythonExe $mainFile
