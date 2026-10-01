#!/usr/bin/env python3
"""Check or update standalone skill readers from the read-only region in shared.env."""

from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BEGIN = "# BEGIN STANDALONE ENV READER"
END = "# END STANDALONE ENV READER"


def reader_region(text: str) -> str:
    start = text.index(BEGIN)
    return text[start : text.index(END, start) + len(END)]


def mirror_paths(root: Path = ROOT) -> list[Path]:
    return sorted((root / "src/capabilities").glob("*/skill/**/env_config.py"))


def sync(root: Path = ROOT, *, write: bool = False) -> int:
    expected = reader_region((root / "src/shared/env.py").read_text(encoding="utf-8"))
    status = 0
    for path in mirror_paths(root):
        text = path.read_text(encoding="utf-8")
        current = reader_region(text)
        if current == expected:
            continue
        if write:
            path.write_text(text.replace(current, expected, 1), encoding="utf-8")
        else:
            print(f"{path.relative_to(root)}: stale reader; run python3 scripts/sync_env_readers.py --write")
            status = 1
    return status


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="update mirrored regions; otherwise only check")
    args = parser.parse_args()
    return sync(write=args.write)


if __name__ == "__main__":
    raise SystemExit(main())
