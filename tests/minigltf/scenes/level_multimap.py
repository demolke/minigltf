"""Level scene: instances of two libraries (see _level_common.py). Imported in
auto mode this is a level, so the instances become one MultiMap."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scene_utils import parse_args


def main():
    args = parse_args()
    sys.path.insert(0, args.repo_dir)
    from _level_common import build
    build(args)


main()
