param(
    [Parameter(Mandatory=$true)]
    [string]$RegistrationToken,

    [string]$RunnerRoot = "C:\actions-runner",
    [string]$RepositoryUrl = "https://github.com/reprewindai-dev/lockerphycer",
    [string]$RunnerName = "$env:COMPUTERNAME-VEKLOM-PREDATOR",
    [switch]$InstallService
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Assert-Path([string]$Path, [string]$Description) {
    if (-not (Test-Path -LiteralPath $Path)) {
        throw "$Description not found: $Path"
    }
}

Assert-Path $RunnerRoot "GitHub Actions runner directory"
$configCmd = Join-Path $RunnerRoot "config.cmd"
$runCmd = Join-Path $RunnerRoot "run.cmd"
Assert-Path $configCmd "GitHub Actions config.cmd"
Assert-Path $runCmd "GitHub Actions run.cmd"

Write-Host "[runner-bootstrap] target repository: $RepositoryUrl"
Write-Host "[runner-bootstrap] runner name: $RunnerName"
Write-Host "[runner-bootstrap] labels: veklom-predator,windows,x64"

# A prior runner registration may have been deleted by GitHub after being offline.
# We deliberately remove only local registration metadata; secrets and work files
# are not printed or copied. The new repository-scoped registration token is
# passed directly to config.cmd and is never persisted by this script.
$staleFiles = @(
    ".runner",
    ".credentials",
    ".credentials_rsaparams",
    ".service"
)
foreach ($name in $staleFiles) {
    $path = Join-Path $RunnerRoot $name
    if (Test-Path -LiteralPath $path) {
        Write-Host "[runner-bootstrap] removing stale local registration metadata: $name"
        Remove-Item -LiteralPath $path -Force
    }
}

Push-Location $RunnerRoot
try {
    & $configCmd `
        --unattended `
        --replace `
        --url $RepositoryUrl `
        --token $RegistrationToken `
        --name $RunnerName `
        --labels "veklom-predator,windows,x64" `
        --work "_work"

    if ($LASTEXITCODE -ne 0) {
        throw "GitHub runner configuration failed with exit code $LASTEXITCODE"
    }

    if ($InstallService) {
        Write-Host "[runner-bootstrap] installing Windows service"
        & $configCmd --unattended --replace --url $RepositoryUrl --token $RegistrationToken --name $RunnerName --labels "veklom-predator,windows,x64" --work "_work" --runasservice
        if ($LASTEXITCODE -ne 0) {
            throw "Runner service configuration failed with exit code $LASTEXITCODE"
        }
    }

    Write-Host "[runner-bootstrap] registration complete"
    Write-Host "[runner-bootstrap] starting foreground listener"
    & $runCmd
}
finally {
    Pop-Location
}
