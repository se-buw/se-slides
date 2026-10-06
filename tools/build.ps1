<#
.SYNOPSIS
  Builds a course's slides: checks all code, renders HTML, optionally PDF and a Moodle bundle.
  Called by the course's build.ps1 from the course folder.

.EXAMPLE
  ./build.ps1                 # all lectures, HTML only (_site/)
  ./build.ps1 05              # only lecture 05, HTML
  ./build.ps1 05 -Pdf         # lecture 05, HTML + PDF (_site/pdf/)
  ./build.ps1 -Pdf -Moodle    # everything, plus dist/moodle-<date>.zip
  ./build.ps1 05 -Preview     # live preview in the browser while editing
  ./build.ps1 -Lenient        # drafting: missing alt texts, credits, regions are warnings
  ./build.ps1 -Strict         # release: also fail on ::: todo blocks and layout problems
  ./build.ps1 05 -Layout      # HTML plus layout report (also part of -Pdf)
  ./build.ps1 05 -ShowLayout  # also mark overflowing slides in the browser and PDF
#>
param(
  [Parameter(Position = 0, ValueFromRemainingArguments = $true)][string[]]$Lecture = @(),
  [switch]$Pdf,
  [switch]$Moodle,
  [switch]$Preview,
  [switch]$Strict,
  [switch]$Lenient,
  [switch]$Layout,
  [switch]$ShowLayout
)
$ErrorActionPreference = 'Stop'
$Root = (Get-Location).Path
if (-not (Test-Path (Join-Path $Root '_quarto.yml'))) { throw "Run this from a course folder (no _quarto.yml in $Root)." }
$ToolCache = if ($env:SE_SLIDES_HOME) { $env:SE_SLIDES_HOME } else { Join-Path $env:LOCALAPPDATA 'se-slides' }

function Find-Quarto {
  $cached = Join-Path $ToolCache 'quarto/bin/quarto.exe'
  if (Test-Path $cached) { return $cached }
  $q = Get-Command quarto -ErrorAction SilentlyContinue
  if ($q) { return $q.Source }
  throw "Quarto not found. Run $PSScriptRoot/bootstrap.ps1 once."
}

function Find-Browser {
  if ($env:COURSE_BROWSER) { return $env:COURSE_BROWSER }
  # Preferred: the pinned chrome-headless-shell from bootstrap.ps1. It is made for scripted
  # printing and independent of the browser you use (updates, profiles, policies).
  $shell = Join-Path $ToolCache 'chrome-headless-shell/chrome-headless-shell.exe'
  if (Test-Path $shell) { return $shell }
  foreach ($p in @(
      "$env:ProgramFiles/Google/Chrome/Application/chrome.exe",
      "${env:ProgramFiles(x86)}/Google/Chrome/Application/chrome.exe",
      "${env:ProgramFiles(x86)}/Microsoft/Edge/Application/msedge.exe",
      "$env:ProgramFiles/Microsoft/Edge/Application/msedge.exe")) {
    if (Test-Path $p) { return $p }
  }
  throw "No browser for PDF export. Run $PSScriptRoot/bootstrap.ps1 or set COURSE_BROWSER."
}

function Resolve-Lectures([string[]]$names) {
  if ($names.Count -eq 0) { return @() }
  $files = foreach ($n in $names) {
    $hit = Get-ChildItem lectures -Filter '*.qmd' | Where-Object { $_.BaseName -eq $n -or $_.BaseName -like "$n-*" }
    if (-not $hit) { throw "No lecture matches '$n'" }
    $hit | ForEach-Object { "lectures/$($_.Name)" }
  }
  return @($files)
}

function All-Decks {
  Get-ChildItem lectures -Filter '*.qmd' | Where-Object Name -match '^\d' | ForEach-Object BaseName
}

function Export-Pdf([string[]]$targets) {
  $browser = Find-Browser
  $profileDir = Join-Path ([IO.Path]::GetTempPath()) 'se-slides-pdf-profile'
  New-Item -ItemType Directory -Force '_site/pdf' | Out-Null
  $decks = if ($targets.Count) { $targets | ForEach-Object { [IO.Path]::GetFileNameWithoutExtension($_) } } else { All-Decks }
  foreach ($d in $decks) {
    $html = (Resolve-Path "_site/lectures/$d.html").Path -replace '\\', '/'
    $pdf = Join-Path $Root "_site/pdf/$d.pdf"
    Write-Host "PDF  $d"
    Remove-Item $pdf -ErrorAction SilentlyContinue
    $chromeArgs = @('--disable-gpu', "--user-data-dir=$profileDir", '--no-pdf-header-footer',
      '--run-all-compositor-stages-before-draw', '--virtual-time-budget=30000',
      "--print-to-pdf=$pdf", "file:///$html`?print-pdf")
    if ($browser -notmatch 'chrome-headless-shell') { $chromeArgs = @('--headless=new') + $chromeArgs }
    # Start-Process does not quote: quote arguments with spaces (course folders with spaces)
    $chromeArgs = $chromeArgs | ForEach-Object { if ($_ -match ' ') { '"' + $_ + '"' } else { $_ } }
    # a browser that hangs must not block a nightly build
    # The browser occasionally prints before the slides are laid out (a 1-page PDF):
    # compare the page count with the number of slides and retry once.
    $expected = (Select-String -Path "lectures/$d.qmd" -Pattern '^#{1,2} ' | Measure-Object).Count
    for ($attempt = 1; $attempt -le 2; $attempt++) {
      Remove-Item $pdf -ErrorAction SilentlyContinue
      $p = Start-Process -FilePath $browser -ArgumentList $chromeArgs -PassThru -NoNewWindow -RedirectStandardError "$profileDir.log"
      if (-not $p.WaitForExit(120000)) { Stop-Process -Id $p.Id -Force; throw "PDF export of $d timed out ($browser)" }
      if (-not (Test-Path $pdf)) { throw "PDF export failed for $d ($browser)" }
      $pages = ([regex]::Matches([IO.File]::ReadAllText($pdf, [Text.Encoding]::Latin1), '/Type /Page[^s]')).Count
      if ($pages -ge $expected) { break }
      Write-Host "     only $pages of $expected pages, retrying"
    }
    if ($pages -lt $expected) { throw "PDF of $d has only $pages pages, expected at least $expected" }
  }
}

# Layout report: opens each deck's print view headless; se-slides.js lists the slides whose
# content runs into the footer or whose listings are clipped (#course-layout-report in the DOM).
# Written to _build/layout/<deck>.txt; returns the number of problems.
function Test-Layout([string[]]$targets) {
  $browser = Find-Browser
  $profileDir = Join-Path ([IO.Path]::GetTempPath()) 'se-slides-layout-profile'
  New-Item -ItemType Directory -Force '_build/layout' | Out-Null
  $decks = if ($targets.Count) { $targets | ForEach-Object { [IO.Path]::GetFileNameWithoutExtension($_) } } else { All-Decks }
  # the index page is a deck, too (its lecture list is split across slides)
  if (Test-Path '_site/index.html') { $decks = @($decks) + 'index' }
  $total = 0
  foreach ($d in $decks) {
    $file = if ($d -eq 'index') { '_site/index.html' } else { "_site/lectures/$d.html" }
    $html = (Resolve-Path $file).Path -replace '\\', '/'
    $dom = Join-Path $Root "_build/layout/$d.dom.html"
    $chromeArgs = @('--disable-gpu', "--user-data-dir=$profileDir", '--window-size=1280,720',
      '--run-all-compositor-stages-before-draw', '--virtual-time-budget=30000', '--dump-dom', "file:///$html`?print-pdf")
    if ($browser -notmatch 'chrome-headless-shell') { $chromeArgs = @('--headless=new') + $chromeArgs }
    $chromeArgs = $chromeArgs | ForEach-Object { if ($_ -match ' ') { '"' + $_ + '"' } else { $_ } }
    $p = Start-Process -FilePath $browser -ArgumentList $chromeArgs -PassThru -NoNewWindow -RedirectStandardOutput $dom -RedirectStandardError "$profileDir.log"
    if (-not $p.WaitForExit(120000)) { Stop-Process -Id $p.Id -Force; throw "Layout check of $d timed out ($browser)" }
    $m = [regex]::Match([IO.File]::ReadAllText($dom), '<div id="course-layout-report" hidden="">(.*?)</div>')
    Remove-Item $dom -ErrorAction SilentlyContinue
    if (-not $m.Success) { Write-Warning "Layout check of $d produced no report"; continue }
    $problems = @([Net.WebUtility]::HtmlDecode($m.Groups[1].Value) | ConvertFrom-Json)
    $lines = $problems | ForEach-Object { "slide $($_.page): $($_.problem) :: $($_.title)" }
    Set-Content -Path "_build/layout/$d.txt" -Value $lines -Encoding utf8
    if ($problems.Count) {
      Write-Host "LAYOUT $d - $($problems.Count) problem(s):" -ForegroundColor Yellow
      $lines | ForEach-Object { Write-Host "  $_" -ForegroundColor Yellow }
    } else { Write-Host "LAYOUT $d - ok" }
    $total += $problems.Count
  }
  return $total
}

# index.html of the Moodle bundle: the decks link back to ../index.html
function Write-MoodleIndex([string]$staging, [string]$courseTitle) {
  $rows = foreach ($f in Get-ChildItem "$staging/html" -Filter '*.html' | Sort-Object Name) {
    $qmd = "lectures/$($f.BaseName).qmd"
    $title = $f.BaseName
    if (Test-Path $qmd) {
      $m = Select-String -Path $qmd -Pattern '^title:\s*"?(.*?)"?\s*$' | Select-Object -First 1
      if ($m) { $title = $m.Matches[0].Groups[1].Value }
    }
    $pdf = if (Test-Path "$staging/pdf/$($f.BaseName).pdf") { "<a href=""pdf/$($f.BaseName).pdf"">PDF</a>" } else { '' }
    "<tr><td>$($f.BaseName.Substring(0, 2))</td><td><a href=""html/$($f.Name)"">$([Net.WebUtility]::HtmlEncode($title))</a></td><td>$pdf</td></tr>"
  }
  $t = [Net.WebUtility]::HtmlEncode($courseTitle)
  $html = @"
<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>$t</title>
<style>
body { font-family: "Segoe UI", Arial, sans-serif; max-width: 760px; margin: 2em auto; padding: 0 16px; color: #1a1a1a; }
table { border-collapse: collapse; width: 100%; } td { padding: .4em .6em; border-bottom: 1px solid #ddd; }
a { color: #1d4e89; }
</style></head><body>
<h1>$t</h1>
<p>Slides as HTML (code listings with copy buttons) and PDF. Example code: folder <code>code/</code>.</p>
<table>
$($rows -join "`n")
</table>
</body></html>
"@
  Set-Content -Path "$staging/index.html" -Value $html -Encoding utf8
}

function Course-Title {
  $m = Select-String -Path '_quarto.yml' -Pattern '^\s+title:\s*"?(.*?)"?\s*$' | Select-Object -First 1
  if ($m) { return $m.Matches[0].Groups[1].Value } else { return 'Slides' }
}

$quarto = Find-Quarto
$targets = @(Resolve-Lectures $Lecture)
if ($Strict) { $env:COURSE_STRICT = '1' } else { Remove-Item Env:COURSE_STRICT -ErrorAction SilentlyContinue }
if ($Lenient) { $env:COURSE_LENIENT = '1' } else { Remove-Item Env:COURSE_LENIENT -ErrorAction SilentlyContinue }
# Visible layout marks (red outline and label) only on request; the layout report does not need them.
if ($ShowLayout) { $env:COURSE_LAYOUT_MARKS = '1' } else { Remove-Item Env:COURSE_LAYOUT_MARKS -ErrorAction SilentlyContinue }
# Your local HTML opens files in VS Code from this checkout by default.
$env:COURSE_VSCODE_ROOT = $Root -replace '\\', '/'

if ($Preview) {
  & $quarto preview @targets
  exit $LASTEXITCODE
}

# Quarto 1.10 fails on a second explicitly named file in a website project
# ("withBinaryFile: does not exist"), so named lectures are rendered one by one.
# The index page lists the lectures' titles: render it with them.
$renderTargets = if ($targets.Count -and (Test-Path 'index.qmd')) { @($targets) + 'index.qmd' } else { $targets }
if ($renderTargets.Count -le 1) {
  & $quarto render @renderTargets
  if ($LASTEXITCODE) { exit $LASTEXITCODE }
} else {
  foreach ($t in $renderTargets) {
    & $quarto render $t
    if ($LASTEXITCODE) { exit $LASTEXITCODE }
  }
}

if ($Pdf -or $Moodle) { Export-Pdf $targets }
if ($Pdf -or $Moodle -or $Layout -or $Strict) {
  $layoutProblems = Test-Layout $targets
  if ($Strict -and $layoutProblems) { throw "$layoutProblems layout problem(s), see _build/layout/" }
}

if ($Moodle) {
  # Self-contained HTML files without the local VS Code path and without layout marks
  $env:COURSE_VSCODE_ROOT = ''
  Remove-Item Env:COURSE_LAYOUT_MARKS -ErrorAction SilentlyContinue
  $moodleTargets = if ($targets.Count) { $targets } else { @($null) }
  foreach ($t in $moodleTargets) {
    if ($t) { & $quarto render $t --output-dir _build/moodle -M embed-resources:true }
    else { & $quarto render --output-dir _build/moodle -M embed-resources:true }
    if ($LASTEXITCODE) { exit $LASTEXITCODE }
  }
  New-Item -ItemType Directory -Force dist | Out-Null
  $zip = "dist/moodle-$(Get-Date -Format yyyy-MM-dd).zip"
  $staging = '_build/moodle-bundle'
  Remove-Item -Recurse -Force $staging -ErrorAction SilentlyContinue
  New-Item -ItemType Directory -Force "$staging/html", "$staging/pdf", "$staging/code" | Out-Null
  Copy-Item _build/moodle/lectures/*.html "$staging/html/"
  Copy-Item _site/pdf/*.pdf "$staging/pdf/" -ErrorAction SilentlyContinue
  Copy-Item -Recurse code/* "$staging/code/"
  Write-MoodleIndex $staging (Course-Title)
  Compress-Archive -Force -Path "$staging/*" -DestinationPath $zip
  Write-Host "Moodle bundle: $zip"
}
