#!/usr/bin/env python3
"""Capture one card and export validated tracks for MagSpoof."""

from __future__ import annotations

import argparse
import sys

from msr import (
    DEFAULT_BPI,
    DecodeError,
    MSRDevice,
    MSRError,
    decode_card_partial,
    format_flipper_legacy_mag,
    format_flipper_mag,
    format_json,
    format_magspoof,
    identify_service_codes,
    service_codes_consistent,
    write_private,
)


def parse_bpi(value: str) -> dict[int, int]:
    """Parse Track 1/2/3 densities from a comma-separated CLI value."""

    try:
        densities = [int(item.strip()) for item in value.split(",")]
    except ValueError as error:
        raise argparse.ArgumentTypeError("BPI must be three comma-separated numbers") from error
    if len(densities) != 3 or any(density not in (75, 210) for density in densities):
        raise argparse.ArgumentTypeError("BPI must be three values, each 75 or 210")
    return {number: densities[number - 1] for number in (1, 2, 3)}


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
        choices=("flipper", "flipper-legacy", "magspoof", "json"),
        help="output format (default: inferred from .mag/.json, otherwise magspoof)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="seconds to wait for a swipe (default: 30)",
    )
    parser.add_argument(
        "--read-mode",
        choices=("iso", "raw"),
        default="raw",
        help="reader decoding mode (default: raw; iso uses firmware decoding)",
    )
    parser.add_argument(
        "--bpi",
        type=parse_bpi,
        default=dict(DEFAULT_BPI),
        metavar="T1,T2,T3",
        help="raw track densities to save (default: 210,75,210)",
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

    output_format = args.format
    if output_format is None:
        lowered_output = args.output.lower()
        if lowered_output.endswith(".mag"):
            output_format = "flipper"
        elif lowered_output.endswith(".json"):
            output_format = "json"
        else:
            output_format = "magspoof"

    try:
        print("Reader ready; swipe one card...", file=sys.stderr)
        raw_card = None
        decode_errors = {}
        with MSRDevice() as device:
            if args.read_mode == "raw":
                raw_card = device.capture_raw_card(args.timeout)
                tracks, decode_errors = decode_card_partial(raw_card)
            else:
                tracks = device.capture_iso(args.timeout)
        if output_format != "json" and decode_errors:
            first_number = min(decode_errors)
            raise DecodeError(decode_errors[first_number])
        service_codes = identify_service_codes(tracks)
        formatters = {
            "flipper": format_flipper_mag,
            "flipper-legacy": format_flipper_legacy_mag,
            "magspoof": format_magspoof,
            "json": format_json,
        }
        content = (
            format_json(
                tracks,
                raw_card=raw_card,
                bpi=args.bpi,
                decode_errors=decode_errors,
            )
            if output_format == "json"
            else formatters[output_format](tracks)
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
    except (MSRError, OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    present_tracks = (
        [number for number, raw in raw_card.tracks.items() if raw]
        if raw_card is not None
        else sorted(tracks)
    )
    present = ", ".join(str(number) for number in present_tracks)
    print(f"Recorded track(s) {present} in {args.output!r}.", file=sys.stderr)
    for number, track in sorted(tracks.items()):
        if track.direction == "reverse":
            print(f"Track {number} decoded in reverse direction.", file=sys.stderr)
    for number in sorted(decode_errors):
        print(
            f"Track {number} was preserved as raw data but did not decode as ISO.",
            file=sys.stderr,
        )
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
