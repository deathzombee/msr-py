"""MSR605/MSRx6 USB capture, raw-track decoding, and MagSpoof export."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import time
from typing import Dict, Iterable, Mapping, Optional, Union

try:
    import usb.core
    import usb.util
except ImportError:  # Pure protocol/decoder functions remain usable without PyUSB.
    usb = None


ESC = 0x1B
FS = 0x1C
END_SENTINEL = 0x3F
BAD_TRACK = 0x2A
EMPTY_TRACK = 0x2B
OK_STATUS = 0x30

VENDOR_ID = 0x0801
PRODUCT_ID = 0x0003

# The HID wrapper's low six bits are its payload length. The two high bits
# indicate the first and final report in a message.
HID_FIRST = 0x80
HID_FINAL = 0x40
HID_LENGTH_MASK = 0x3F

READ_RAW_COMMAND = bytes((0xC5, ESC, 0x6D))
READ_ISO_COMMAND = bytes((0xC5, ESC, 0x72))
RESET_COMMAND = bytes((0xC2, ESC, 0x61))
SET_HICO_COMMAND = bytes((0xC2, ESC, 0x78))
SET_LOCO_COMMAND = bytes((0xC2, ESC, 0x79))
ERASE_COMMAND_PREFIX = bytes((0xC5, ESC, 0x63))
SET_BPI_COMMAND_PREFIX = bytes((ESC, 0x62))
SET_BPC_COMMAND_PREFIX = bytes((ESC, 0x6F))

CAPTURE_SCHEMA = "msr-py.capture"
CAPTURE_VERSION = 2
RAW_READ_REPRESENTATION = "msrx6-raw-read-v1"
DEFAULT_BPI = {1: 210, 2: 75, 3: 210}

# The MSR605 protocol uses device-specific selector bytes rather than sending
# the density as a separate track/value pair.
BPI_SELECTOR = {
    (1, 75): 0xA0,
    (1, 210): 0xA1,
    (2, 75): 0x4B,
    (2, 210): 0xD2,
    (3, 75): 0xC0,
    (3, 210): 0xC1,
}

TRACK1_ALPHABET = "".join(chr(code) for code in range(32, 96))
TRACK23_ALPHABET = "0123456789:;<=>?"
ISO_TRACK_MAX_LENGTHS = {1: 79, 2: 40, 3: 107}

STATUS_DESCRIPTIONS = {
    0x31: "write or read error",
    0x32: "command format error",
    0x34: "invalid command",
    0x39: "invalid card swipe",
    0x41: "command failed",
}


class MSRError(Exception):
    """Base exception for reader, framing, and decoding errors."""


class ProtocolError(MSRError):
    """The reader returned a malformed HID or MSR protocol message."""


class DecodeError(MSRError):
    """Raw track bits could not be decoded and validated."""


class CardReadError(MSRError):
    """The reader reported an unsuccessful card operation."""


class CardWriteError(MSRError):
    """The writer reported an unsuccessful card operation."""


@dataclass(frozen=True)
class RawCard:
    """One parsed raw-read response."""

    tracks: Dict[int, bytes]
    status: int


@dataclass(frozen=True)
class ISOCard:
    """One parsed ISO-read response before track validation."""

    tracks: Dict[int, str]
    status: int
    bad_tracks: frozenset[int] = field(default_factory=frozenset)


@dataclass(frozen=True)
class DecodedTrack:
    """A parity- and LRC-validated ISO track string."""

    number: int
    text: str
    direction: str = "forward"


@dataclass(frozen=True)
class ServiceCodeInfo:
    """A payment-card service code found in a decoded track."""

    track_number: int
    value: str
    icc_emv: bool


@dataclass(frozen=True)
class CaptureDocument:
    """Logical and raw representations loaded from one JSON capture."""

    tracks: Dict[int, DecodedTrack]
    raw_tracks: Dict[int, bytes]
    bpi: Dict[int, int]
    capture_mode: str


class HIDMessageAssembler:
    """Reassemble one or more 64-byte HID reports into protocol messages."""

    def __init__(self) -> None:
        self._buffer: Optional[bytearray] = None

    def feed(self, report: Iterable[int]) -> Optional[bytes]:
        packet = bytes(report)
        if not packet:
            raise ProtocolError("received an empty HID report")

        header = packet[0]
        payload_length = header & HID_LENGTH_MASK
        if payload_length > len(packet) - 1:
            raise ProtocolError(
                f"HID report declares {payload_length} payload bytes, "
                f"but only {len(packet) - 1} arrived"
            )

        is_first = bool(header & HID_FIRST)
        is_final = bool(header & HID_FINAL)

        if is_first:
            if self._buffer is not None:
                raise ProtocolError("new HID message started before the previous one ended")
            self._buffer = bytearray()
        elif self._buffer is None:
            raise ProtocolError("received a continuation HID report without a start")

        assert self._buffer is not None
        self._buffer.extend(packet[1 : 1 + payload_length])

        if not is_final:
            return None

        message = bytes(self._buffer)
        self._buffer = None
        return message


def frame_hid_message(message: bytes, report_size: int = 64) -> tuple[bytes, ...]:
    """Split one protocol message into padded MSRx6 HID feature reports."""

    if not message:
        raise ValueError("cannot frame an empty HID message")
    if report_size < 2 or report_size > 64:
        raise ValueError("report size must be between 2 and 64 bytes")

    payload_size = report_size - 1
    chunks = [
        message[offset : offset + payload_size]
        for offset in range(0, len(message), payload_size)
    ]
    reports = []
    for index, chunk in enumerate(chunks):
        header = len(chunk)
        if index == 0:
            header |= HID_FIRST
        if index == len(chunks) - 1:
            header |= HID_FINAL
        report = bytes((header,)) + chunk
        reports.append(report + bytes(report_size - len(report)))
    return tuple(reports)


def parse_raw_card(message: bytes) -> RawCard:
    """Parse an MSR raw data block using its track length fields."""

    start = bytes((ESC, 0x73))
    trailer = bytes((END_SENTINEL, FS, ESC))
    if not message.startswith(start):
        raise ProtocolError("raw response does not start with <ESC>s")

    tracks: Dict[int, bytes] = {1: b"", 2: b"", 3: b""}
    position = len(start)
    last_track = 0

    while message[position : position + len(trailer)] != trailer:
        if position + 3 > len(message):
            raise ProtocolError("raw response ended inside a track header")
        if message[position] != ESC or message[position + 1] not in (1, 2, 3):
            raise ProtocolError(f"expected a track marker at byte {position}")

        track_number = message[position + 1]
        if track_number <= last_track:
            raise ProtocolError("track markers are duplicated or out of order")

        raw_length = message[position + 2]
        data_start = position + 3
        data_end = data_start + raw_length
        if data_end > len(message):
            raise ProtocolError(
                f"track {track_number} declares {raw_length} bytes beyond the response"
            )

        tracks[track_number] = message[data_start:data_end]
        last_track = track_number
        position = data_end

    if position + 4 != len(message):
        raise ProtocolError("raw response has missing or unexpected bytes after its trailer")

    return RawCard(tracks=tracks, status=message[position + 3])


def parse_iso_card(message: bytes) -> ISOCard:
    """Parse the reader's sentinel-delimited ISO response."""

    start = bytes((ESC, 0x73))
    ending_field = bytes((END_SENTINEL, FS))
    if not message.startswith(start):
        raise ProtocolError("ISO response does not start with <ESC>s")
    ending_position = message.find(ending_field, len(start))
    if ending_position == -1:
        raise ProtocolError("ISO response has a missing or malformed trailer")

    status_position = message.find(
        bytes((ESC,)), ending_position + len(ending_field)
    )
    if status_position == -1 or status_position + 1 >= len(message):
        raise ProtocolError("ISO response has no status after its ending field")

    # Some MSRx6 firmware includes stale bytes after the first complete
    # response or inserts transport bytes between ?<FS> and <ESC><status>.
    # Track data cannot contain FS, so its first occurrence is unambiguous.
    data_end = ending_position
    status = message[status_position + 1]
    position = len(start)
    last_track = 0
    tracks: Dict[int, str] = {}
    bad_tracks = set()
    while position < data_end:
        if position + 2 > data_end:
            raise ProtocolError("ISO response ended inside a track marker")
        if message[position] != ESC or message[position + 1] not in (1, 2, 3):
            found = message[position : position + 2].hex(" ") or "end of response"
            raise ProtocolError(
                f"expected an ISO track marker at byte {position}; found {found}"
            )

        track_number = message[position + 1]
        if track_number <= last_track:
            raise ProtocolError("ISO track markers are duplicated or out of order")

        data_start = position + 2
        next_marker = message.find(bytes((ESC,)), data_start, data_end)
        data_stop = data_end if next_marker == -1 else next_marker
        raw_text = message[data_start:data_stop]
        if raw_text:
            try:
                tracks[track_number] = raw_text.decode("ascii")
            except UnicodeDecodeError as error:
                raise ProtocolError(
                    f"Track {track_number} contains non-ASCII ISO data"
                ) from error

        last_track = track_number
        position = data_stop
        if next_marker != -1 and next_marker + 1 < data_end:
            field_code = message[next_marker + 1]
            if field_code in (BAD_TRACK, EMPTY_TRACK):
                if raw_text:
                    raise ProtocolError(
                        f"Track {track_number} has data followed by a field status"
                    )
                if field_code == BAD_TRACK:
                    bad_tracks.add(track_number)
                position = next_marker + 2

    return ISOCard(tracks=tracks, status=status, bad_tracks=frozenset(bad_tracks))


def _reverse_bits(value: int, width: int) -> int:
    reversed_value = 0
    for _ in range(width):
        reversed_value = (reversed_value << 1) | (value & 1)
        value >>= 1
    return reversed_value


def decode_raw_track(track_number: int, raw: bytes) -> DecodedTrack:
    """Decode common raw-bit packings and reject bad parity or LRC."""

    if track_number == 1:
        bit_width = 7
        data_width = 6
        alphabet = TRACK1_ALPHABET
        start_sentinel = "%"
    elif track_number in (2, 3):
        bit_width = 5
        data_width = 4
        alphabet = TRACK23_ALPHABET
        start_sentinel = ";"
    else:
        raise ValueError("track number must be 1, 2, or 3")
    if not raw:
        raise DecodeError(f"track {track_number} contains no raw data")

    raw_bitstream = "".join(f"{byte:08b}" for byte in raw)
    byte_reversed = "".join(f"{byte:08b}" for byte in reversed(raw))
    bit_reversed_bytes = "".join(f"{byte:08b}"[::-1] for byte in raw)

    # Reverse playback can reach raw-reader firmware in several equivalent
    # byte/bit packings. Search each packing at every bit alignment, then only
    # accept a candidate that passes sentinel, odd parity, and LRC validation.
    orientations = (
        ("forward", raw_bitstream),
        ("reverse", raw_bitstream[::-1]),
        ("reverse-byte-order", byte_reversed),
        ("reverse-bit-order", bit_reversed_bytes),
    )
    failures = []
    valid_candidates = []
    seen_bitstreams = set()
    for orientation, oriented_bits in orientations:
        if oriented_bits in seen_bitstreams:
            continue
        seen_bitstreams.add(oriented_bits)

        sentinel_offsets = []
        for start_offset in range(len(oriented_bits) - bit_width + 1):
            group = oriented_bits[start_offset : start_offset + bit_width]
            value = int(group[:-1], 2)
            if alphabet[_reverse_bits(value, data_width)] == start_sentinel:
                sentinel_offsets.append(start_offset)

        if not sentinel_offsets:
            failures.append(f"{orientation}: no {start_sentinel!r} sentinel")
            continue

        for start_offset in sentinel_offsets:
            bitstream = oriented_bits[start_offset:]
            groups = [
                bitstream[offset : offset + bit_width]
                for offset in range(0, len(bitstream) - bit_width + 1, bit_width)
            ]
            values = [int(group[:-1], 2) for group in groups]
            characters = [
                alphabet[_reverse_bits(value, data_width)] for value in values
            ]

            try:
                end_index = characters.index("?", 1)
            except ValueError:
                failures.append(f"{orientation}: has no end sentinel")
                continue

            lrc_index = end_index + 1
            if lrc_index >= len(groups):
                failures.append(f"{orientation}: has no LRC character")
                continue

            bad_parity = [
                index
                for index, group in enumerate(groups[: lrc_index + 1])
                if group.count("1") % 2 != 1
            ]
            if bad_parity:
                failures.append(f"{orientation}: bad parity")
                continue

            lrc = 0
            for value in values[: lrc_index + 1]:
                lrc ^= value
            if lrc != 0:
                failures.append(f"{orientation}: failed its LRC check")
                continue

            text = "".join(characters[: end_index + 1])
            direction = "forward" if orientation == "forward" else "reverse"
            valid_candidates.append(
                (len(text), -start_offset, DecodedTrack(track_number, text, direction))
            )

    if valid_candidates:
        # The real start sentinel yields the longest valid track. This also
        # avoids selecting a sentinel-like character inside discretionary data.
        return max(valid_candidates, key=lambda candidate: candidate[:2])[2]

    detail = "; ".join(dict.fromkeys(failures))
    raise DecodeError(f"track {track_number} could not be decoded ({detail})")


def decode_card(card: RawCard) -> Dict[int, DecodedTrack]:
    """Decode every nonempty track in a successful raw-read response."""

    if card.status != OK_STATUS:
        printable = chr(card.status) if 32 <= card.status <= 126 else "?"
        raise CardReadError(
            f"reader returned status 0x{card.status:02x} ({printable!r})"
        )

    decoded = {
        number: decode_raw_track(number, raw)
        for number, raw in card.tracks.items()
        if raw
    }
    if not decoded:
        raise DecodeError("the card did not contain any readable tracks")
    return decoded


def decode_card_partial(
    card: RawCard,
) -> tuple[Dict[int, DecodedTrack], Dict[int, str]]:
    """Decode tracks independently while retaining undecodable raw tracks."""

    if card.status != OK_STATUS:
        printable = chr(card.status) if 32 <= card.status <= 126 else "?"
        raise CardReadError(
            f"reader returned status 0x{card.status:02x} ({printable!r})"
        )

    decoded: Dict[int, DecodedTrack] = {}
    errors: Dict[int, str] = {}
    for number, raw in card.tracks.items():
        if not raw:
            continue
        try:
            decoded[number] = decode_raw_track(number, raw)
        except DecodeError as error:
            errors[number] = str(error)
    if not decoded and not errors:
        raise DecodeError("the card did not contain any readable tracks")
    return decoded, errors


def decode_iso_card(card: ISOCard) -> Dict[int, DecodedTrack]:
    """Validate every track in a successful device-decoded ISO response."""

    if card.status != OK_STATUS:
        printable = chr(card.status) if 32 <= card.status <= 126 else "?"
        raise CardReadError(
            f"reader returned status 0x{card.status:02x} ({printable!r})"
        )
    if card.bad_tracks:
        numbers = ", ".join(str(number) for number in sorted(card.bad_tracks))
        raise CardReadError(f"reader could not decode track(s) {numbers}")

    decoded = {
        number: DecodedTrack(number, text)
        for number, text in card.tracks.items()
    }
    if not decoded:
        raise DecodeError("the card did not contain any readable tracks")
    try:
        return validate_iso_tracks(decoded)
    except ValueError as error:
        raise DecodeError(f"reader returned invalid ISO data ({error})") from error


def identify_service_codes(
    tracks: Dict[int, DecodedTrack],
) -> Dict[int, ServiceCodeInfo]:
    """Locate payment-card service codes without modifying track contents."""

    found: Dict[int, ServiceCodeInfo] = {}
    for number in (1, 2):
        track = tracks.get(number)
        if track is None:
            continue

        if number == 1:
            fields = track.text.split("^")
            if not track.text.startswith("%B") or len(fields) < 3:
                continue
            expiry_and_service = fields[2]
        else:
            if not track.text.startswith(";") or "=" not in track.text:
                continue
            expiry_and_service = track.text.split("=", 1)[1]

        if len(expiry_and_service) < 7:
            continue
        value = expiry_and_service[4:7]
        if not value.isdigit():
            continue

        found[number] = ServiceCodeInfo(
            track_number=number,
            value=value,
            icc_emv=value[0] in ("2", "6"),
        )
    return found


def service_codes_consistent(codes: Dict[int, ServiceCodeInfo]) -> bool:
    """Return whether all service codes found across tracks agree."""

    return len({code.value for code in codes.values()}) <= 1


def validate_iso_tracks(
    tracks: Mapping[int, DecodedTrack],
) -> Dict[int, DecodedTrack]:
    """Validate logical ISO tracks before allowing them near the write head."""

    if not tracks:
        raise ValueError("at least one track is required")

    validated: Dict[int, DecodedTrack] = {}
    for number, track in tracks.items():
        if number not in (1, 2, 3):
            raise ValueError(f"invalid track number {number!r}")
        if not isinstance(track, DecodedTrack) or track.number != number:
            raise ValueError(f"Track {number} has inconsistent metadata")

        text = track.text
        start_sentinel = "%" if number == 1 else ";"
        if not text.startswith(start_sentinel) or not text.endswith("?"):
            raise ValueError(
                f"Track {number} must start with {start_sentinel!r} and end with '?'"
            )
        if text.count("?") != 1:
            raise ValueError(f"Track {number} contains an embedded end sentinel")

        alphabet = TRACK1_ALPHABET if number == 1 else TRACK23_ALPHABET
        invalid = sorted(set(text) - set(alphabet))
        if invalid:
            raise ValueError(f"Track {number} contains characters outside its ISO alphabet")
        if len(text) > ISO_TRACK_MAX_LENGTHS[number]:
            raise ValueError(
                f"Track {number} is {len(text)} characters; "
                f"the ISO limit is {ISO_TRACK_MAX_LENGTHS[number]}"
            )
        validated[number] = track
    return validated


def encode_iso_write_message(tracks: Mapping[int, DecodedTrack]) -> bytes:
    """Build the MSR605 ISO-write command from validated logical tracks."""

    validated = validate_iso_tracks(tracks)
    message = bytearray((ESC, 0x77, ESC, 0x73))
    for number in (1, 2, 3):
        message.extend((ESC, number))
        if number in validated:
            # The writer generates ISO start/end sentinels, parity, and LRC.
            message.extend(validated[number].text[1:-1].encode("ascii"))
    message.extend((END_SENTINEL, FS))
    return bytes(message)


def raw_read_to_write(raw: bytes) -> bytes:
    """Convert an MSRx6 raw-read field into its raw-write byte orientation."""

    if len(raw) < 2:
        raise ValueError(
            "an MSRx6 raw-read track must include data and its trailing packing byte"
        )
    # Raw reads include one final packing byte that raw writes do not accept.
    # The bit order within every preceding byte is reversed between commands.
    return bytes(_reverse_bits(value, 8) for value in raw[:-1])


def encode_raw_write_message(tracks: Mapping[int, bytes]) -> bytes:
    """Build a raw-write command from tracks in MSRx6 raw-read form."""

    invalid = set(tracks) - {1, 2, 3}
    if invalid:
        raise ValueError(f"invalid raw track number {min(invalid)!r}")
    if not any(tracks.get(number) for number in (1, 2, 3)):
        raise ValueError("at least one raw track is required")

    message = bytearray((ESC, 0x6E, ESC, 0x73))
    for number in (1, 2, 3):
        raw = tracks.get(number, b"")
        encoded = raw_read_to_write(raw) if raw else b""
        if len(encoded) > 255:
            raise ValueError(f"Track {number} exceeds the raw-write 255-byte limit")
        message.extend((ESC, number, len(encoded)))
        message.extend(encoded)
    message.extend((END_SENTINEL, FS))
    return bytes(message)


def parse_status_response(
    message: bytes,
    operation: str,
    expected_trailing: Optional[bytes] = None,
) -> int:
    """Validate one ``<ESC><status>`` response and raise on failure."""

    if len(message) < 2 or message[0] != ESC:
        raise ProtocolError(f"malformed {operation} status response")
    status = message[1]
    if status != OK_STATUS:
        description = STATUS_DESCRIPTIONS.get(status, "unknown reader error")
        raise CardWriteError(
            f"{operation} failed with status 0x{status:02x} ({description})"
        )
    trailing = message[2:]
    if expected_trailing is None:
        if trailing:
            raise ProtocolError(f"malformed {operation} status response")
    elif trailing and trailing != expected_trailing:
        raise ProtocolError(f"{operation} returned unexpected configuration data")
    return status


def load_capture(path: Union[str, os.PathLike[str]]) -> CaptureDocument:
    """Load a legacy logical or version-2 logical/raw JSON capture."""

    input_path = Path(path)
    try:
        with input_path.open(encoding="utf-8") as input_file:
            document = json.load(input_file)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read {input_path}: {error}") from error

    if not isinstance(document, dict):
        raise ValueError(f"{input_path} does not contain a JSON object")

    tracks: Dict[int, DecodedTrack] = {}
    for number in (1, 2, 3):
        name = f"track{number}"
        value = document.get(name)
        if value is None:
            continue
        if not isinstance(value, str):
            raise ValueError(f"{input_path}: {name} must be a string or null")
        tracks[number] = DecodedTrack(number, value)

    if tracks:
        try:
            tracks = validate_iso_tracks(tracks)
        except ValueError as error:
            raise ValueError(f"{input_path}: {error}") from error

    raw_tracks: Dict[int, bytes] = {}
    bpi = dict(DEFAULT_BPI)
    raw_section = document.get("raw")
    if raw_section is not None:
        if document.get("schema") != CAPTURE_SCHEMA:
            raise ValueError(f"{input_path}: raw data has an unknown capture schema")
        if document.get("version") != CAPTURE_VERSION:
            raise ValueError(
                f"{input_path}: unsupported capture version {document.get('version')!r}"
            )
        if not isinstance(raw_section, dict):
            raise ValueError(f"{input_path}: raw must be an object")
        if raw_section.get("representation") != RAW_READ_REPRESENTATION:
            raise ValueError(f"{input_path}: unsupported raw representation")

        raw_values = raw_section.get("tracks")
        if not isinstance(raw_values, dict):
            raise ValueError(f"{input_path}: raw.tracks must be an object")
        for number in (1, 2, 3):
            name = f"track{number}"
            value = raw_values.get(name)
            if value is None:
                continue
            if not isinstance(value, str):
                raise ValueError(f"{input_path}: raw.tracks.{name} must be hex or null")
            try:
                raw = bytes.fromhex(value)
            except ValueError as error:
                raise ValueError(
                    f"{input_path}: raw.tracks.{name} is not valid hex"
                ) from error
            if not raw:
                raise ValueError(f"{input_path}: raw.tracks.{name} must not be empty")
            if len(raw) > 256:
                raise ValueError(f"{input_path}: raw.tracks.{name} is too long")
            raw_tracks[number] = raw

        bpi_values = raw_section.get("bpi")
        if not isinstance(bpi_values, dict):
            raise ValueError(f"{input_path}: raw.bpi must be an object")
        for number in (1, 2, 3):
            name = f"track{number}"
            value = bpi_values.get(name)
            if value not in (75, 210):
                raise ValueError(f"{input_path}: raw.bpi.{name} must be 75 or 210")
            bpi[number] = value

    if not tracks and not raw_tracks:
        raise ValueError(f"{input_path}: at least one logical or raw track is required")

    capture_mode = document.get("capture_mode", "raw" if raw_tracks else "iso")
    if capture_mode not in ("iso", "raw"):
        raise ValueError(f"{input_path}: capture_mode must be 'iso' or 'raw'")
    return CaptureDocument(tracks, raw_tracks, bpi, capture_mode)


def load_json_tracks(path: Union[str, os.PathLike[str]]) -> Dict[int, DecodedTrack]:
    """Load and validate logical ISO tracks from a JSON capture."""

    capture = load_capture(path)
    if not capture.tracks:
        raise ValueError(f"{Path(path)}: capture has no decoded ISO tracks")
    return capture.tracks


def compare_track_text(
    expected: Mapping[int, DecodedTrack], actual: Mapping[int, DecodedTrack]
) -> Dict[int, bool]:
    """Compare all three logical tracks without returning their contents."""

    return {
        number: (
            expected[number].text if number in expected else None
        )
        == (actual[number].text if number in actual else None)
        for number in (1, 2, 3)
    }


def compare_raw_tracks(
    expected: Mapping[int, bytes], actual: Mapping[int, bytes]
) -> Dict[int, bool]:
    """Compare raw tracks while accepting either physical swipe direction."""

    def variants(raw: bytes) -> set[bytes]:
        if not raw:
            return {b""}
        if len(raw) < 2:
            # A malformed read-back should compare as data, not abort the
            # verification report before the other tracks are shown.
            return {b"\xff" + raw}
        write_bytes = raw_read_to_write(raw)
        return {
            write_bytes,
            write_bytes[::-1],
            bytes(_reverse_bits(value, 8) for value in write_bytes),
            bytes(_reverse_bits(value, 8) for value in reversed(write_bytes)),
        }

    results = {}
    for number in (1, 2, 3):
        expected_raw = expected.get(number, b"")
        actual_raw = actual.get(number, b"")
        results[number] = bool(variants(expected_raw) & variants(actual_raw))
    return results


def format_magspoof(tracks: Dict[int, DecodedTrack]) -> str:
    """Create a replacement MagSpoof ``tracks[]`` C definition."""

    def c_string(value: str) -> str:
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'

    codes = identify_service_codes(tracks)
    comments = []
    for number, code in sorted(codes.items()):
        classification = "ICC/EMV indicated" if code.icc_emv else "ICC/EMV not indicated"
        comments.append(
            f"// Track {number} service code: {code.value} ({classification})."
        )
    if not service_codes_consistent(codes):
        comments.append("// WARNING: Track 1 and Track 2 service codes disagree.")

    values = [
        tracks[number].text if number in tracks else "" for number in (1, 2, 3)
    ]
    body = ",\n".join(f"    {c_string(value)}" for value in values)
    metadata = "\n".join(comments)
    if metadata:
        metadata += "\n"
    return (
        "// Replace the tracks[] definition in magspoof.c with this block.\n"
        f"{metadata}"
        "const char* tracks[] = {\n"
        f"{body}\n"
        "};\n"
    )


def format_flipper_mag(tracks: Dict[int, DecodedTrack]) -> str:
    """Create the current line-based version-1 Flipper ``.mag`` format."""

    if not tracks:
        raise ValueError("at least one decoded track is required")
    values = {
        number: tracks[number].text if number in tracks else ""
        for number in (1, 2, 3)
    }
    return (
        "Filetype: Flipper Mag device\n"
        "Version: 1\n"
        "# Mag device track data\n"
        f"Track 1: {values[1]}\n"
        f"Track 2: {values[2]}\n"
        f"Track 3: {values[3]}\n"
    )


def format_flipper_legacy_mag(tracks: Dict[int, DecodedTrack]) -> str:
    """Create the older quoted-Data version-1 Flipper MagSpoof format."""

    values = [tracks[number].text for number in (1, 2, 3) if number in tracks]
    if not values:
        raise ValueError("at least one decoded track is required")
    data = "\r\n".join(values)
    return (
        "Filetype: Flipper Magspoof device\r\n"
        "Version: 1\r\n"
        f'Data:"{data}"\r\n'
        "\r\n"
    )


def format_json(
    tracks: Dict[int, DecodedTrack],
    *,
    raw_card: Optional[RawCard] = None,
    bpi: Optional[Mapping[int, int]] = None,
    decode_errors: Optional[Mapping[int, str]] = None,
) -> str:
    """Create a versioned logical/raw interchange document."""

    payload = {
        "schema": CAPTURE_SCHEMA,
        "version": CAPTURE_VERSION,
        "capture_mode": "raw" if raw_card is not None else "iso",
        **{
            f"track{number}": tracks[number].text if number in tracks else None
            for number in (1, 2, 3)
        },
    }
    codes = identify_service_codes(tracks)
    payload["service_codes"] = {
        **{
            f"track{number}": {
                "value": code.value,
                "icc_emv": code.icc_emv,
            }
            for number, code in sorted(codes.items())
        },
        "consistent": service_codes_consistent(codes),
    }
    if raw_card is not None:
        densities = dict(DEFAULT_BPI if bpi is None else bpi)
        if set(densities) != {1, 2, 3} or any(
            density not in (75, 210) for density in densities.values()
        ):
            raise ValueError("raw capture BPI must specify 75 or 210 for every track")
        payload["raw"] = {
            "representation": RAW_READ_REPRESENTATION,
            "tracks": {
                f"track{number}": (
                    raw_card.tracks.get(number, b"").hex()
                    if raw_card.tracks.get(number, b"")
                    else None
                )
                for number in (1, 2, 3)
            },
            "bpi": {
                f"track{number}": densities[number] for number in (1, 2, 3)
            },
        }
        if decode_errors:
            payload["decode_errors"] = {
                f"track{number}": decode_errors[number]
                for number in sorted(decode_errors)
            }
    return json.dumps(payload, indent=2) + "\n"


def write_private(path: str, content: str, *, overwrite: bool = False) -> None:
    """Write sensitive card data with owner-only permissions."""

    flags = os.O_WRONLY | os.O_CREAT
    flags |= os.O_TRUNC if overwrite else os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    os.fchmod(descriptor, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
        output.write(content)


class MSRDevice:
    """USB HID transport for an MSRx6-compatible reader."""

    def __init__(
        self,
        vendor_id: int = VENDOR_ID,
        product_id: int = PRODUCT_ID,
        endpoint_address: int = 0x81,
        report_size: int = 64,
    ) -> None:
        if usb is None:
            raise MSRError("PyUSB is required to communicate with the reader")

        self.dev = usb.core.find(idVendor=vendor_id, idProduct=product_id)
        if self.dev is None:
            raise MSRError(
                f"MSR device {vendor_id:04x}:{product_id:04x} was not found"
            )

        self._detached_kernel_driver = False
        if self.dev.is_kernel_driver_active(0):
            self.dev.detach_kernel_driver(0)
            self._detached_kernel_driver = True
        usb.util.claim_interface(self.dev, 0)

        self.endpoint_address = endpoint_address
        self.report_size = report_size
        self._closed = False

    def send_command(self, command: bytes) -> None:
        if len(command) > self.report_size:
            raise ValueError("command is larger than one HID report")
        report = command + bytes(self.report_size - len(command))
        self.dev.ctrl_transfer(0x21, 9, 0x300, 0, report)

    def send_hid_message(self, message: bytes) -> None:
        """Send a protocol message, splitting it across HID reports as needed."""

        for report in frame_hid_message(message, self.report_size):
            self.dev.ctrl_transfer(0x21, 9, 0x300, 0, report)

    def read_message(self, timeout: float) -> bytes:
        assembler = HIDMessageAssembler()
        deadline = time.monotonic() + timeout
        io_retries = 0

        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise CardReadError("timed out waiting for a card swipe")
            try:
                read_timeout = max(1, min(round(remaining * 1000), 500))
                report = self.dev.read(
                    self.endpoint_address,
                    self.report_size,
                    timeout=read_timeout,
                )
            except usb.core.USBTimeoutError:
                continue
            except usb.core.USBError as error:
                # Some MSRx6 units transiently stall endpoint 0x81 between
                # commands. Clear it and retry twice before surfacing the
                # transport failure.
                if error.errno == 5 and io_retries < 2:
                    io_retries += 1
                    try:
                        self.dev.clear_halt(self.endpoint_address)
                    except usb.core.USBError:
                        pass
                    time.sleep(0.05)
                    continue
                raise MSRError(f"USB reader failed: {error}") from error

            io_retries = 0
            message = assembler.feed(report)
            if message is not None:
                return message

    def capture(self, timeout: float = 30.0) -> Dict[int, DecodedTrack]:
        """Capture and locally decode the reader's raw bitstream."""

        return decode_card(self.capture_raw_card(timeout))

    def capture_raw_card(self, timeout: float = 30.0) -> RawCard:
        """Capture and return the reader's unmodified raw track fields."""

        self.send_command(READ_RAW_COMMAND)
        card = parse_raw_card(self.read_message(timeout))
        if card.status != OK_STATUS:
            printable = chr(card.status) if 32 <= card.status <= 126 else "?"
            raise CardReadError(
                f"reader returned status 0x{card.status:02x} ({printable!r})"
            )
        return card

    def capture_iso(self, timeout: float = 30.0) -> Dict[int, DecodedTrack]:
        """Capture tracks decoded into ISO text by the reader firmware."""

        self.send_command(READ_ISO_COMMAND)
        return decode_iso_card(parse_iso_card(self.read_message(timeout)))

    def set_coercivity(self, coercivity: str, timeout: float = 5.0) -> None:
        """Select high- or low-coercivity media for subsequent writes."""

        commands = {"high": SET_HICO_COMMAND, "low": SET_LOCO_COMMAND}
        try:
            command = commands[coercivity]
        except KeyError as error:
            raise ValueError("coercivity must be 'high' or 'low'") from error
        self.send_command(command)
        parse_status_response(self.read_message(timeout), "setting coercivity")

    def set_bpi(self, track_number: int, density: int, timeout: float = 5.0) -> None:
        """Set one physical track to 75 or 210 bits per inch."""

        try:
            selector = BPI_SELECTOR[(track_number, density)]
        except KeyError as error:
            if track_number not in (1, 2, 3):
                raise ValueError("track number must be 1, 2, or 3") from error
            raise ValueError("density must be 75 or 210 BPI") from error
        self.send_hid_message(SET_BPI_COMMAND_PREFIX + bytes((selector,)))
        try:
            response = self.read_message(timeout)
        except CardReadError as error:
            raise CardWriteError(
                f"timed out waiting for the Track {track_number} BPI response"
            ) from error
        parse_status_response(response, f"setting Track {track_number} BPI")

    def set_bpi_all(
        self, densities: Mapping[int, int], timeout: float = 5.0
    ) -> None:
        """Set the recording density for all three physical tracks."""

        if set(densities) != {1, 2, 3}:
            raise ValueError("BPI settings must include tracks 1, 2, and 3")
        for number in (1, 2, 3):
            self.set_bpi(number, densities[number], timeout)

    def set_bpc(
        self, track1: int, track2: int, track3: int, timeout: float = 5.0
    ) -> None:
        """Set bits per character for the three tracks."""

        values = bytes((track1, track2, track3))
        if any(value < 5 or value > 8 for value in values):
            raise ValueError("BPC values must be between 5 and 8")
        self.send_hid_message(SET_BPC_COMMAND_PREFIX + values)
        try:
            response = self.read_message(timeout)
        except CardReadError as error:
            raise CardWriteError("timed out waiting for the BPC response") from error
        parse_status_response(
            response,
            "setting BPC",
            expected_trailing=values,
        )

    def write_iso(
        self, tracks: Mapping[int, DecodedTrack], timeout: float = 30.0
    ) -> None:
        """Write logical ISO tracks and wait for the card swipe result."""

        self.send_hid_message(encode_iso_write_message(tracks))
        parse_status_response(self.read_message(timeout), "card write")

    def write_raw(
        self, tracks: Mapping[int, bytes], timeout: float = 30.0
    ) -> None:
        """Replay MSRx6 raw-read fields through the raw-write command."""

        self.send_hid_message(encode_raw_write_message(tracks))
        parse_status_response(self.read_message(timeout), "raw card write")

    def erase(self, tracks: Iterable[int] = (1, 2, 3), timeout: float = 30.0) -> None:
        """Erase the selected physical tracks and wait for the card swipe result."""

        selected = set(tracks)
        if not selected:
            raise ValueError("at least one track must be selected for erasure")
        if not selected <= {1, 2, 3}:
            raise ValueError("erase tracks must contain only 1, 2, and/or 3")

        select_bytes = {
            frozenset((1,)): 0x00,
            frozenset((2,)): 0x02,
            frozenset((3,)): 0x04,
            frozenset((1, 2)): 0x03,
            frozenset((1, 3)): 0x05,
            frozenset((2, 3)): 0x06,
            frozenset((1, 2, 3)): 0x07,
        }
        select_byte = select_bytes[frozenset(selected)]
        self.send_command(ERASE_COMMAND_PREFIX + bytes((select_byte,)))
        parse_status_response(self.read_message(timeout), "card erase")

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self.send_command(RESET_COMMAND)
        except usb.core.USBError:
            pass
        try:
            usb.util.release_interface(self.dev, 0)
        except usb.core.USBError:
            pass
        if self._detached_kernel_driver:
            try:
                self.dev.attach_kernel_driver(0)
            except usb.core.USBError:
                pass
        try:
            usb.util.dispose_resources(self.dev)
        except usb.core.USBError:
            pass

    def __enter__(self) -> "MSRDevice":
        return self

    def __exit__(self, _type, _value, _traceback) -> None:
        self.close()
