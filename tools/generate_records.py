#!/usr/bin/env python3
"""Generate kilix-license records from the pinned determinations JSON.

Never retype licence text. --check refuses a hand-edited committed record and
a missing quote text, and writes nothing.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from kilix_license.errors import HandEditedRecord  # noqa: E402
from kilix_license.generate import (  # noqa: E402
    RECORDS_DIRNAME,
    TEXTS_DIRNAME,
    check_quote_texts,
    check_records,
    data_dir,
    generate_records,
    load_determinations,
    write_quote_texts,
    write_records,
)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="refuse if committed records differ from generator output",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=ROOT,
        help="repository root (default: this clone)",
    )
    args = parser.parse_args(argv[1:])
    if args.root.resolve() == ROOT.resolve():
        directory = data_dir(None)
    else:
        directory = data_dir(args.root)
    _data, payload, pin = load_determinations(directory)
    texts = directory / TEXTS_DIRNAME
    records_path = directory / RECORDS_DIRNAME
    if args.check:
        # Read-only (LIC3-3): a missing or changed quote text fails; it is never written.
        check_quote_texts(payload, texts)
        records = generate_records(payload, pin=pin, texts_dir=texts)
        check_records(records, records_path)
        sys.stdout.write(f"records {len(records)} match generator (pin {pin})\n")
        return 0
    write_quote_texts(payload, texts)
    records = generate_records(payload, pin=pin, texts_dir=texts)
    write_records(records, records_path)
    sys.stdout.write(f"wrote {len(records)} records (pin {pin})\n")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv))
    except HandEditedRecord as exc:
        sys.stderr.write(f"{exc}\n")
        raise SystemExit(1)
