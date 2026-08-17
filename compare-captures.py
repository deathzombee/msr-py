#!/usr/bin/env python3
"""Compare two MSR JSON captures without displaying sensitive track data."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Dict, Tuple


TRACK_NAMES = ("track1", "track2", "track3")


def load_capture(path: Path) -> Dict[str, Any]:
    try:
        with path.open(encoding="utf-8") as capture_file:
            capture = json.load(capture_file)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read {path}: {error}") from error

    if not isinstance(capture, dict):
        raise ValueError(f"{path} does not contain a JSON object")
    for name in TRACK_NAMES:
        value = capture.get(name)
        if value is not None and not isinstance(value, str):
            raise ValueError(f"{path}: {name} must be a string or null")
    return capture


def compare_captures(
    original: Dict[str, Any], replay: Dict[str, Any]
) -> Tuple[Dict[str, bool], bool]:
    track_results = {
        name: original.get(name) == replay.get(name) for name in TRACK_NAMES
    }
    service_codes_match = original.get("service_codes") == replay.get(
        "service_codes"
    )
    return track_results, service_codes_match


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare an original-card capture with a MagSpoof read-back"
    )
    parser.add_argument("original", type=Path, help="original card JSON capture")
    parser.add_argument("replay", type=Path, help="MagSpoof read-back JSON capture")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        original = load_capture(args.original)
        replay = load_capture(args.replay)
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    track_results, service_codes_match = compare_captures(original, replay)
    for name in TRACK_NAMES:
        label = "MATCH" if track_results[name] else "DIFFERENT"
        print(f"{name}: {label}")
    print(
        "service codes: " + ("MATCH" if service_codes_match else "DIFFERENT")
    )

    all_match = all(track_results.values()) and service_codes_match
    print("overall: " + ("MATCH" if all_match else "DIFFERENT"))
    return 0 if all_match else 1


if __name__ == "__main__":
    raise SystemExit(main())
