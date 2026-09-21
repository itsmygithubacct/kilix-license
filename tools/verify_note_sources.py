#!/usr/bin/env python3
"""Re-derive an advisory note's sources from the evidence packets themselves.

LIC5-FIX-VERIFY F3. Two things pin each quoted source inside this repository:
``tests/data/note-sources/<sha256>``, the source file itself, and
``tests/data/note-sources/packet-records/<sha256>.json``, the evidence packet's
own record of that file. Both are in the tree, so both can be forged together
by one seat willing to make three edits agree. Only the packets settle it.

This takes the packets as an argument -- no path is committed -- and checks,
for each declared source:

* the packet file the vendored record came from hashes to the digest that
  record names, which is also the digest the note shows the user;
* re-extracting the named key from that packet file, with the documented path
  rewrite and nothing else, reproduces the vendored bytes exactly;
* the source file in the packets hashes to the digest ADVISORY_TEXT_SOURCES
  declares, and is byte-identical to the vendored fixture;
* every line the note quotes is that file's line, and every such line the
  packet independently records agrees with it.

    tools/verify_note_sources.py --packets ~/research/gpu_terminal

Exit 0 when every check passes; 1 otherwise, with each failure on its own line.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from kilix_license.generate import (  # noqa: E402
    ADVISORY_TEXT_SOURCES,
    ADVISORY_TEXTS,
    data_dir,
    parse_advisory_note,
)

FIXTURES = ROOT / "tests" / "data" / "note-sources"
PACKET_RECORDS = FIXTURES / "packet-records"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _rewrite(path: str, marker: str) -> str:
    return path[path.index(marker):] if marker in path else path


def check(packets: Path, out) -> list[str]:
    failures: list[str] = []

    def bad(message: str) -> None:
        failures.append(message)
        out.write(f"FAIL {message}\n")

    def good(message: str) -> None:
        out.write(f"ok   {message}\n")

    texts = data_dir() / "texts"
    for quote_id, note_digest in sorted(ADVISORY_TEXTS.items()):
        note = (texts / note_digest).read_bytes()
        preamble = note.decode("utf-8")[: note.decode("utf-8").index("quoted from ")]
        _authored, blocks = parse_advisory_note(note, f"advisory note {note_digest}")
        declared = ADVISORY_TEXT_SOURCES[note_digest]
        for source, quoted in zip(declared, blocks):
            claimed, quoted_bytes = quoted[0], quoted[1]
            label = f"{quote_id} {source.path} lines {source.lines}"

            # 1. the source file, from the packets
            upstream = packets / source.path
            if not upstream.is_file():
                bad(f"{label}: no such file under --packets: {upstream}")
                continue
            data = upstream.read_bytes()
            if _sha256(data) != source.sha256:
                bad(f"{label}: packet file hashes {_sha256(data)}, declared {source.sha256}")
                continue
            good(f"{label}: packet file matches the declared digest")
            fixture = FIXTURES / source.sha256
            if not fixture.is_file() or fixture.read_bytes() != data:
                bad(f"{label}: vendored fixture is not the packet's bytes")
            else:
                good(f"{label}: vendored fixture is byte-identical to the packet's file")

            # 2. the quoted lines, from the packet file
            lines = data.split(b"\n")
            expected = b"".join(lines[n - 1] + b"\n" for n in claimed.lines)
            if quoted_bytes != expected:
                bad(f"{label}: the note's quoted bytes are not those lines of the packet file")
            else:
                good(f"{label}: every quoted line is that file's bytes")

            # 3. the packet's own record of the file
            record_path = PACKET_RECORDS / f"{source.sha256}.json"
            if not record_path.is_file():
                bad(f"{label}: no vendored packet record for {source.sha256}")
                continue
            record = json.loads(record_path.read_text(encoding="utf-8"))
            origin = record["vendored_from"]
            packet_file = packets / origin["packet"] / origin["file"]
            if not packet_file.is_file():
                bad(f"{label}: no such packet file: {packet_file}")
                continue
            raw = packet_file.read_bytes()
            if _sha256(raw) != origin["sha256"]:
                bad(
                    f"{label}: {origin['packet']}/{origin['file']} hashes "
                    f"{_sha256(raw)}, record names {origin['sha256']}"
                )
                continue
            good(f"{label}: {origin['packet']}/{origin['file']} matches the recorded digest")
            if origin["sha256"] not in preamble:
                bad(f"{label}: the note does not show the user that packet digest")
            else:
                good(f"{label}: the note shows the user that packet digest")

            # 4. the vendored bytes are that key, rewritten as documented
            section, key = origin["key"].split(".", 1)
            obj = json.loads(raw)[section][key]
            marker = source.path.split("/")[0] + "/"
            rebuilt = {
                "vendored_from": origin,
                "path": _rewrite(obj["path"], marker),
                "sha256": obj["sha256"],
                "lines": dict(sorted(obj["lines"].items(), key=lambda kv: int(kv[0]))),
            }
            body = json.dumps(rebuilt, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
            if body.encode("utf-8") != record_path.read_bytes():
                bad(f"{label}: the vendored record is not {origin['key']} rewritten as documented")
            else:
                good(f"{label}: the vendored record re-derives from {origin['key']}")

            # 5. every quoted line the packet independently records
            witnessed = [n for n in claimed.lines if str(n) in record["lines"]]
            for number in witnessed:
                if record["lines"][str(number)] != lines[number - 1].decode("utf-8"):
                    bad(f"{label}: the packet's recorded line {number} differs from the file")
            good(
                f"{label}: {len(witnessed)} of {len(claimed.lines)} quoted lines have a "
                f"second witness in {origin['key']}"
            )
    return failures


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--packets",
        type=Path,
        required=True,
        help="directory holding the licence-evidence-* packets",
    )
    args = parser.parse_args(argv[1:])
    failures = check(args.packets.resolve(), sys.stdout)
    sys.stdout.write(
        f"\n{len(failures)} failures\n" if failures else "\nevery check passed\n"
    )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
