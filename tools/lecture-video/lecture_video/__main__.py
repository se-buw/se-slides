"""lecture-video: narrated lecture videos from the slides. Run from the course folder.

  check    [lectures] [--lang en,de] [--stale] [--quiet]   narration against the slides
  stamp    [lectures] [--lang ..] [--force]                after a review: remember the slides
  fix-ids  [lectures] [--lang ..]                          follow renamed slides
  estimate [lectures] [--lang ..]                          runtime from the word count
  frames   [lectures] [--force]                            the pictures of all steps
  build    [lectures] [--lang ..] [--force]                the videos: _video/<deck>.<lang>.mp4
  sample   [--lang en,de] [--text ...]                    the configured voices on a test paragraph
"""
from __future__ import annotations

import argparse
import sys

from . import course


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="lecture-video", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["check", "stamp", "fix-ids", "estimate", "frames", "build", "sample"])
    ap.add_argument("lectures", nargs="*")
    ap.add_argument("--lang", help="comma-separated, default: all narration files of the deck")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--stale", action="store_true", help="check: only changed slides, with their narration")
    ap.add_argument("--quiet", action="store_true", help="check: no INFO lines")
    ap.add_argument("--text", help="sample: the text to speak")
    a = ap.parse_args(argv)
    langs = a.lang.split(",") if a.lang else None

    if a.command == "sample":
        from . import build
        return build.sample(langs or sorted(course.load_config()["voices"]), a.text)
    decks = course.resolve(a.lectures)
    if not decks:
        print("No lecture with narration (lectures/<deck>.narration.<lang>.md).")
        return 0
    if a.command in ("check", "stamp", "fix-ids", "estimate"):
        from . import check
        if a.command == "check":
            return check.run_check(decks, langs, a.stale, a.quiet)
        if a.command == "stamp":
            return check.stamp(decks, langs, a.force)
        if a.command == "fix-ids":
            return check.fix_ids(decks, langs)
        return check.estimate(decks, langs)
    if a.command == "frames":
        from . import frames
        for d in decks:
            frames.capture(d, a.force)
        return 0
    from . import build
    return build.build(decks, langs, a.force)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
