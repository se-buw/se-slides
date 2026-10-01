<#
.SYNOPSIS
  Creates a new course from the template: folder, Git repository, se-slides as submodule.

.EXAMPLE
  ./new-course.ps1 -Path C:/teaching/se1 -Title "Software Engineering" -Repo se1
  ./new-course.ps1 -Path C:/teaching/se1 -Title "Software Engineering" -Repo se1 -SharedUrl C:/teaching/se-slides
#>
param(
  [Parameter(Mandatory = $true)][string]$Path,
  [Parameter(Mandatory = $true)][string]$Title,
  # name of the course repository on GitHub (used in README and repo-url)
  [Parameter(Mandatory = $true)][string]$Repo,
  # where the course gets se-slides from; a local path works for testing
  [string]$SharedUrl = 'https://github.com/se-buw/se-slides.git'
)
$ErrorActionPreference = 'Stop'
if (Test-Path $Path) { throw "$Path already exists." }
$template = Join-Path (Split-Path $PSScriptRoot -Parent) 'template'

New-Item -ItemType Directory -Force $Path | Out-Null
Copy-Item -Recurse -Force (Join-Path $template '*') $Path
foreach ($hidden in @('.gitignore', '.vscode', '.github')) {
  Copy-Item -Recurse -Force (Join-Path $template $hidden) $Path
}
Get-ChildItem $Path -Recurse -File | Where-Object { $_.Extension -in '.yml', '.md', '.qmd', '.json' } | ForEach-Object {
  $text = [IO.File]::ReadAllText($_.FullName)
  $new = $text.Replace('__COURSE_TITLE__', $Title).Replace('__REPO__', $Repo)
  if ($new -ne $text) { [IO.File]::WriteAllText($_.FullName, $new, (New-Object Text.UTF8Encoding $false)) }
}

Push-Location $Path
try {
  git init -q -b main
  # file:// submodules (local testing) need protocol.file.allow
  git -c protocol.file.allow=always submodule add -q $SharedUrl _extensions/se-slides
  if ($LASTEXITCODE) { throw 'git submodule add failed' }
  git add -A
  Write-Host "Created $Path. Next:"
  Write-Host "  cd $Path"
  Write-Host "  ./build.ps1 01 -Preview"
} finally {
  Pop-Location
}
