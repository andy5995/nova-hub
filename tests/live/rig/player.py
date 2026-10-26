#!/usr/bin/env python3
"""Drive BRE as a *player*, not as maintenance.

`node.run()` covers everything the game will do unattended. It explicitly refuses
FULL, because FULL is the player path and headless it blocks forever on "Do you
want ANSI Graphics? (Y/n)". This module is the answer to that refusal.

Why the rig needs it: an idle league emits packets on days one, two and three and
then goes quiet. Longer runs of traffic -- and any traffic carrying a score change
or a message -- need someone to actually play.

The walk itself -- prompts, turns, status, IP mail, IPScores, quitting -- is
`sr_harness.bre.Player`, and what was learned driving the game lives with it
(sr-harness's `bre-harness` skill). What stays here is the rig's own part:

  * `agent_round`, which hands the wheel to bre_agent;
  * the caller API (`visit`, `read_history`), which runs as the rig user and
    shells into the node's own unix user;
  * `main()`, which is what runs over there, driving dosemu on a pty.
"""
import json
import subprocess
import sys
from pathlib import Path

from sr_harness import Install, bre
from sr_harness.bre import parse_status  # noqa: F401  (re-exported)

from rig.layout import DOSEMU_CONF, LOGS, VENV_PYTHON, League, Node

# The BBS user name in the door file should be UNIQUE ACROSS THE LEAGUE. When
# duplicate checking is on -- it is a league setting, page 2 of the configuration
# editor during RESET, and changeable mid-league -- a name already playing on
# another board is refused outright:
#
#     Duplicate User Found on BBS #2 (Test Node 02), Player A
#     ... you cannot join this game.
#
# It is not a warning and there is no prompt to get past it: the session simply
# never reaches the main menu. The rig leaves the setting at its default and
# derives a unique name per node instead, which is correct either way.


def door_user(node_index: int) -> str:
    return f"TEST PILOT {node_index:02d}"


class Player(bre.Player):
    """One interactive BRE session on a rig install, as a player."""

    def __init__(self, install: Path, exe: str, dos_path: str, realm: str,
                 user: str = "TEST PILOT", transcript=None, conf=DOSEMU_CONF):
        super().__init__(Install(install, exe, dos_path=dos_path, conf=conf),
                         realm=realm, user=user, transcript=transcript)

    # ── the decision loop ─────────────────────────────────────────────────
    # bre_agent decides *what* to do; only send_message and wait have a real
    # counterpart here yet. Every other action is executed as a do-nothing turn:
    # v0 of the decision module has no notion of how much to buy, and a turn taken
    # on defaults is the honest approximation -- it still moves the score, which
    # is what the rig needs to move between hosts. The decision is logged either
    # way, so when the executor learns to buy things the history already says what
    # it was asked for.
    def agent_round(self, history_path=None, message=None) -> dict:
        """Read the realm's state, ask bre_agent what to do, and do it."""
        from dataclasses import fields

        from bre_agent import State, decide
        from bre_agent import history as agent_history

        status = self.status()
        known = {f.name for f in fields(State)}
        state = State.from_dict({k: v for k, v in status.items() if k in known})
        decision = decide(state)
        if history_path:
            agent_history.record(decision, history_path)

        if decision.action == "send_message":
            self.send_ip_message(message or (
                f"{state.realm_name} reports score {state.score}, "
                f"{state.turns} turns left."))
        elif decision.action != "wait":
            self.play_turns(1)

        self.events.append(f"agent chose {decision.action}")
        return {
            "action": decision.action,
            "goal_weights": decision.goal_weights,
            "scores": decision.scores,
            "excluded": decision.excluded,
            "status": status,
        }


# ── the CLI half: this is what runs as the node's own user ────────────────
def main(argv=None):
    plan = json.loads((argv or sys.argv)[1])
    if plan.get("activity_weight") is not None:
        # The rig's knob: bre_agent scores "be visibly present" against everything
        # else, and turning it up is how a league is made to keep talking without
        # touching any code path.
        from bre_agent import goals
        goals.ACTIVITY_WEIGHT = plan["activity_weight"]
    player = Player(
        install=Path(plan["install"]),
        exe=plan["exe"],
        dos_path=plan["dos_path"],
        realm=plan["realm"],
        user=plan.get("user", "TEST PILOT"),
        transcript=plan.get("transcript"),
    )
    result = {"events": player.events}
    try:
        player.start()
        result["status_before"] = player.status()
        if plan.get("turns"):
            result["turns_played"] = player.play_turns(plan["turns"])
            result["turn_text"] = player.turn_text
        for text in plan.get("ip_messages", []):
            player.send_ip_message(text)
        for _ in range(plan.get("agent_rounds", 0)):
            result.setdefault("decisions", []).append(
                player.agent_round(plan.get("history"), plan.get("message")))
            if player.turn_text:
                result["turn_text"] = player.turn_text
        if plan.get("read_ip_scores"):
            result["ip_scores"] = player.ip_scores(plan["read_ip_scores"])
        if plan.get("read_messages"):
            result["messages"] = player.read_messages()
        result["status_after"] = player.status()
    finally:
        result["events"] = player.events
        try:
            result["rc"] = player.quit()
        except Exception as exc:                     # pragma: no cover
            result["quit_error"] = str(exc)
    print("##PLAYER##" + json.dumps(result))
    return 0


# ── the caller half: this runs as the rig user ────────────────────────────
def _sudo(node: Node, *args) -> list:
    import getpass
    if node.user == getpass.getuser():
        return list(args)
    return ["sudo", "-u", node.user, "--", *args]


def visit(league: League, node: Node, realm: str = None, user: str = None,
          turns: int = 0, ip_messages=(), agent_rounds: int = 0,
          activity_weight=None, history=None, message=None, read_ip_scores=False,
          read_messages: bool = False, tag: str = "play",
          timeout: int = 900) -> dict:
    """Play this node's install as a human would, and report what changed.

    Returns the parsed status before and after, so a scenario can assert on a
    score change rather than merely on a packet appearing.

    `turns` and `ip_messages` say exactly what to do. `agent_rounds` instead hands
    the wheel to bre_agent: each round reads the realm's live state, asks for a
    decision and carries it out. That is the loop the whole three-part design is
    for -- the rig just happens to be its first caller.
    """
    install = league.install_path(node)
    log = LOGS / f"{tag}_{league.dirname(node.index)}_player.log"
    # The decision log is written by the *node's* user, so it cannot live in
    # pytest's tmp_path (owned by the test user, mode 700). LOGS is the rig's
    # shared, world-writable drop for exactly this. Start each session fresh:
    # bre_agent.history appends, and a rerun under the same tag would otherwise
    # read back as two sessions' worth.
    if history is None:
        history = LOGS / f"{tag}_{league.dirname(node.index)}_decisions.jsonl"
    if agent_rounds:
        subprocess.run(_sudo(node, "rm", "-f", str(history)), check=True)
    plan = {
        "install": str(install),
        "exe": league.g.exe,
        "dos_path": league.dos_path(node),
        "realm": realm or f"Realm {node.index:02d}",
        # Unique per node: see door_user().
        "user": user or door_user(node.index),
        "turns": turns,
        "ip_messages": list(ip_messages),
        # True means the default report; a name or key picks another.
        "agent_rounds": agent_rounds,
        "activity_weight": activity_weight,
        "history": str(history) if history else None,
        "message": message,
        "read_ip_scores": ("players_by_score" if read_ip_scores is True
                           else read_ip_scores),
        "read_messages": read_messages,
        "transcript": str(log),
    }
    try:
        result = subprocess.run(
            _sudo(node, str(VENV_PYTHON), "-m", "rig.player", json.dumps(plan)),
            cwd=str(Path(__file__).resolve().parents[1]),
            capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        # A killed session leaves the game's mutex behind, and then every later
        # run on this install exits 1 having printed nothing about why -- so one
        # hung walk would fail every test after it. Clear it, and say where the
        # walk got stuck rather than leaving that in a log nobody reads.
        subprocess.run(_sudo(node, "rm", "-f", str(install / "inuse.flg")),
                       check=False)
        tail = subprocess.run(_sudo(node, "tail", "-c", "1500", str(log)),
                              capture_output=True, text=True, check=False)
        raise RuntimeError(
            f"player session on {league.league_id} node {node.index} did not "
            f"finish within {timeout}s -- most likely an unanswered prompt.\n"
            f"--- last of the transcript ---\n{tail.stdout}"
        ) from None
    marker = "##PLAYER##"
    if marker not in result.stdout:
        raise RuntimeError(
            f"player session on {league.league_id} node {node.index} produced no "
            f"result:\nstdout: {result.stdout[-2000:]}\nstderr: {result.stderr[-2000:]}"
        )
    out = json.loads(result.stdout.split(marker, 1)[1].splitlines()[0])
    out["log"] = str(log)
    out["history"] = str(history)
    return out


def read_history(node: Node, path) -> list:
    """Read back a decision log the node user wrote."""
    result = subprocess.run(
        _sudo(node, "cat", str(path)), capture_output=True, text=True, check=True
    )
    return [json.loads(line) for line in result.stdout.splitlines() if line.strip()]


if __name__ == "__main__":
    sys.exit(main())
