"""Read a BRE v0.988 InterBBS packet, and pull the attack traffic out of it.

The packets were described as encrypted and tamper-proofed. They are neither,
beyond a checksum: every record is plain structured data behind a zero-run
compressor, and "Test Realm" or "v0.988" can be read straight off a hex dump.
Everything below was established by differential capture on the test rig --
attacks sent with 37, 38 and 25 troopers, diffed byte for byte -- and checked
against the game's own `/DETAILED` transcript, whose per-record `Old:`/`Size:`
figures match the lengths decoded here exactly.

    file    = header(12)  record*  0x0F...
    header  = u32, rising over time  +  8 bytes not yet identified
    record  = type u8 | length u16le | src u8 | dst u8 | crc u32le | payload[length]
    crc     = zlib CRC-32 without the final xor, over the *compressed* payload
    payload = 0xFD n -> n zero bytes; any other byte is literal

The 8 unidentified header bytes are not a CRC over any span of the file. They do
not stand between us and the records, so they are left for the memory-capture
route rather than guessed at.

**Why this exists: Missing In Transit.** An individual attack (0x07) carries an
8-byte attack ID. The defender's game answers with an Attack Result (0x08) that
is the original 875-byte record echoed back verbatim with 28 bytes of outcome
appended -- so the ID survives the round trip and an attack can be joined to its
result exactly, however many are in flight. Correlating by timing breaks down in
exactly the busy free-for-all stage when MITs matter most; the ID does not.

The attacker's game declares MIT when no result has arrived within the league's
"Days for Lost Attacks" (default 7). Forces come home, the attack achieves
nothing, and `PROBLEMS.LOG` says `Missing-In-Transit Attack Found to BBS #n`. A
result arriving after that is thrown away -- `Duplicate or Late Attack Return
Recieved - Packet Deleted` -- even though the defender has already taken the hit.
Both reproduced on the rig.

The timestamp in an attack record is also what the attacker's MIT report prints
as `Date:`, to the second. That is the join from what a player saw to the record
the hub carried.

Do not surface unit counts to anyone who also plays. Planets, realm letters, the
ID and the timestamps identify an attack; its strength is hidden game state.
"""
import datetime
import struct
import zlib
from dataclasses import dataclass
from typing import List, Optional

HEADER_SIZE = 12
RECORD_HEADER_SIZE = 9
TRAILER = 0x0F

INDIV_ATTACK = 0x07
ATTACK_RESULT = 0x08

# Names as the game's /DETAILED transcript prints them.
RECORD_TYPES = {
    0x01: "Recon Request",
    0x02: "Recon Update",
    INDIV_ATTACK: "Indiv Attack",
    ATTACK_RESULT: "Attack Results",
    0x0A: "Configupdate",
    0x0D: "Player List",
    0x11: "Dummy Data",
    0x12: "Routing List",
    0x1A: "Time Check",
}

# Fitted, not assumed: three known wall-clock times on the rig decode to the
# second against this epoch. It is not Turbo Pascal's or Delphi's.
_EPOCH = datetime.datetime(1989, 12, 30)

# Offsets into a decompressed 0x07 record (0x08 shares them for its first 875).
ATTACK_SIZE = 875
_ATTACKER = 0          # realm letter on the sending planet
_FROM_PLANET = 1
_TO_PLANET = 2
_TARGET = 7            # realm letter on the target planet
_TROOPERS = 12         # i32; jets/tanks/bombers presumably follow, not yet varied
_STAMP = 859           # 6-byte Real; attack: sender's session start, result: resolved
_NORMAL = 866          # 1 = Normal attack, 0 = Quick Strike (Extended not yet seen)
_ID = 867              # 8 bytes, unique per attack, echoed in the result


class PacketFormatError(ValueError):
    pass


def unrle(payload: bytes) -> bytes:
    out, i = bytearray(), 0
    while i < len(payload):
        if payload[i] == 0xFD:
            if i + 1 >= len(payload):
                raise PacketFormatError("zero-run escape at end of payload")
            out += bytes(payload[i + 1])
            i += 2
        else:
            out.append(payload[i])
            i += 1
    return bytes(out)


def real48(raw: bytes) -> float:
    """Turbo Pascal's 6-byte Real: exponent byte, then 39-bit mantissa and sign."""
    if raw[0] == 0:
        return 0.0
    mantissa = int.from_bytes(raw[1:6], "little")
    sign, mantissa = mantissa >> 39, mantissa & ((1 << 39) - 1)
    return (-1) ** sign * (1 + mantissa / 2 ** 39) * 2.0 ** (raw[0] - 129)


def timestamp(raw: bytes) -> Optional[datetime.datetime]:
    days = real48(raw)
    return _EPOCH + datetime.timedelta(days=days) if days else None


def record_crc(payload: bytes) -> bytes:
    return (zlib.crc32(payload) ^ 0xFFFFFFFF).to_bytes(4, "little")


@dataclass
class Record:
    type: int
    src: int
    dst: int
    crc_ok: bool
    data: bytes          # decompressed

    @property
    def name(self) -> str:
        return RECORD_TYPES.get(self.type, f"type {self.type:#04x}")


def parse(packet: bytes) -> List[Record]:
    if len(packet) < HEADER_SIZE:
        raise PacketFormatError(f"{len(packet)} bytes is shorter than the header")
    records, i = [], HEADER_SIZE
    while i < len(packet):
        if all(b == TRAILER for b in packet[i:]):
            break
        if i + RECORD_HEADER_SIZE > len(packet):
            raise PacketFormatError(f"truncated record header at offset {i}")
        rtype = packet[i]
        (length,) = struct.unpack_from("<H", packet, i + 1)
        src, dst = packet[i + 3], packet[i + 4]
        crc = packet[i + 5:i + 9]
        payload = packet[i + 9:i + 9 + length]
        if len(payload) != length:
            raise PacketFormatError(f"record at offset {i} runs past the end")
        records.append(Record(rtype, src, dst, record_crc(payload) == crc,
                              unrle(payload)))
        i += RECORD_HEADER_SIZE + length
    return records


@dataclass
class Attack:
    """The part of an attack that identifies it -- deliberately not its strength."""
    attack_id: str
    is_result: bool
    from_planet: int
    to_planet: int
    attacker: str
    target: str
    attack_type: str
    stamp: Optional[datetime.datetime]


def attack(record: Record) -> Attack:
    d = record.data
    if record.type not in (INDIV_ATTACK, ATTACK_RESULT) or len(d) < ATTACK_SIZE:
        raise PacketFormatError(f"{record.name} is not an individual attack")
    return Attack(
        attack_id=d[_ID:_ID + 8].hex(),
        is_result=record.type == ATTACK_RESULT,
        from_planet=d[_FROM_PLANET],
        to_planet=d[_TO_PLANET],
        attacker=chr(d[_ATTACKER]),
        target=chr(d[_TARGET]),
        attack_type="Normal" if d[_NORMAL] else "Quick Strike",
        stamp=timestamp(d[_STAMP:_STAMP + 6]),
    )


def troopers(record: Record) -> int:
    """Kept apart from `attack()` on purpose: this is hidden game state."""
    return struct.unpack_from("<i", record.data, _TROOPERS)[0]


def attacks(packet: bytes) -> List[Attack]:
    return [attack(r) for r in parse(packet)
            if r.type in (INDIV_ATTACK, ATTACK_RESULT)]


# ── league settings ───────────────────────────────────────────────────────
# The League Coordinator's editor settings travel as a Configupdate, a run of
# u16 words. Located by changing them in BRE EDITOR on the rig (protection
# 20 -> 0, attacks/day 1 -> 10, lost-attack days 7 -> 1) and diffing the record.
CONFIG_UPDATE = 0x0A


@dataclass
class LeagueSettings:
    game_started_at: Optional[datetime.datetime]
    protection_turns: int
    indiv_attacks_per_day: int
    lost_attack_days: int      # the MIT window: no result by then, forces come home


def league_settings(record: Record) -> LeagueSettings:
    d = record.data
    if record.type != CONFIG_UPDATE or len(d) < 34:
        raise PacketFormatError(f"{record.name} is not a Configupdate")
    w = struct.unpack_from("<17H", d, 0)
    try:
        started = datetime.datetime(w[0], w[1], w[2], w[3], w[4], w[5])
    except ValueError:
        started = None
    return LeagueSettings(started, w[8], w[12], w[16])


if __name__ == "__main__":
    import sys
    for path in sys.argv[1:]:
        print(path)
        for rec in parse(open(path, "rb").read()):
            line = (f"  {rec.name:15} {rec.src:>3}->{rec.dst:<3} {len(rec.data):5}B "
                    f"crc={'ok' if rec.crc_ok else 'BAD'}")
            if rec.type in (INDIV_ATTACK, ATTACK_RESULT):
                a = attack(rec)
                line += (f"  id={a.attack_id} {a.from_planet}{a.attacker}->"
                         f"{a.to_planet}{a.target} {a.attack_type} {a.stamp}")
            print(line)
