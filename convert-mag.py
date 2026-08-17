#!/usr/bin/env python3
"""Convert a legacy quoted-Data Flipper MagSpoof file to track lines."""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys
from typing import Dict, Sequence

from msr import DecodedTrack, format_flipper_mag, write_private


LEGACY_MAG_PATTERN = re.compile(
    r'\AFiletype: Flipper Magspoof device\n'
    r'Version: 1\n'
    r'Data:"(.*)"\n*\Z',
    re.DOTALL,
)


def parse_legacy_mag(content: str) -> Dict[int, DecodedTrack]:
    """Parse tracks from the version-1 quoted ``Data:`` representation."""

    normalized = content.replace("\r\n", "\n").replace("\r", "\n")
    match = LEGACY_MAG_PATTERN.fullmatch(normalized)
    if match is None:
        raise ValueError("input is not a version-1 legacy Flipper MagSpoof file")

    values = match.group(1).split("\n")
    if not values or any(not value for value in values):
        raise ValueError("legacy Data field contains an empty track")

    # Legacy files omit track numbers. A leading '%' identifies Track 1; when
    # it is absent, the first ';' track is treated as Track 2.
    first_number = 1 if values[0].startswith("%") else 2
    if len(values) > 4 - first_number:
        raise ValueError("legacy Data field contains too many tracks")

    tracks: Dict[int, DecodedTrack] = {}
    for offset, value in enumerate(values):
        number = first_number + offset
        expected_sentinel = "%" if number == 1 else ";"
        if not value.startswith(expected_sentinel) or not value.endswith("?"):
            raise ValueError(f"Track {number} has invalid sentinels")
        tracks[number] = DecodedTrack(number, value)
    return tracks


def convert_file(input_path: Path, output_path: Path, *, overwrite: bool = False) -> None:
    """Convert one legacy file without exposing its track contents."""

    content = input_path.read_text(encoding="utf-8")
    tracks = parse_legacy_mag(content)
    converted = format_flipper_mag(tracks)
    write_private(str(output_path), converted, overwrite=overwrite)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert a legacy Flipper MagSpoof .mag file to track lines"
    )
    parser.add_argument("input", type=Path, help="legacy quoted-Data .mag file")
    parser.add_argument("output", type=Path, help="destination .mag file")
    parser.add_argument(
        "--force", action="store_true", help="replace the destination if it exists"
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        convert_file(args.input, args.output, overwrite=args.force)
    except FileExistsError:
        print(
            f"error: {args.output} already exists; use --force to replace it",
            file=sys.stderr,
        )
        return 1
    except (OSError, UnicodeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    print(f"Converted {args.input} to {args.output}.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
