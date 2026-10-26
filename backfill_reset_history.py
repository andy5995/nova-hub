#!/usr/bin/env python3
"""
Fill in the reset history of BRE leagues from the packets already on disk.

A league-wide reset goes out as a Game Start record in the coordinator's next
packets. New ones are recorded as they pass; this reads the ones stored before
(packets/processed, outbound and inbound under data_dir), so the console's
history goes back as far as the hub's packets do. A file is used only when its
SHA-256 matches the packet row.

Additive and idempotent: it only adds game_resets rows with source "observed",
or confirms a console reset with the Game Start that followed it.

    .venv/bin/python backfill_reset_history.py
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from backend.core.config import init_config
from backend.core.database import get_session, init_database
from backend.services.game_reset.history import backfill


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default="config.toml", help="path to config.toml")
    args = parser.parse_args()

    config = init_config(args.config)
    init_database(f"sqlite:///{config.database.path}")
    data_dir = Path(config._raw.get("server", {}).get("data_dir", "./data"))

    counts = backfill(get_session(), data_dir)
    print(f"BRE packets examined:   {counts['packets']}")
    print(f"  Game Start records:   {counts['game_starts']}")
    print(f"  file no longer held:  {counts['missing']}")
    print(f"  could not be decoded: {counts['failed']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
