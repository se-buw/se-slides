<#
.SYNOPSIS
  Lecture recordings: YouTube chapters and video links on the slides, from the slide log.
  Called by the course's video.ps1 from the course folder.

.DESCRIPTION
  While a deck is shown, se-slides.js logs every slide change with the time (in the browser);
  Shift+R in the deck saves the log as slidelog-<date>.json to Downloads. OBS names a recording
  after its start time ("2026-10-14 10-15-03.mkv"). This script matches the two: for each recording
  that shows the lecture it prints YouTube chapters (also copied to the clipboard) and writes
  lectures/<deck>.video.json, which the build turns into video links on the slides and the index.
  Running it again is safe: recordings are matched by their start time, IDs are kept.

  A slide links to its longest visit in a recording, so flipping through, previewing a slide and
  short recaps do not move the link. Log entries outside the recording are ignored.

.EXAMPLE
  ./video.ps1 02                                     # after the lecture: chapters to the clipboard
  ./video.ps1 02 -Id https://youtu.be/abcdefghijk    # after the upload; several recordings: IDs in recording order
  ./video.ps1 02 -Recording "D:/obs/2026-10-14 10-15-03.mkv"
  ./video.ps1 02 -Start "2026-10-14 10:15" -End "2026-10-14 11:45"   # recording window by hand
#>
param(
  [Parameter(Position = 0, Mandatory = $true)][string]$Lecture,
  [string[]]$Id = @(),
  [string[]]$Recording = @(),
  [string]$RecordingDir = $(if ($env:COURSE_RECORDINGS) { $env:COURSE_RECORDINGS } else { [Environment]::GetFolderPath('MyVideos') }),
  [string[]]$Log = @(),
  [string]$Start,
  [string]$End,
  [int]$MinChapter = 60
)
$ErrorActionPreference = 'Stop'
$Root = (Get-Location).Path
if (-not (Test-Path (Join-Path $Root '_quarto.yml'))) { throw "Run this from a course folder (no _quarto.yml in $Root)." }

$MERGE_GAP = 60       # s: a reload or a short close does not split the visit of a slide
$LEAD_IN = 3 * 3600   # s: the slide on screen when the recording starts may have been opened this long before
$MIN_GAP = 10         # s between YouTube chapters (YouTube's minimum)
$OBS_NAME = '(\d{4})-(\d{2})-(\d{2})[ _](\d{2})-(\d{2})-(\d{2})'
$BACK = [string][char]0x21A9  # ↩ before a slide the lecture comes back to

function Downloads-Folder {
  try {
    $p = (Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders' -ErrorAction Stop).'{374DE290-123F-4565-9164-39C4925E467B}'
    if ($p) { return [Environment]::ExpandEnvironmentVariables($p) }
  } catch { }
  return Join-Path $HOME 'Downloads'
}

function To-Ms([datetime]$t) { [DateTimeOffset]::new($t).ToUnixTimeMilliseconds() }

function Format-Time([long]$sec) {
  $t = [TimeSpan]::FromSeconds($sec)
  if ($t.TotalHours -ge 1) { '{0}:{1:00}:{2:00}' -f [int][Math]::Floor($t.TotalHours), $t.Minutes, $t.Seconds }
  else { '{0}:{1:00}' -f $t.Minutes, $t.Seconds }
}

# Start of a recording from its OBS file name (local time), otherwise the file's creation time
function Recording-Start([IO.FileInfo]$f) {
  $m = [regex]::Match($f.Name, $OBS_NAME)
  if (-not $m.Success) { return $f.CreationTime }
  $g = $m.Groups
  return [datetime]::new([int]$g[1].Value, [int]$g[2].Value, [int]$g[3].Value, [int]$g[4].Value, [int]$g[5].Value, [int]$g[6].Value, [DateTimeKind]::Local)
}

# End: start + length (ffprobe), otherwise the last write (OBS writes the file until the recording stops;
# a file remuxed later is newer, so install ffprobe if you remux)
function Recording-End([IO.FileInfo]$f, [datetime]$start) {
  $ffprobe = Get-Command ffprobe -ErrorAction SilentlyContinue
  if ($ffprobe) {
    $out = & $ffprobe.Source -v error -show_entries format=duration -of default=nw=1:nk=1 $f.FullName 2>$null
    $sec = 0.0
    if ([double]::TryParse("$out".Trim(), [Globalization.NumberStyles]::Float, [Globalization.CultureInfo]::InvariantCulture, [ref]$sec) -and $sec -gt 0) {
      return $start.AddSeconds($sec)
    }
  }
  return $f.LastWriteTime
}

# Visits over all decks: a slide is shown from its log entry until the next entry (any deck) or
# until its deck is closed ("away"). The last visit stays open and ends with the recording.
function Get-Visits($entries) {
  $visits = [System.Collections.Generic.List[object]]::new()
  $cur = $null
  foreach ($e in $entries) {
    if ($e.ev -eq 'away') {
      if ($cur -and $cur.d -eq $e.d) { $cur.b = [long]$e.t; $visits.Add($cur); $cur = $null }
      continue
    }
    if ($cur) { $cur.b = [long]$e.t; $visits.Add($cur) }
    $cur = [pscustomobject]@{ d = $e.d; i = $e.i; ti = $e.ti; l = [int]$e.l; s = $e.s; st = $e.st; a = [long]$e.t; b = [long]::MaxValue }
  }
  if ($cur) { $visits.Add($cur) }
  return $visits
}

# The visits of this deck within a recording [s, e] (ms), cut to the recording; visits of the same
# slide only interrupted by a reload or a short close are one visit
function Get-DeckVisits($visits, [long]$s, [long]$e) {
  $out = [System.Collections.Generic.List[object]]::new()
  foreach ($v in $visits) {
    if ($v.b -le $s -or $v.a -ge $e -or $v.a -lt $s - $LEAD_IN * 1000) { continue }
    $c = [pscustomobject]@{ d = $v.d; i = $v.i; ti = $v.ti; l = $v.l; s = $v.s; st = $v.st
      a = [Math]::Max($v.a, $s); b = [Math]::Min($v.b, $e) }
    $last = if ($out.Count) { $out[$out.Count - 1] } else { $null }
    if ($last -and $last.d -eq $c.d -and $last.i -eq $c.i -and $c.a - $last.b -le $MERGE_GAP * 1000) { $last.b = $c.b }
    else { $out.Add($c) }
  }
  return @($out | Where-Object d -eq $deck)
}

# slide id -> @(seconds into the recording, length of the visit), from the longest visit (the first on a tie)
function Get-SlideTimes($dv, [long]$s) {
  $best = @{}
  foreach ($v in $dv) {
    if (-not $v.i) { continue }
    $d = [long][Math]::Round(($v.b - $v.a) / 1000)
    if (-not $best.ContainsKey($v.i) -or $d -gt $best[$v.i][1]) {
      $best[$v.i] = @([long][Math]::Floor(($v.a - $s) / 1000), $d)
    }
  }
  return $best
}

# YouTube chapters in the order of the lecture: 0:00 the lecture, then each section (# heading) the
# first time its slides are shown for $MinChapter s in a row, and each slide shown that long
# (↩ when the lecture comes back to it). Chapters at least $MIN_GAP s apart.
function Get-Chapters($dv, [long]$s) {
  $min = $MinChapter * 1000
  $cands = [System.Collections.Generic.List[object]]::new()
  $sections = @{}
  for ($k = 0; $k -lt $dv.Count; $k++) {
    $sec = $dv[$k].s
    if (-not $sec -or $sections[$sec]) { continue }
    $j = $k
    while ($j + 1 -lt $dv.Count -and $dv[$j + 1].s -eq $sec -and $dv[$j + 1].a - $dv[$j].b -le $MERGE_GAP * 1000) { $j++ }
    if ($dv[$j].b - $dv[$k].a -ge $min) {
      $sections[$sec] = $true
      $cands.Add([pscustomobject]@{ t = $dv[$k].a; p = 0; title = $dv[$k].st; i = $null })
    }
  }
  foreach ($v in $dv) {
    if ($v.l -eq 2 -and $v.b - $v.a -ge $min) { $cands.Add([pscustomobject]@{ t = $v.a; p = 1; title = $v.ti; i = $v.i }) }
  }
  $kept = [System.Collections.Generic.List[object]]::new()
  $kept.Add([pscustomobject]@{ t = $s; title = $deckTitle; i = $null })
  $shown = @{}
  $lastSlide = $null
  foreach ($c in ($cands | Sort-Object t, p)) {
    if ($c.i -and $c.i -eq $lastSlide) { continue }  # back on the same slide after a short look elsewhere
    $again = $c.i -and $shown[$c.i]
    if ($c.i) { $shown[$c.i] = $true; $lastSlide = $c.i }
    # too close to the previous chapter (usually its section's): that chapter covers the slide
    if ($c.t - $kept[$kept.Count - 1].t -lt $MIN_GAP * 1000) { continue }
    if ($again) { $c.title = "$BACK $($c.title)" }
    $kept.Add($c)
  }
  return @($kept | ForEach-Object { "$(Format-Time ([Math]::Floor(($_.t - $s) / 1000))) $($_.title)" })
}

function YouTube-Id([string]$s) {
  $m = [regex]::Match($s, '(?:youtu\.be/|[?&]v=|/(?:live|shorts|embed)/)([\w-]{11})')
  if ($m.Success) { return $m.Groups[1].Value }
  if ($s -match '^[\w-]{11}$') { return $s }
  throw "Not a YouTube video ID or link: $s"
}

# One slide per line, in the order of the recording (readable diffs)
function ConvertTo-VideoJson($videos) {
  function q($s) { ConvertTo-Json -InputObject ([string]$s) }
  $lines = [System.Collections.Generic.List[string]]::new()
  $lines.Add('{'); $lines.Add('  "videos": [')
  for ($k = 0; $k -lt $videos.Count; $k++) {
    $v = $videos[$k]
    $lines.Add('    {')
    $lines.Add("      ""id"": $(q $v.id),")
    $lines.Add("      ""recording"": $(q $v.recording),")
    $lines.Add('      "slides": {')
    $keys = @($v.slides.Keys | Sort-Object { $v.slides[$_][0] }, { $_ })
    for ($j = 0; $j -lt $keys.Count; $j++) {
      $t = $v.slides[$keys[$j]]
      $lines.Add("        $(q $keys[$j]): [$($t[0]), $($t[1])]" + $(if ($j -lt $keys.Count - 1) { ',' } else { '' }))
    }
    $lines.Add('      }')
    $lines.Add('    }' + $(if ($k -lt $videos.Count - 1) { ',' } else { '' }))
  }
  $lines.Add('  ]'); $lines.Add('}')
  return ($lines -join "`n") + "`n"
}

# --- the lecture
$hit = @(Get-ChildItem lectures -Filter '*.qmd' | Where-Object { $_.BaseName -eq $Lecture -or $_.BaseName -like "$Lecture-*" })
if ($hit.Count -ne 1) { throw "'$Lecture' matches $($hit.Count) lectures" }
$deck = $hit[0].BaseName
$m = Select-String -Path $hit[0].FullName -Pattern '^title:\s*"?(.*?)"?\s*$' | Select-Object -First 1
$deckTitle = if ($m) { $m.Matches[0].Groups[1].Value } else { $deck }
$jsonPath = "lectures/$deck.video.json"

$videos = [System.Collections.Generic.List[object]]::new()
if (Test-Path $jsonPath) {
  foreach ($v in @((Get-Content -Raw $jsonPath | ConvertFrom-Json -AsHashtable).videos)) { $videos.Add($v) }
}

# --- the slide logs (each export holds the whole log of the browser, so all of them are merged)
$logFiles = if ($Log.Count) { $Log } else { @(Get-ChildItem (Downloads-Folder) -Filter 'slidelog*.json' -File | ForEach-Object FullName) }
foreach ($f in $logFiles) { if (-not (Test-Path -LiteralPath $f)) { throw "Slide log not found: $f" } }
$seen = @{}
$entries = @(foreach ($f in $logFiles) {
    foreach ($e in @(Get-Content -Raw $f | ConvertFrom-Json)) {
      $key = "$($e.t)|$($e.d)|$($e.i)|$($e.ev)"
      if (-not $seen.ContainsKey($key)) { $seen[$key] = $true; $e }
    }
  }) | Sort-Object { [long]$_.t }
$deckEntries = @($entries | Where-Object { $_.d -eq $deck -and $_.ev -ne 'away' })

# --- the recordings
$recordings = @()
if ($Start -or $End) {
  if (-not ($Start -and $End)) { throw '-Start and -End go together.' }
  $s = Get-Date $Start
  $recordings = @([pscustomobject]@{ recording = $s.ToString('yyyy-MM-dd HH-mm-ss'); start = $s; end = Get-Date $End })
} elseif ($deckEntries.Count) {
  $files = if ($Recording.Count) { @($Recording | ForEach-Object { Get-Item -LiteralPath $_ }) }
  elseif (Test-Path $RecordingDir) {
    @(Get-ChildItem $RecordingDir -File | Where-Object { $_.Extension -in '.mkv', '.mp4', '.mov', '.flv', '.ts' -and $_.Name -match $OBS_NAME })
  } else { Write-Warning "Recording folder not found: $RecordingDir (-RecordingDir or COURSE_RECORDINGS)"; @() }
  $first = [DateTimeOffset]::FromUnixTimeMilliseconds([long]$deckEntries[0].t).LocalDateTime
  $last = [DateTimeOffset]::FromUnixTimeMilliseconds([long]$deckEntries[-1].t).LocalDateTime
  # one recording per start time: OBS remuxing leaves an .mkv and an .mp4
  $recordings = @($files | ForEach-Object { [pscustomobject]@{ file = $_; start = Recording-Start $_ } } |
      Where-Object { $_.start -le $last -and $_.start -ge $first.AddDays(-1) } |
      Group-Object { $_.start } | ForEach-Object {
        $r = $_.Group | Sort-Object { if ($_.file.Extension -eq '.mp4') { 0 } else { 1 } } | Select-Object -First 1
        [pscustomobject]@{ recording = [IO.Path]::GetFileNameWithoutExtension($r.file.Name); start = $r.start; end = Recording-End $r.file $r.start }
      })
}

# --- match
$visits = Get-Visits $entries
$results = @()
foreach ($r in ($recordings | Sort-Object start)) {
  $s = To-Ms $r.start
  $e = To-Ms $r.end
  # the deck was used during the recording, not just left open on one slide
  if (-not @($deckEntries | Where-Object { [long]$_.t -ge $s -and [long]$_.t -lt $e }).Count) { continue }
  $dv = @(Get-DeckVisits $visits $s $e)
  $shown = ($dv | ForEach-Object { $_.b - $_.a } | Measure-Object -Sum).Sum / 1000
  if ($shown -lt $MinChapter) { continue }
  $results += [pscustomobject]@{
    recording = $r.recording; length = ($r.end - $r.start).TotalSeconds; shown = $shown
    slides = Get-SlideTimes $dv $s; chapters = Get-Chapters $dv $s
  }
}

if (-not $results.Count) {
  if ($Id.Count -and $videos.Count) {
    Write-Host "No (new) recording of $deck in the slide log; only setting the video ID(s)."
  } elseif (-not $logFiles.Count) {
    throw "No slidelog*.json in $(Downloads-Folder). Press Shift+R in the deck you presented to save the log (or -Log <file>)."
  } else {
    throw ("No recording shows $deck. Slide log: $($deckEntries.Count) entries for this deck in $($logFiles.Count) file(s); " +
      "recordings: $($recordings.Count) in the time of the log (folder $RecordingDir). Use -Recording <file> or -Start/-End.")
  }
}

# recordings without an ID that no longer show the deck (e.g. matched by an older version of this script)
$matched = @($results | ForEach-Object recording)
foreach ($v in @($videos | Where-Object { $_.id -eq 'TODO' -and $_.recording -notin $matched -and $_.recording -in @($recordings | ForEach-Object recording) })) {
  [void]$videos.Remove($v)
  Write-Host "Removed $($v.recording) (no longer shows $deck)"
}

$clip = @()
foreach ($r in $results) {
  $chapters = $r.chapters
  $old = $videos | Where-Object { $_.recording -eq $r.recording } | Select-Object -First 1
  Write-Host ""
  Write-Host "Recording $($r.recording) ($(Format-Time $r.length)): $deck shown $(Format-Time $r.shown), $($r.slides.Count) slides, $($chapters.Count) chapters" -ForegroundColor Cyan
  # with -Id the chapters of a known recording were printed before (and are in the description)
  if (-not ($Id.Count -and $old)) {
    $chapters | ForEach-Object { Write-Host "  $_" }
    if ($chapters.Count -lt 3) { Write-Warning "YouTube needs at least 3 chapters (lower -MinChapter, now $MinChapter s)." }
    if ($results.Count -gt 1) { $clip += "--- $($r.recording)" }
    $clip += $chapters
    if ($results.Count -gt 1) { $clip += '' }
  }

  if ($old) { $old.slides = $r.slides }
  else { $videos.Add([ordered]@{ id = 'TODO'; recording = $r.recording; slides = $r.slides }) }
}
if ($clip.Count) {
  try { Set-Clipboard -Value ($clip -join "`n"); Write-Host "`nChapters copied to the clipboard (paste them into the video description)." }
  catch { Write-Warning "Could not copy to the clipboard: $_" }
}

$videos = [System.Collections.Generic.List[object]]@($videos | Sort-Object { $_.recording })
if ($Id.Count) {
  $ids = @($Id | ForEach-Object { $_ -split ',' } | Where-Object { $_.Trim() } | ForEach-Object { YouTube-Id $_.Trim() })
  $todo = @($videos | Where-Object { $_.id -eq 'TODO' })
  if (-not $todo.Count -and $ids.Count -eq $videos.Count) { $todo = @($videos) }  # correcting the IDs
  if ($ids.Count -gt $todo.Count) { throw "$($ids.Count) ID(s) given, but $($todo.Count) recording(s) of $deck without an ID." }
  for ($k = 0; $k -lt $ids.Count; $k++) { $todo[$k].id = $ids[$k]; Write-Host "$($todo[$k].recording): https://youtu.be/$($ids[$k])" }
}

# slides that are gone from the deck since the recording (renamed, moved, deleted)
$html = "_site/lectures/$deck.html"
if (Test-Path $html) {
  $ids = @{}
  [regex]::Matches((Get-Content -Raw $html), '<section id="([^"]+)"') | ForEach-Object { $ids[$_.Groups[1].Value] = $true }
  $gone = @($videos | ForEach-Object { $_.slides.Keys } | Where-Object { -not $ids.ContainsKey($_) } | Sort-Object -Unique)
  if ($gone.Count) { Write-Warning "Not in $html (deck changed, or not rebuilt): $($gone -join ', ')" }
}

[IO.File]::WriteAllText((Join-Path $Root $jsonPath), (ConvertTo-VideoJson $videos), [Text.UTF8Encoding]::new($false))
Write-Host "Wrote $jsonPath"
$open = @($videos | Where-Object { $_.id -eq 'TODO' })
if ($open.Count) {
  Write-Host "Without a video ID: $(($open | ForEach-Object recording) -join ', ')"
  Write-Host "Next: upload the recording to YouTube, paste the chapters into the description, then  ./video.ps1 $Lecture -Id <link>"
} else {
  Write-Host "Next: commit $jsonPath; the build adds the video links to the slides and the lecture list."
}
