import os
from pathlib import Path
import tempfile
import unittest

from msr import (
    DecodeError,
    DecodedTrack,
    HIDMessageAssembler,
    ProtocolError,
    decode_card,
    decode_raw_track,
    format_json,
    format_magspoof,
    identify_service_codes,
    parse_raw_card,
    service_codes_consistent,
    write_private,
)


TRACK1_RAW = bytes.fromhex("a30d1e28a9727c5400")
TRACK2_RAW = bytes.fromhex("d4119257f500")
RAW_MESSAGE = (
    b"\x1b\x73"
    + b"\x1b\x01"
    + bytes((len(TRACK1_RAW),))
    + TRACK1_RAW
    + b"\x1b\x02"
    + bytes((len(TRACK2_RAW),))
    + TRACK2_RAW
    + b"\x1b\x03"
    + bytes((len(TRACK2_RAW),))
    + TRACK2_RAW
    + b"\x3f\x1c\x1b\x30"
)


class HIDMessageAssemblerTests(unittest.TestCase):
    def test_single_report_uses_only_declared_payload(self):
        report = bytes((0xC0 | len(RAW_MESSAGE),)) + RAW_MESSAGE
        report += bytes(64 - len(report))

        self.assertEqual(HIDMessageAssembler().feed(report), RAW_MESSAGE)

    def test_multiple_reports_are_reassembled(self):
        message = bytes(range(100))
        first = bytes((0x80 | 63,)) + message[:63]
        final_payload = message[63:]
        final = bytes((0x40 | len(final_payload),)) + final_payload
        final += bytes(64 - len(final))
        assembler = HIDMessageAssembler()

        self.assertIsNone(assembler.feed(first))
        self.assertEqual(assembler.feed(final), message)

    def test_continuation_without_start_is_rejected(self):
        with self.assertRaises(ProtocolError):
            HIDMessageAssembler().feed(b"\x41x")


class RawCardTests(unittest.TestCase):
    def test_parse_and_decode_known_tracks(self):
        tracks = decode_card(parse_raw_card(RAW_MESSAGE))

        self.assertEqual(tracks[1].text, "%ABC123?")
        self.assertEqual(tracks[2].text, ";12345?")
        self.assertEqual(tracks[3].text, ";12345?")

    def test_track_lengths_allow_escape_bytes_in_payload(self):
        message = (
            b"\x1b\x73\x1b\x01\x02\x1b\x01"
            b"\x1b\x02\x00\x1b\x03\x00\x3f\x1c\x1b\x30"
        )

        self.assertEqual(parse_raw_card(message).tracks[1], b"\x1b\x01")

    def test_truncated_track_is_rejected(self):
        with self.assertRaises(ProtocolError):
            parse_raw_card(b"\x1b\x73\x1b\x01\x20short")

    def test_bad_parity_is_rejected(self):
        damaged = bytes((TRACK1_RAW[0] ^ 1,)) + TRACK1_RAW[1:]

        with self.assertRaisesRegex(DecodeError, "parity"):
            decode_raw_track(1, damaged)

    def test_bad_lrc_is_rejected(self):
        damaged = TRACK1_RAW[:7] + bytes((TRACK1_RAW[7] ^ 0xC0,)) + TRACK1_RAW[8:]

        with self.assertRaisesRegex(DecodeError, "LRC"):
            decode_raw_track(1, damaged)


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.tracks = decode_card(parse_raw_card(RAW_MESSAGE))

    def test_magspoof_export(self):
        output = format_magspoof(self.tracks)

        self.assertIn('"%ABC123?"', output)
        self.assertIn('";12345?"', output)

    def test_json_export(self):
        output = format_json(self.tracks)

        self.assertIn('"track1": "%ABC123?"', output)

    def test_private_writer_refuses_overwrite_and_uses_mode_600(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "card.json"
            write_private(str(path), "secret\n")

            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError):
                write_private(str(path), "replacement\n")

            os.chmod(path, 0o644)
            write_private(str(path), "replacement\n", overwrite=True)
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)


class ServiceCodeTests(unittest.TestCase):
    def test_identifies_emv_service_code_on_both_payment_tracks(self):
        tracks = {
            1: DecodedTrack(
                1, "%B1234567890123456^TEST/USER^30012010000000000000?"
            ),
            2: DecodedTrack(2, ";1234567890123456=30012010000000000000?"),
        }

        codes = identify_service_codes(tracks)

        self.assertEqual(codes[1].value, "201")
        self.assertTrue(codes[1].icc_emv)
        self.assertEqual(codes[2].value, "201")
        self.assertTrue(service_codes_consistent(codes))

    def test_nonpayment_tracks_have_no_service_code(self):
        tracks = {1: DecodedTrack(1, "%ABC123?"), 2: DecodedTrack(2, ";12345?")}

        self.assertEqual(identify_service_codes(tracks), {})

    def test_mismatch_is_reported_but_tracks_are_not_modified(self):
        tracks = {
            1: DecodedTrack(1, "%B1^T/U^3001201?"),
            2: DecodedTrack(2, ";1=3001101?"),
        }
        original = {number: track.text for number, track in tracks.items()}
        codes = identify_service_codes(tracks)

        self.assertFalse(service_codes_consistent(codes))
        self.assertEqual(
            {number: track.text for number, track in tracks.items()}, original
        )
        self.assertIn("service codes disagree", format_magspoof(tracks))


if __name__ == "__main__":
    unittest.main()
