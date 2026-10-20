<#
.SYNOPSIS
  Downloads the pinned tool versions into the shared tool cache (no admin rights needed):
  $env:SE_SLIDES_HOME, default %LOCALAPPDATA%\se-slides. All courses use the same copy.
  Re-run after changing a version below.

.EXAMPLE
  ./bootstrap.ps1                 # slides and code: Quarto, JDK, browser for the PDF export
  ./bootstrap.ps1 -Video          # also the lecture videos: uv and ffmpeg (the voices come on first use)
  ./bootstrap.ps1 -Gpu gfx1150    # also Chatterbox on an AMD GPU (ROCm, about 5 GB): Radeon 890M = gfx1150
  ./bootstrap.ps1 -Gpu none       # back to the CPU; removes the GPU environment
#>
param(
  [switch]$Video,
  [ValidatePattern('^(none|gfx\d{3,4}[a-z0-9]*)$')][string]$Gpu
)
$ErrorActionPreference = 'Stop'
if ($Gpu -and $Gpu -ne 'none') { $Video = $true }
$QuartoVersion = '1.10.18'   # update deliberately, then test a full build of each course
$JdkFeature = 25             # latest Temurin 25.x (security updates within the LTS line)
$ChromeChannel = 'Stable'    # chrome-headless-shell for PDF export (Chrome for Testing)
$UvVersion = '0.13.3'        # Python environment of the lecture videos (tools/lecture-video)
$FfmpegBranch = '8.1'        # lecture videos: latest build of this release branch (BtbN)
# Chatterbox on AMD GPUs: AMD's ROCm builds of PyTorch for Windows, one device package per GPU target
$RocmIndex = 'https://stable.repo.amd.com/rocm/whl-next/'
$RocmTorch = '2.12.0+rocm10.1.0'
$RocmTorchaudio = '2.11.0+rocm10.1.0'

$Tools = if ($env:SE_SLIDES_HOME) { $env:SE_SLIDES_HOME } else { Join-Path $env:LOCALAPPDATA 'se-slides' }
New-Item -ItemType Directory -Force $Tools | Out-Null
$tmp = Join-Path ([IO.Path]::GetTempPath()) 'se-slides-bootstrap'
New-Item -ItemType Directory -Force $tmp | Out-Null

function Get-Zip([string]$url, [string]$target) {
  $zip = Join-Path $tmp 'download.zip'
  Write-Host "Downloading $url"
  Invoke-WebRequest -Uri $url -OutFile $zip
  $unpack = Join-Path $tmp 'unpack'
  Remove-Item -Recurse -Force $unpack -ErrorAction SilentlyContinue
  Expand-Archive $zip -DestinationPath $unpack
  Remove-Item -Recurse -Force $target -ErrorAction SilentlyContinue
  # JDK zips contain one top-level folder; Quarto zips do not
  $items = Get-ChildItem $unpack
  if ($items.Count -eq 1 -and $items[0].PSIsContainer) { Move-Item $items[0].FullName $target }
  else { Move-Item $unpack $target }
}

$quarto = Join-Path $Tools 'quarto/bin/quarto.exe'
if (-not (Test-Path $quarto) -or ((& $quarto --version) -ne $QuartoVersion)) {
  Get-Zip "https://github.com/quarto-dev/quarto-cli/releases/download/v$QuartoVersion/quarto-$QuartoVersion-win.zip" (Join-Path $Tools 'quarto')
}
$java = Join-Path $Tools 'jdk/bin/java.exe'
if (-not (Test-Path $java)) {
  Get-Zip "https://api.adoptium.net/v3/binary/latest/$JdkFeature/ga/windows/x64/jdk/hotspot/normal/eclipse" (Join-Path $Tools 'jdk')
}
$shell = Join-Path $Tools 'chrome-headless-shell/chrome-headless-shell.exe'
if (-not (Test-Path $shell)) {
  $versions = Invoke-RestMethod 'https://googlechromelabs.github.io/chrome-for-testing/last-known-good-versions-with-downloads.json'
  $url = ($versions.channels.$ChromeChannel.downloads.'chrome-headless-shell' | Where-Object platform -eq 'win64').url
  Get-Zip $url (Join-Path $Tools 'chrome-headless-shell')
}
# Lecture videos only (tools/lecture-video): uv makes their Python environment on first use
$uv = Join-Path $Tools 'uv/uv.exe'
if ($Video) {
  if (-not (Test-Path $uv) -or ((& $uv --version) -notmatch [regex]::Escape($UvVersion))) {
    Get-Zip "https://github.com/astral-sh/uv/releases/download/$UvVersion/uv-x86_64-pc-windows-msvc.zip" (Join-Path $Tools 'uv')
  }
  $ffmpeg = Join-Path $Tools 'ffmpeg/bin/ffmpeg.exe'
  if (-not (Test-Path $ffmpeg)) {
    Get-Zip "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-n$FfmpegBranch-latest-win64-gpl-$FfmpegBranch.zip" (Join-Path $Tools 'ffmpeg')
  }
}

# The GPU environment of the lecture videos: its own venv next to the CPU one (lecture-video.ps1 uses
# it while gpu.txt names the target), so switching never reinstalls gigabytes
$videoHome = Join-Path $Tools 'lecture-video'
$gpuFile = Join-Path $videoHome 'gpu.txt'
if ($Gpu -eq 'none') {
  Remove-Item -Force $gpuFile -ErrorAction SilentlyContinue
  Get-ChildItem $videoHome -Directory -Filter 'venv-gfx*' -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force
  Write-Host 'Lecture videos: Chatterbox runs on the CPU'
} elseif ($Gpu) {
  $venv = Join-Path $videoHome "venv-$Gpu"
  $project = Join-Path $PSScriptRoot 'lecture-video'
  New-Item -ItemType Directory -Force $videoHome | Out-Null
  if (-not (Test-Path (Join-Path $venv 'Scripts/python.exe'))) { & $uv venv --quiet --python 3.12 $venv }
  # chatterbox-tts pins torch 2.6.0 (CPU): overridden by the ROCm build, with the extra that brings
  # the GPU's device packages (an override without it drops them)
  $override = Join-Path $tmp 'rocm-override.txt'
  Set-Content $override "torch[device-$Gpu]==$RocmTorch`ntorchaudio==$RocmTorchaudio"
  $env:VIRTUAL_ENV = $venv
  & $uv pip install --index $RocmIndex --index-strategy unsafe-best-match --override $override `
    -r (Join-Path $project 'pyproject.toml') --extra chatterbox --extra piper `
    "torch[device-$Gpu]==$RocmTorch" "torchaudio==$RocmTorchaudio"
  $code = $LASTEXITCODE
  Remove-Item Env:VIRTUAL_ENV
  if ($code) { throw "Installing the ROCm environment for $Gpu failed (is $Gpu a target of $RocmIndex ?)" }
  & (Join-Path $venv 'Scripts/python.exe') -c "import torch, sys; ok = torch.cuda.is_available(); print('GPU:', torch.cuda.get_device_name(0) if ok else 'none found'); sys.exit(0 if ok else 1)"
  if ($LASTEXITCODE) { throw "PyTorch sees no GPU in $venv (wrong target or driver?). ./bootstrap.ps1 -Gpu none goes back to the CPU." }
  Set-Content $gpuFile $Gpu
  Write-Host "Lecture videos: Chatterbox runs on the GPU ($Gpu)"
}
Write-Host "Tools in $Tools"
& $quarto --version
& $java -version
