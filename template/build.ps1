# Builds this course with the shared se-slides tools.
#   ./build.ps1 05 -Preview | ./build.ps1 05 -Pdf | ./build.ps1 -Pdf -Moodle | -Lenient | -Strict | -ShowLayout
# Details: _extensions/se-slides/README.md
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$core = Join-Path $PSScriptRoot '_extensions/se-slides/tools/build.ps1'
if (-not (Test-Path $core)) { throw 'Shared tools missing. Run:  git submodule update --init' }
& $core @args
exit $LASTEXITCODE
