#!/usr/bin/env python3
"""
Re-read stored transcripts into the Movements rows, after the 0.8.1 parser fix.

The parser used to join a node number to digits the game painted elsewhere on
the screen (1->31194), and to lose records spaced with cursor-forward. Every
run whose transcript is still held is re-parsed and, where the result differs,
its rows are rewritten under the same leagues. Older runs, whose transcripts
retention has blanked, only lose node numbers above 255, which no board has.

Reports what it would change unless given --apply. Safe to run again.

    .venv/bin/python reparse_movements.py
    .venv/bin/python reparse_movements.py --apply
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from backend.core.config import init_config
from backend.core.database import get_session, init_database
from backend.services.movement_repair import repair


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default="config.toml", help="path to config.toml")
    parser.add_argument("--apply", action="store_true", help="write the changes")
    args = parser.parse_args()

    config = init_config(args.config)
    init_database(f"sqlite:///{config.database.path}")

    counts = repair(get_session(), apply=args.apply)
    verb = "rewritten" if args.apply else "would be rewritten"
    print(f"Runs with a transcript:      {counts['runs_read']}")
    print(f"  {verb}:{' ' * (24 - len(verb))}{counts['runs_changed']}"
          f" ({counts['rows_before']} rows -> {counts['rows_after']})")
    if counts["unsure"]:
        print(f"  left alone, league unsure: {len(counts['unsure'])} "
              f"(runs {', '.join(map(str, counts['unsure'][:20]))})")
    print(f"Older nodes over 255 {'cleared' if args.apply else 'to clear'}: "
          f"{counts['purged_nodes_cleared']}")
    if not args.apply:
        print("Nothing written; run with --apply to make these changes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
