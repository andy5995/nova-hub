#!/usr/bin/env python3
"""
Trace BRE attacks in packets the hub stored before attack tracing existed.

New packets are traced as they arrive. This reads the ones already on disk
(packets/processed, outbound and inbound under data_dir) so that attacks sent
before the upgrade -- including any MIT still being chased -- appear in the
Attacks view. A file is used only when its SHA-256 matches the packet row:
filenames repeat every thousand packets, and a same-named file may be a later one.

Additive and idempotent: it only writes attack_sightings and
league_game_settings, and a packet already traced is skipped.

    .venv/bin/python backfill_attacks.py
    .venv/bin/python backfill_attacks.py --redo     # re-read every packet
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from backend.core.config import init_config
from backend.core.database import get_session, init_database
from backend.services.attack_trace import backfill


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default="config.toml", help="path to config.toml")
    parser.add_argument("--redo", action="store_true",
                        help="re-read packets that already have sightings")
    args = parser.parse_args()

    config = init_config(args.config)
    init_database(f"sqlite:///{config.database.path}")
    data_dir = Path(config._raw.get("server", {}).get("data_dir", "./data"))

    counts = backfill(get_session(), data_dir, redo=args.redo)
    print(f"BRE packets examined:   {counts['packets']}")
    print(f"  traced:               {counts['traced']}")
    print(f"  attack sightings:     {counts['sightings']}")
    print(f"  file no longer held:  {counts['missing']}")
    print(f"  file is a later one:  {counts['mismatched']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
