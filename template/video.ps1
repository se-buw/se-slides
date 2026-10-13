# Lecture recordings with the shared se-slides tools: YouTube chapters and video links on the slides.
#   ./video.ps1 05 | ./video.ps1 05 -Id <YouTube link> | -Recording <file> | -Start <time> -End <time>
# Details: _extensions/se-slides/README.md
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$core = Join-Path $PSScriptRoot '_extensions/se-slides/tools/video.ps1'
if (-not (Test-Path $core)) { throw 'Shared tools missing. Run:  git submodule update --init' }
& $core @args
