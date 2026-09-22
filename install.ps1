# Windows: install/update the addon. Prefer double-clicking Install.cmd or Start.cmd
# (Start.cmd syncs the addon automatically every launch).
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if (Test-Path ".\GamepadSpeak.exe") {
  & ".\GamepadSpeak.exe" --install-addon @args
  exit $LASTEXITCODE
}
& "$PSScriptRoot\run-helper.ps1" --install-addon @args
exit $LASTEXITCODE
