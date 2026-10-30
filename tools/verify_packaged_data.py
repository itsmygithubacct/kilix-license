"""Check installed wheel data without importing the source checkout."""

from pathlib import Path

from kilix_license.catalog import load_determined_records
from kilix_license.generate import DATA_DIR


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    source = root / "src" / "kilix_license" / "data"
    installed = DATA_DIR.resolve()
    if installed.is_relative_to(root):
        raise SystemExit("packaging check imported the source checkout; use isolated Python")
    files = sorted(path for path in source.rglob("*") if path.is_file())
    if not files:
        raise SystemExit("packaging check has no source data to compare")
    for path in files:
        relative = path.relative_to(source)
        target = installed / relative
        if not target.is_file():
            raise SystemExit(f"installed wheel is missing data/{relative}")
        if target.read_bytes() != path.read_bytes():
            raise SystemExit(f"installed wheel differs at data/{relative}")
    expected = {record.id: record.digest for record in load_determined_records(root)}
    actual = {record.id: record.digest for record in load_determined_records()}
    if actual != expected:
        raise SystemExit("installed wheel licence catalog differs from source")
    print(f"installed wheel data: {len(files)} files and {len(actual)} records verified")


if __name__ == "__main__":
    main()
