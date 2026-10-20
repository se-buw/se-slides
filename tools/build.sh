#!/usr/bin/env bash
# Builds a course's slides (Linux/macOS/CI). Called by the course's build.sh from the course folder.
#   build.sh [lecture ...] [--pdf] [--strict] [--lenient] [--show-layout] [--clean] [--release]
#   --release: only the lectures in release.txt (all if there is none); the index lists only them
set -euo pipefail
[ -f _quarto.yml ] || { echo "Run this from a course folder (no _quarto.yml in $PWD)"; exit 1; }

# lectures/NAME.qmd or lectures/NAME-*.qmd ("05" or "05-loops")
lecture_files() {
  for f in lectures/"$1".qmd lectures/"$1"-*.qmd; do [ -f "$f" ] && echo "$f"; done
  return 0
}

pdf=0
release=0
targets=()
for a in "$@"; do
  case "$a" in
    --pdf) pdf=1 ;;
    --strict) export COURSE_STRICT=1 ;;
    --lenient) export COURSE_LENIENT=1 ;;
    --show-layout) export COURSE_LAYOUT_MARKS=1 ;;
    --clean) export COURSE_CLEAN=1 ;;
    --release) release=1 ;;
    *) while read -r f; do targets+=("$f"); done < <(lecture_files "$a") ;;
  esac
done

if [ "$release" = 1 ]; then
  released=()
  if [ -f release.txt ]; then
    while read -r line; do
      name="$(echo "${line%%#*}" | tr -d '[:space:]')"
      [ -n "$name" ] || continue
      found="$(lecture_files "$name")"
      [ -n "$found" ] || { echo "release.txt: no lecture matches '$name'"; exit 1; }
      while read -r f; do released+=("$f"); done <<< "$found"
    done < release.txt
  else
    released=(lectures/[0-9]*.qmd)
  fi
  # named lectures: only those that are released
  if [ ${#targets[@]} -gt 0 ]; then
    kept=()
    for t in "${targets[@]}"; do
      for r in "${released[@]}"; do [ "$t" = "$r" ] && kept+=("$t"); done
    done
    released=("${kept[@]}")
  fi
  [ ${#released[@]} -gt 0 ] || { echo "No released lecture to build"; exit 1; }
  targets=("${released[@]}")
  names=()
  for t in "${targets[@]}"; do names+=("$(basename "$t" .qmd)"); done
  export COURSE_RELEASE="${names[*]}"
  echo "Release: ${names[*]}"
fi

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

# Narration of the generated lecture videos against the slides (README: "Generated lecture videos").
# Errors (renamed slides, wrong [click] counts, slides without narration) fail --strict.
decks=()
for t in "${targets[@]:-lectures/[0-9]*.qmd}"; do
  for f in $t; do
    d="$(basename "$f" .qmd)"
    compgen -G "lectures/$d.narration.*.md" >/dev/null && decks+=("$d")
  done
done
if [ ${#decks[@]} -gt 0 ]; then
  status=0
  python3 "$(dirname "$0")/lecture-video/lv.py" check "${decks[@]}" --quiet || status=$?
  if [ "$status" = 2 ] && [ -n "${COURSE_STRICT:-}" ]; then echo "Narration errors, see above"; exit 1; fi
  [ "$status" -le 2 ] || exit "$status"
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
