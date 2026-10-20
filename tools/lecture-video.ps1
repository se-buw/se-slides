<#
.SYNOPSIS
  Narrated lecture videos from the slides (README: "Generated lecture videos").
  Called by the course's lecture-video.ps1 from the course folder.

.EXAMPLE
  ./lecture-video.ps1 05                  # render lecture 05, build _video/05-loops.<lang>.mp4 for all narrations
  ./lecture-video.ps1 05 -Lang de         # only the German video
  ./lecture-video.ps1 05 check            # narration against the slides (also part of every build)
  ./lecture-video.ps1 05 check -Stale     # only the changed slides, with their diff and narration
  ./lecture-video.ps1 05 stamp -Lang en   # after reviewing the English narration
  ./lecture-video.ps1 05 fix-ids          # follow renamed slides
  ./lecture-video.ps1 05 estimate         # runtime from the word count, before any audio exists
  ./lecture-video.ps1 sample -Lang de     # the configured voice on a code-heavy test paragraph: _video/samples/
  ./lecture-video.ps1 05 -Force           # take the pictures again and ignore check errors (drafts)
#>
param(
  [Parameter(Position = 0, ValueFromRemainingArguments = $true)][string[]]$Arguments = @(),
  [string[]]$Lang = @(),
  [string]$Text,
  [switch]$Stale,
  [switch]$Quiet,
  [switch]$Force,
  [switch]$NoRender
)
$ErrorActionPreference = 'Stop'
if (-not (Test-Path '_quarto.yml')) { throw "Run this from a course folder (no _quarto.yml in $(Get-Location))." }
$ToolCache = if ($env:SE_SLIDES_HOME) { $env:SE_SLIDES_HOME } else { Join-Path $env:LOCALAPPDATA 'se-slides' }
$Project = Join-Path $PSScriptRoot 'lecture-video'
$Commands = 'check', 'stamp', 'fix-ids', 'estimate', 'frames', 'build', 'sample'

$command = 'build'
$lectures = @()
foreach ($a in $Arguments) { if ($Commands -contains $a) { $command = $a } else { $lectures += $a } }

$uv = Join-Path $ToolCache 'uv/uv.exe'
if (-not (Test-Path $uv)) { throw "uv not found. Run $PSScriptRoot/bootstrap.ps1 -Video once." }
# One environment for all courses, outside the repositories
$env:UV_PROJECT_ENVIRONMENT = Join-Path $ToolCache 'lecture-video/venv'
$env:PYTHONUTF8 = '1'

# The packages of the configured local engines (cloud engines need none)
$local = 'piper', 'chatterbox'
$used = @('chatterbox')  # the default voices (lecture_video/course.py)
if (Test-Path 'lecture-video.yml') {
  $used = @([regex]::Matches((Get-Content 'lecture-video.yml' -Raw), '(?m)^[^#\n]*engine:\s*(\w+)') | ForEach-Object { $_.Groups[1].Value })
}
$extras = @($local | Where-Object { $used -contains $_ } | ForEach-Object { '--extra', $_ })

# Pictures and the check need the deck's current HTML
if (-not $NoRender -and @('build', 'frames') -contains $command -and $lectures.Count) {
  & (Join-Path (Get-Location) 'build.ps1') @lectures
  if ($LASTEXITCODE) { exit $LASTEXITCODE }
}

$pyArgs = @($command) + $lectures
if ($Lang.Count) { $pyArgs += '--lang', ($Lang -join ',') }
if ($Text) { $pyArgs += '--text', $Text }
if ($Stale) { $pyArgs += '--stale' }
if ($Quiet) { $pyArgs += '--quiet' }
if ($Force) { $pyArgs += '--force' }
# bootstrap.ps1 -Gpu <target>: its ROCm environment (made there, not synced here)
$gpuFile = Join-Path $ToolCache 'lecture-video/gpu.txt'
if (Test-Path $gpuFile) {
  $gpu = (Get-Content $gpuFile -Raw).Trim()
  $python = Join-Path $ToolCache "lecture-video/venv-$gpu/Scripts/python.exe"
  if (-not (Test-Path $python)) { throw "GPU environment $gpu missing. Run $PSScriptRoot/bootstrap.ps1 -Gpu $gpu (or -Gpu none)." }
  & $python (Join-Path $Project 'lv.py') @pyArgs
} else {
  & $uv run --quiet --project $Project @extras python (Join-Path $Project 'lv.py') @pyArgs
}
exit $LASTEXITCODE
