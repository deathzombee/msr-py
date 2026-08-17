#!/usr/bin/env python3
"""Erase selected tracks from an authorized test card."""

from __future__ import annotations

import argparse
import sys
from typing import Sequence

from msr import MSRDevice, MSRError


def track_selection(value: str) -> tuple[int, ...]:
    if not value or any(character not in "123" for character in value):
        raise argparse.ArgumentTypeError("tracks must be a combination of 1, 2, and 3")
    if len(set(value)) != len(value):
        raise argparse.ArgumentTypeError("tracks must not contain duplicates")
    return tuple(sorted(int(character) for character in value))


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Erase selected tracks from an authorized test card"
    )
    parser.add_argument(
        "--tracks",
        type=track_selection,
        default=(1, 2, 3),
        help="tracks to erase (default: 123; examples: 1, 23, 123)",
    )
    parser.add_argument(
        "--coercivity",
        choices=("high", "low"),
        required=True,
        help="coercivity printed on the test card (HiCo or LoCo)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="seconds allowed for the swipe (default: 30)",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.timeout <= 0:
        print("error: --timeout must be greater than zero", file=sys.stderr)
        return 2

    selected = ", ".join(str(number) for number in args.tracks)
    try:
        with MSRDevice() as device:
            device.set_coercivity(args.coercivity)
            print(
                f"Ready to erase track(s) {selected} on the test card; swipe it now...",
                file=sys.stderr,
            )
            device.erase(args.tracks, args.timeout)
    except KeyboardInterrupt:
        print("\nErase cancelled.", file=sys.stderr)
        return 130
    except (MSRError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    print(f"Erased track(s) {selected}.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
