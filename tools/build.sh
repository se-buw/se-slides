#!/usr/bin/env bash
# Builds a course's slides (Linux/macOS/CI). Called by the course's build.sh from the course folder.
#   build.sh [lecture ...] [--pdf] [--strict] [--lenient]
set -euo pipefail
[ -f _quarto.yml ] || { echo "Run this from a course folder (no _quarto.yml in $PWD)"; exit 1; }

pdf=0
targets=()
for a in "$@"; do
  case "$a" in
    --pdf) pdf=1 ;;
    --strict) export COURSE_STRICT=1 ;;
    --lenient) export COURSE_LENIENT=1 ;;
    *) for f in lectures/"$a".qmd lectures/"$a"-*.qmd; do [ -f "$f" ] && targets+=("$f"); done ;;
  esac
done

cache="${SE_SLIDES_HOME:-$HOME/.cache/se-slides}"
quarto=quarto
[ -x "$cache/quarto/bin/quarto" ] && quarto="$cache/quarto/bin/quarto"

"$quarto" render "${targets[@]}"

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
