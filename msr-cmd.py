#!/usr/bin/env python3
"""Capture one card and export validated tracks for MagSpoof."""

from __future__ import annotations

import argparse
import sys

from msr import (
    MSRDevice,
    MSRError,
    format_json,
    format_magspoof,
    identify_service_codes,
    service_codes_consistent,
    write_private,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Capture one authorized magnetic-stripe card for MagSpoof"
    )
    parser.add_argument(
        "-o",
        "--output",
        required=True,
        help="output filename, created with owner-only permissions",
    )
    parser.add_argument(
        "--format",
        choices=("magspoof", "json"),
        default="magspoof",
        help="output format (default: magspoof)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="seconds to wait for a swipe (default: 30)",
    )
    parser.add_argument(
        "--force", action="store_true", help="replace an existing output file"
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.timeout <= 0:
        print("error: --timeout must be greater than zero", file=sys.stderr)
        return 2

    try:
        print("Reader ready; swipe one card...", file=sys.stderr)
        with MSRDevice() as device:
            tracks = device.capture(args.timeout)
        service_codes = identify_service_codes(tracks)
        content = (
            format_magspoof(tracks)
            if args.format == "magspoof"
            else format_json(tracks)
        )
        write_private(args.output, content, overwrite=args.force)
    except KeyboardInterrupt:
        print("\nCapture cancelled.", file=sys.stderr)
        return 130
    except FileExistsError:
        print(
            f"error: {args.output!r} already exists; use --force to replace it",
            file=sys.stderr,
        )
        return 1
    except (MSRError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    present = ", ".join(str(number) for number in sorted(tracks))
    print(f"Recorded track(s) {present} in {args.output!r}.", file=sys.stderr)
    if service_codes:
        for number, code in sorted(service_codes.items()):
            classification = "ICC/EMV indicated" if code.icc_emv else "ICC/EMV not indicated"
            print(
                f"Track {number} service code: {code.value} ({classification}).",
                file=sys.stderr,
            )
        if not service_codes_consistent(service_codes):
            print(
                "warning: Track 1 and Track 2 service codes disagree",
                file=sys.stderr,
            )
    else:
        print("No ISO payment-card service code was identified.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
