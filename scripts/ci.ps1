# Local CI sequence mirroring .github/workflows/tests.yml (Windows).
# Requires `uv` on PATH (and Node/npm for the web build).
#
# Usage:
#   .\scripts\ci.ps1                 # run everything
#   .\scripts\ci.ps1 -Only pytest    # run a subset (ruff-format|ruff-check|pytest|web)
#   .\scripts\ci.ps1 -Skip web
#   .\scripts\ci.ps1 -DryRun         # print commands without running

[CmdletBinding()]
param(
  [string]$Only,
  [string[]]$Skip = @(),
  [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
Set-Location (Join-Path $PSScriptRoot '..')

function Want([string]$step) {
  if ($Only -and $Only -ne $step) { return $false }
  if ($Skip -contains $step) { return $false }
  return $true
}

function Invoke-Step([string]$cmd) {
  Write-Host "+ $cmd"
  if (-not $DryRun) { Invoke-Expression $cmd }
}

if (Want 'ruff-format') { Invoke-Step 'uv run ruff format --check api mcp-server tests' }
if (Want 'ruff-check')  { Invoke-Step 'uv run ruff check api mcp-server tests' }
if (Want 'pytest')      { Invoke-Step 'uv run pytest -v --tb=short' }
if (Want 'web') {
  if ($DryRun) {
    Write-Host '+ (cd web; npm ci; npm run build)'
  } else {
    Push-Location web
    try { npm ci; npm run build } finally { Pop-Location }
  }
}

Write-Host 'CI OK'
