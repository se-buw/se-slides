#!/usr/bin/env bash
# Builds a course's slides (Linux/macOS/CI). Called by the course's build.sh from the course folder.
#   build.sh [lecture ...] [--pdf] [--strict] [--lenient] [--show-layout]
set -euo pipefail
[ -f _quarto.yml ] || { echo "Run this from a course folder (no _quarto.yml in $PWD)"; exit 1; }

pdf=0
targets=()
for a in "$@"; do
  case "$a" in
    --pdf) pdf=1 ;;
    --strict) export COURSE_STRICT=1 ;;
    --lenient) export COURSE_LENIENT=1 ;;
    --show-layout) export COURSE_LAYOUT_MARKS=1 ;;
    *) for f in lectures/"$a".qmd lectures/"$a"-*.qmd; do [ -f "$f" ] && targets+=("$f"); done ;;
  esac
done

cache="${SE_SLIDES_HOME:-$HOME/.cache/se-slides}"
quarto=quarto
[ -x "$cache/quarto/bin/quarto" ] && quarto="$cache/quarto/bin/quarto"

# Quarto 1.10 fails on a second explicitly named file in a website project: render one by one
# The index page lists the lectures' titles: render it with them.
if [ ${#targets[@]} -eq 0 ]; then
  "$quarto" render
else
  for t in "${targets[@]}"; do "$quarto" render "$t"; done
  if [ -f index.qmd ]; then "$quarto" render index.qmd; fi
fi

if [ "$pdf" = 1 ]; then
  browser="${COURSE_BROWSER:-$(command -v google-chrome || command -v chromium || command -v chromium-browser)}"
  mkdir -p _site/pdf
  profile="$(mktemp -d)"
  if [ ${#targets[@]} -eq 0 ]; then targets=(lectures/[0-9]*.qmd); fi
  for t in "${targets[@]}"; do
    d="$(basename "$t" .qmd)"
    echo "PDF  $d"
    "$browser" --headless=new --disable-gpu --no-sandbox --user-data-dir="$profile" --no-pdf-header-footer \
      --run-all-compositor-stages-before-draw --virtual-time-budget=30000 \
      --print-to-pdf="$PWD/_site/pdf/$d.pdf" "file://$PWD/_site/lectures/$d.html?print-pdf" >/dev/null 2>&1
    [ -f "_site/pdf/$d.pdf" ] || { echo "PDF export failed for $d"; exit 1; }
  done
fi
