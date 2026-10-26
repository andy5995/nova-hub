"""The 8.3 guard.

A DOS path with an over-long component does not produce an error anywhere. The
16-bit Turbo Pascal the games are built with simply fails to traverse it, so the
game runs to completion, prints every phase marker, and ingests nothing at all.
That is the R-3 failure mode, and the only cheap way to catch it is to look at
the configured paths before trusting a run.

Deliberately importable with no rig setup -- it needs only sr-harness -- so it
can be pointed at a production config.toml as well as at the rig.
"""
from pathlib import Path

# The path rule itself lives in sr-harness, which drives the games for the rig;
# what is left here is the half that knows a hub config's shape.
from sr_harness.dospath import bbs_cfg_inbound, dos_path_problems  # noqa: F401


def config_problems(config: dict) -> list:
    """Every problem with the game paths in a hub config.

    Checks both halves of the pairing that matters: the DOS path the game is told
    to read (must be 8.3-clean) and the host path the hub writes into (must
    exist). A mismatch between them is invisible at runtime.
    """
    problems = []
    dosemu = config.get("dosemu", {}) or {}

    for league_id, games in dosemu.items():
        if not isinstance(games, dict):
            continue  # dosemu_path, timeout, term and friends
        for game, league_config in games.items():
            if not isinstance(league_config, dict):
                continue
            where = f"[dosemu.{league_id}.{game}]"

            for problem in dos_path_problems(league_config.get("game_dos_path", "")):
                problems.append(f"{where} game_dos_path: {problem}")

            for key in ("game_folder", "inbound_folder", "outbound_folder"):
                value = league_config.get(key)
                if not value:
                    problems.append(f"{where} {key} is not set")
                elif not Path(value).is_dir():
                    problems.append(f"{where} {key} does not exist: {value}")

    return problems

