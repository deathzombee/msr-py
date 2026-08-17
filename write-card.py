#!/usr/bin/env python3
"""Write an authorized JSON capture to a test card and verify it."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Sequence

from msr import (
    MSRDevice,
    MSRError,
    compare_raw_tracks,
    compare_track_text,
    encode_raw_write_message,
    load_capture,
)


def parse_bpi(value: str) -> dict[int, int]:
    try:
        densities = [int(item.strip()) for item in value.split(",")]
    except ValueError as error:
        raise argparse.ArgumentTypeError("BPI must be three comma-separated numbers") from error
    if len(densities) != 3 or any(density not in (75, 210) for density in densities):
        raise argparse.ArgumentTypeError("BPI must be three values, each 75 or 210")
    return {number: densities[number - 1] for number in (1, 2, 3)}


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Write an authorized MSR JSON capture to a test card and verify it"
    )
    parser.add_argument("input", type=Path, help="JSON capture created by msr-cmd.py")
    parser.add_argument(
        "--coercivity",
        choices=("high", "low"),
        required=True,
        help="coercivity printed on the test card (HiCo or LoCo)",
    )
    parser.add_argument(
        "--mode",
        choices=("auto", "iso", "raw"),
        default="auto",
        help="write logical ISO or captured raw data (default: raw when available)",
    )
    parser.add_argument(
        "--bpi",
        type=parse_bpi,
        metavar="T1,T2,T3",
        help="override saved raw densities; each value must be 75 or 210",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="seconds allowed for each swipe (default: 30)",
    )
    parser.add_argument(
        "--erase-first",
        action="store_true",
        help="erase all three tracks with a separate swipe before writing",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.timeout <= 0:
        print("error: --timeout must be greater than zero", file=sys.stderr)
        return 2

    try:
        capture = load_capture(args.input)
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    mode = args.mode
    if mode == "auto":
        mode = "raw" if capture.raw_tracks else "iso"
    if mode == "raw" and not capture.raw_tracks:
        print("error: input capture does not contain raw track data", file=sys.stderr)
        return 2
    if mode == "iso" and not capture.tracks:
        print("error: input capture does not contain decoded ISO tracks", file=sys.stderr)
        return 2
    if mode == "raw":
        try:
            encode_raw_write_message(capture.raw_tracks)
        except ValueError as error:
            print(f"error: {error}", file=sys.stderr)
            return 2

    source = capture.raw_tracks if mode == "raw" else capture.tracks
    present = ", ".join(str(number) for number in sorted(source))
    densities = args.bpi or capture.bpi
    try:
        with MSRDevice() as device:
            device.set_coercivity(args.coercivity)
            if mode == "raw":
                # Configure before asking for a card so a configuration error
                # cannot be mistaken for a missed erase/write swipe.
                device.set_bpc(8, 8, 8)
                device.set_bpi_all(densities)
            if args.erase_first:
                print(
                    "Ready to erase all tracks on the test card; swipe it now...",
                    file=sys.stderr,
                )
                device.erase(timeout=args.timeout)
                print("Erase succeeded.", file=sys.stderr)
            print(
                f"Ready to {mode}-write track(s) {present} on a "
                f"{args.coercivity}-coercivity test card; swipe it now...",
                file=sys.stderr,
            )
            if mode == "raw":
                device.write_raw(capture.raw_tracks, args.timeout)
            else:
                device.write_iso(capture.tracks, args.timeout)
            print(
                "Write succeeded. Swipe the same card again to verify...",
                file=sys.stderr,
            )
            read_back = (
                device.capture_raw_card(args.timeout)
                if mode == "raw"
                else device.capture(args.timeout)
            )
    except KeyboardInterrupt:
        print("\nOperation cancelled.", file=sys.stderr)
        return 130
    except (MSRError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    results = (
        compare_raw_tracks(capture.raw_tracks, read_back.tracks)
        if mode == "raw"
        else compare_track_text(capture.tracks, read_back)
    )
    for number in (1, 2, 3):
        print(f"track{number}: {'MATCH' if results[number] else 'DIFFERENT'}")
    all_match = all(results.values())
    print(f"overall: {'MATCH' if all_match else 'DIFFERENT'}")
    return 0 if all_match else 1


if __name__ == "__main__":
    raise SystemExit(main())
