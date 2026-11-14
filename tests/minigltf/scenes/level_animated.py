"""Level scene (see _level_common.py) plus an animated camera: auto mode
classifies it as a cutscene, so the instances stay sub-trees."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scene_utils import parse_args


def main():
    args = parse_args()
    sys.path.insert(0, args.repo_dir)
    from _level_common import build
    build(args, animate=True)


main()
