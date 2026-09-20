# Windows: run the helper. Extra flags pass through, e.g. .\run-helper.ps1 --language bg
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "helper")
if (Get-Command uv -ErrorAction SilentlyContinue) {
  uv run --quiet python gamepadspeak_helper.py @args
  exit $LASTEXITCODE
}
if (-not (Test-Path ".venv\Scripts\python.exe")) {
  py -3.13 -m venv .venv 2>$null; if (-not $?) { py -3.12 -m venv .venv 2>$null }; if (-not $?) { py -3 -m venv .venv }
  .venv\Scripts\python.exe -m pip install --quiet --upgrade pip
  .venv\Scripts\python.exe -m pip install --quiet .
}
.venv\Scripts\python.exe gamepadspeak_helper.py @args
