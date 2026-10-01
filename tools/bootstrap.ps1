<#
.SYNOPSIS
  Downloads the pinned tool versions into the shared tool cache (no admin rights needed):
  $env:SE_SLIDES_HOME, default %LOCALAPPDATA%\se-slides. All courses use the same copy.
  Re-run after changing a version below.
#>
$ErrorActionPreference = 'Stop'
$QuartoVersion = '1.10.18'   # update deliberately, then test a full build of each course
$JdkFeature = 25             # latest Temurin 25.x (security updates within the LTS line)

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
Write-Host "Tools in $Tools"
& $quarto --version
& $java -version
