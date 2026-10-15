"""Typing a reset's settings into the game's own editor, and reading them back.

`<EXE> RESET` asks "reset the Game?", wipes the game the moment it is answered
Y, then opens a two-page Configuration Editor. ESC saves and leaves, and the
HOST is then asked whether the reset is league-wide. The hub never writes
GAME.DAT itself: it is checksummed, so the editor is the only safe writer.

What the driver relies on, all seen on the test rig (15 Oct 2026):

- A page is a list of `Label : value` rows under a title holding
  "Configuration Editor", above a footer holding "[ESC] to Save & Quit".
  InterBBS labels start with a `*`.
- The cursor starts on a page's first row, moves with the arrow keys, and stays
  on a row after it is answered. PgDn and PgUp switch pages.
- Enter on a row replaces the page with that setting's help, titled
  `──═<topic>═──`; the topic is the catalogue's `help_title`. Then:
    number   "Enter New Value: (current; max)"; digits and Enter.
    choice   "New Setting:"; one letter, no Enter. Sabre's C then asks
             "Enter value >" for the dial; digits and Enter.
    toggle   flips at once and waits for a key. Most say "This option has
             been toggled."; BRE's Steady Investment says "The setting for
             this option has been switched." over a Paused marker.
    date     "Day (current; max)", "Month (...)" and "Year (...)", one at a
             time, each digits and Enter. BRE asks Day first, FE Month.
- A value over the maximum is put back on the prompt and waits for a second
  Enter. A letter the field doesn't take is ignored. Either way the editor
  doesn't come back, which is how the driver notices: validation should have
  stopped both, so it aborts rather than guess.

Every step waits on the live screen only, never on the history of the byte
stream: a prompt seen once would match there forever.
"""
import re
import time
from datetime import date
from typing import Callable, Optional

from backend.services.game_reset.fields import CHOICE, DATE, NUMBER, TOGGLE, fields_for

EDITOR = "Configuration Editor"
FOOTER = "[ESC] to Save & Quit"
DOWN, UP, PGDN, PGUP, ESC = "\x1b[B", "\x1b[A", "\x1b[6~", "\x1b[5~", "\x1b"

_ROW = re.compile(r"^\*?(?P<label>\S.*?)\s*: (?P<value>.*?)\s*$")
_TOPIC = re.compile(r"──═(?P<topic>[^═]+)═──")
_NUMBER_PROMPT = re.compile(r"Enter New Value: \(\d+; \d+\)\s*(?P<typed>.*)$")
_CHOICE_PROMPT = re.compile(r"New Setting:\s*$")
_DIAL_PROMPT = re.compile(r"Enter value >\s*$")
_TOGGLED = re.compile(r"option has been (toggled|switched)")
_DATE_PROMPT = re.compile(r"^(?P<part>Day|Month|Year) \(\d+; \d+\)\s*$")
_ASK_RESET = re.compile(r"reset the Game", re.I)
_ASK_LEAGUE_WIDE = re.compile(r"league-wide reset", re.I)

# How a choice reads on the page where it differs from the catalogue's name.
_SHOWN = {("sabre", "U"): "User Select/Original Setting"}


class EditorError(Exception):
    """The editor did something other than expected. The game is mid-reset and
    has to be restored."""


def page_rows(screen: str) -> dict:
    """{label: value} for the editor page on `screen`; {} if none is showing."""
    lines = screen.splitlines()
    if not lines or EDITOR not in screen or FOOTER not in screen:
        return {}
    rows = {}
    for line in lines:
        if EDITOR in line or FOOTER in line:
            continue
        m = _ROW.match(line)
        if m:
            rows[m.group("label")] = m.group("value")
    return rows


def shown(field, settings: dict) -> str:
    """How the editor should show `field` once `settings` are in."""
    v = settings[field.id]
    if field.kind == NUMBER:
        return str(v)
    if field.kind == TOGGLE:
        return "Enabled" if v else "Disabled"
    if field.kind == DATE:
        d = date.fromisoformat(v)
        return f"{d.month:02d}/{d.day:02d}/{d.year:04d}"
    if field.id == "sabre" and v == "C":
        return f"Constant Setting Of {settings['sabre_dial']}"
    return _SHOWN.get((field.id, v)) or dict(field.choices)[v]


def matches(field, settings: dict, value: Optional[str]) -> bool:
    if value is None:
        return False
    if field.kind == DATE:
        # The page shows the time as well: "10/14/2026  08:26:04".
        return value.split()[:1] == [shown(field, settings)]
    return value == shown(field, settings)


def _topic(screen: str) -> Optional[str]:
    for m in _TOPIC.finditer(screen):
        if "Configuration Help Information" not in m.group("topic"):
            return m.group("topic").strip()
    return None


def _same_topic(a: str, b: str) -> bool:
    return " ".join(a.split()).casefold() == " ".join(b.split()).casefold()


def _last_line(screen: str) -> str:
    for line in reversed(screen.splitlines()):
        if line.strip():
            return line.rstrip()
    return ""


class EditorDriver:
    """Drives one RESET session: wipe, edit, check, save, league-wide.

    `session` is an sr_harness DosSession, or anything with its `pump`,
    `screen_text`, `send` and `closed`. `wanted` must already have passed
    drafts.validate(); `start_date` None means the day of the reset.
    """

    def __init__(self, session, game_type: str, wanted: dict, today: date,
                 log: Callable[[str], None] = lambda line: None,
                 step_timeout: float = 30.0, start_timeout: float = 180.0,
                 key_gap: float = 0.15):
        self.s = session
        self.game_type = game_type
        self.fields = fields_for(game_type)
        self.wanted = dict(wanted)
        if not self.wanted.get("start_date"):
            self.wanted["start_date"] = today.isoformat()
        self.log = log
        self.step_timeout = step_timeout
        self.start_timeout = start_timeout
        self.key_gap = key_gap
        self.stage = "starting"

    # ── the screen ────────────────────────────────────────────────────────
    @property
    def screen(self) -> str:
        return self.s.screen_text()

    def _wait(self, what: str, test, timeout: Optional[float] = None):
        """Pump until test(screen) is truthy and return it, or raise."""
        deadline = time.time() + (timeout or self.step_timeout)
        while True:
            self.s.pump(0.3)
            got = test(self.screen)
            if got:
                return got
            if self.s.closed:
                raise EditorError(f"the game exited while waiting for {what}")
            if time.time() > deadline:
                raise EditorError(f"timed out waiting for {what}; the screen ends "
                                  f"{_last_line(self.screen)!r}")

    def _press(self, keys: str, note: Optional[str] = None):
        if note:
            self.log(note)
        self.s.send(keys)
        time.sleep(self.key_gap)
        self.s.pump(0.1)

    def _page(self, number: int) -> dict:
        """Wait for page `number` of the editor and return its rows."""
        nav = "[PG-DN]" if number == 1 else "[PG-UP]"

        def ready(screen):
            if nav not in screen:
                return None
            rows = page_rows(screen)
            labels = [f.label for f in self._rows(number)]
            return rows if all(l in rows for l in labels) else None
        return self._wait(f"page {number} of the editor", ready)

    def _rows(self, page: int) -> list:
        """The fields with a row on `page`, top to bottom. Sabre's dial has none:
        it is shown in Sabre's row."""
        return [f for f in self.fields if f.page == page and f.help_title]

    # ── the walk ──────────────────────────────────────────────────────────
    def run(self) -> dict:
        """Reset the game with `wanted`. Returns what the editor showed for each
        field after the read-back. Raises EditorError on anything unexpected,
        leaving the game half-reset: the caller kills the session and restores."""
        self.stage = "confirm"
        self._wait("the reset question", lambda s: _ASK_RESET.search(s),
                   self.start_timeout)
        self._press("Y", "reset the Game? Y (the game is wiped from here on)")

        self.stage = "editor"
        for page in (1, 2):
            if page == 2:
                self._press(PGDN)
            rows = self._page(page)
            cursor = 0
            for index, field in enumerate(self._rows(page)):
                if matches(field, self.wanted, rows.get(field.label)):
                    continue
                self._move(cursor, index)
                cursor = index
                rows = self._edit(page, field)

        self.stage = "readback"
        readback = self.read_back()

        self.stage = "save"
        self._save()
        return readback

    def _move(self, frm: int, to: int):
        key = DOWN if to > frm else UP
        for _ in range(abs(to - frm)):
            self._press(key)

    def _edit(self, page: int, field) -> dict:
        v = self.wanted[field.id]
        self._press("\r")
        topic = self._wait(f"the help for {field.label}", _topic)
        if not _same_topic(topic, field.help_title):
            raise EditorError(f"expected the help for {field.label} "
                              f"({field.help_title!r}) but the editor opened {topic!r}")

        if field.kind == NUMBER:
            self._wait(f"{field.label}'s prompt",
                       lambda s: _NUMBER_PROMPT.search(_last_line(s)))
            self._press(f"{v}\r", f"{field.label}: {v}")
        elif field.kind == CHOICE:
            self._wait(f"{field.label}'s prompt",
                       lambda s: _CHOICE_PROMPT.search(_last_line(s)))
            self._press(v, f"{field.label}: {v}")
            if field.id == "sabre" and v == "C":
                dial = self.wanted["sabre_dial"]
                self._wait("the Sabre dial's prompt",
                           lambda s: _DIAL_PROMPT.search(_last_line(s)))
                self._press(f"{dial}\r", f"Sabre Constant Setting: {dial}")
        elif field.kind == TOGGLE:
            self._wait(f"{field.label} to toggle", lambda s: _TOGGLED.search(s))
            self._press("\r", f"{field.label}: toggled")
        elif field.kind == DATE:
            d = date.fromisoformat(v)
            parts = {"Day": d.day, "Month": d.month, "Year": d.year}
            asked = []

            def next_part(screen):
                # Only a part not yet answered: just after Enter, the last line
                # can still be the prompt that was answered, before its echo.
                m = _DATE_PROMPT.match(_last_line(screen))
                return m if m and m.group("part") not in asked else None
            while len(asked) < 3:
                part = self._wait(f"{field.label}'s next part", next_part).group("part")
                asked.append(part)
                self._press(f"{parts[part]}\r", f"{field.label} {part}: {parts[part]}")
        else:                                                   # pragma: no cover
            raise EditorError(f"no way to answer a {field.kind} field")

        rows = self._wait(f"the editor to come back after {field.label}",
                          lambda s: (r := page_rows(s)) and field.label in r and r)
        if not matches(field, self.wanted, rows.get(field.label)):
            raise EditorError(f"{field.label} reads {rows.get(field.label)!r} after "
                              f"the edit, not {shown(field, self.wanted)!r}")
        return rows

    def read_back(self) -> dict:
        """Both pages, checked field by field against `wanted`."""
        self._press(PGUP)
        got = {}
        for page in (1, 2):
            if page == 2:
                self._press(PGDN)
            rows = self._page(page)
            for field in self._rows(page):
                got[field.id] = rows.get(field.label)
        wrong = [f"{f.label} reads {got[f.id]!r}, not {shown(f, self.wanted)!r}"
                 for p in (1, 2) for f in self._rows(p)
                 if not matches(f, self.wanted, got[f.id])]
        if wrong:
            raise EditorError("the read-back doesn't match the draft: " + "; ".join(wrong))
        self.log("read-back matches the draft on both pages")
        return got

    def _save(self):
        # dosemu takes a lone ESC as the start of an escape sequence, so one
        # press is often swallowed. Press until the editor has gone, and no more:
        # spare ESCs would land on whatever comes next.
        self.log("ESC: save and quit")
        for _ in range(40):
            self.s.send(ESC)
            time.sleep(0.25)
            self.s.pump(0.2)
            if EDITOR not in self.screen or self.s.closed:
                break
        else:
            raise EditorError("the editor didn't close on ESC")
        self.stage = "league-wide"
        self._wait("the league-wide question", lambda s: _ASK_LEAGUE_WIDE.search(s), 60)
        self._press("Y", "league-wide reset? Y")
