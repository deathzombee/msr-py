"""MSR605/MSRx6 USB capture, raw-track decoding, and MagSpoof export."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
import queue
import threading
import time
from typing import Dict, Iterable, Optional

try:
    import usb.core
    import usb.util
except ImportError:  # Pure protocol/decoder functions remain usable without PyUSB.
    usb = None


ESC = 0x1B
FS = 0x1C
END_SENTINEL = 0x3F
OK_STATUS = 0x30

VENDOR_ID = 0x0801
PRODUCT_ID = 0x0003

# The HID wrapper's low six bits are its payload length. The two high bits
# indicate the first and final report in a message.
HID_FIRST = 0x80
HID_FINAL = 0x40
HID_LENGTH_MASK = 0x3F

READ_RAW_COMMAND = bytes((0xC5, ESC, 0x6D))
RESET_COMMAND = bytes((0xC2, ESC, 0x61))

TRACK1_ALPHABET = "".join(chr(code) for code in range(32, 96))
TRACK23_ALPHABET = "0123456789:;<=>?"


class MSRError(Exception):
    """Base exception for reader, framing, and decoding errors."""


class ProtocolError(MSRError):
    """The reader returned a malformed HID or MSR protocol message."""


class DecodeError(MSRError):
    """Raw track bits could not be decoded and validated."""


class CardReadError(MSRError):
    """The reader reported an unsuccessful card operation."""


@dataclass(frozen=True)
class RawCard:
    """One parsed raw-read response."""

    tracks: Dict[int, bytes]
    status: int


@dataclass(frozen=True)
class DecodedTrack:
    """A parity- and LRC-validated ISO track string."""

    number: int
    text: str


@dataclass(frozen=True)
class ServiceCodeInfo:
    """A payment-card service code found in a decoded track."""

    track_number: int
    value: str
    icc_emv: bool


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


def _reverse_bits(value: int, width: int) -> int:
    reversed_value = 0
    for _ in range(width):
        reversed_value = (reversed_value << 1) | (value & 1)
        value >>= 1
    return reversed_value


def decode_raw_track(track_number: int, raw: bytes) -> DecodedTrack:
    """Decode a raw track and reject bad sentinels, parity, or LRC."""

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

    bitstream = "".join(f"{byte:08b}" for byte in raw)
    groups = [
        bitstream[offset : offset + bit_width]
        for offset in range(0, len(bitstream) - bit_width + 1, bit_width)
    ]
    values = [int(group[:-1], 2) for group in groups]
    characters = [alphabet[_reverse_bits(value, data_width)] for value in values]

    if not characters or characters[0] != start_sentinel:
        raise DecodeError(
            f"track {track_number} does not begin with {start_sentinel!r}"
        )
    try:
        end_index = characters.index("?", 1)
    except ValueError as error:
        raise DecodeError(f"track {track_number} has no end sentinel") from error

    lrc_index = end_index + 1
    if lrc_index >= len(groups):
        raise DecodeError(f"track {track_number} has no LRC character")

    bad_parity = [
        index
        for index, group in enumerate(groups[: lrc_index + 1])
        if group.count("1") % 2 != 1
    ]
    if bad_parity:
        positions = ", ".join(str(index) for index in bad_parity)
        raise DecodeError(f"track {track_number} has bad parity at character(s) {positions}")

    lrc = 0
    for value in values[: lrc_index + 1]:
        lrc ^= value
    if lrc != 0:
        raise DecodeError(f"track {track_number} failed its LRC check")

    return DecodedTrack(track_number, "".join(characters[: end_index + 1]))


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


def format_json(tracks: Dict[int, DecodedTrack]) -> str:
    """Create a small, lossless interchange document."""

    payload = {
        f"track{number}": tracks[number].text if number in tracks else None
        for number in (1, 2, 3)
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
        self._exit_event = threading.Event()
        self._reports: queue.Queue[bytes] = queue.Queue()
        self._read_error: Optional[BaseException] = None
        self._thread = threading.Thread(target=self._read_reports, daemon=True)
        self._thread.start()

    def _read_reports(self) -> None:
        while not self._exit_event.is_set():
            try:
                report = self.dev.read(
                    self.endpoint_address, self.report_size, timeout=500
                )
                self._reports.put(bytes(report))
            except usb.core.USBTimeoutError:
                continue
            except usb.core.USBError as error:
                if self._exit_event.is_set() or error.errno == 19:
                    return
                self._read_error = error
                return

    def send_command(self, command: bytes) -> None:
        if len(command) > self.report_size:
            raise ValueError("command is larger than one HID report")
        report = command + bytes(self.report_size - len(command))
        self.dev.ctrl_transfer(0x21, 9, 0x300, 0, report)

    def read_message(self, timeout: float) -> bytes:
        assembler = HIDMessageAssembler()
        deadline = time.monotonic() + timeout

        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise CardReadError("timed out waiting for a card swipe")
            if self._read_error is not None and self._reports.empty():
                raise MSRError(f"USB reader failed: {self._read_error}")
            try:
                report = self._reports.get(timeout=min(remaining, 0.5))
            except queue.Empty:
                continue
            message = assembler.feed(report)
            if message is not None:
                return message

    def capture(self, timeout: float = 30.0) -> Dict[int, DecodedTrack]:
        while True:
            try:
                self._reports.get_nowait()
            except queue.Empty:
                break
        self.send_command(READ_RAW_COMMAND)
        return decode_card(parse_raw_card(self.read_message(timeout)))

    def close(self) -> None:
        if self._exit_event.is_set():
            return
        try:
            self.send_command(RESET_COMMAND)
        finally:
            self._exit_event.set()
            self._thread.join(timeout=2)
            usb.util.release_interface(self.dev, 0)
            if self._detached_kernel_driver:
                try:
                    self.dev.attach_kernel_driver(0)
                except usb.core.USBError:
                    pass
            usb.util.dispose_resources(self.dev)

    def __enter__(self) -> "MSRDevice":
        return self

    def __exit__(self, _type, _value, _traceback) -> None:
        self.close()
