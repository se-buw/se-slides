# Entry point: python lv.py <command> ... (from the course folder). See lecture_video/__main__.py.
# check/stamp/fix-ids/estimate need only the standard library (build.ps1 runs check in every build).
import sys

from lecture_video.__main__ import main

sys.exit(main(sys.argv[1:]))
