import os
from pathlib import Path
import tempfile
import unittest

from msr import (
    CardReadError,
    CardWriteError,
    DEFAULT_BPI,
    DecodeError,
    DecodedTrack,
    HIDMessageAssembler,
    ISOCard,
    MSRDevice,
    ProtocolError,
    RawCard,
    compare_raw_tracks,
    compare_track_text,
    decode_card,
    decode_card_partial,
    decode_iso_card,
    decode_raw_track,
    encode_iso_write_message,
    encode_raw_write_message,
    frame_hid_message,
    format_flipper_legacy_mag,
    format_flipper_mag,
    format_json,
    format_magspoof,
    identify_service_codes,
    load_capture,
    load_json_tracks,
    parse_raw_card,
    parse_iso_card,
    parse_status_response,
    raw_read_to_write,
    service_codes_consistent,
    validate_iso_tracks,
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
ISO_MESSAGE = (
    b"\x1b\x73"
    b"\x1b\x01%ABC123?"
    b"\x1b\x02;12345?"
    b"\x1b\x03;12345?"
    b"\x3f\x1c\x1b\x30"
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

    def test_outbound_message_is_split_and_reassembles_losslessly(self):
        message = bytes(range(140))
        reports = frame_hid_message(message)
        assembler = HIDMessageAssembler()

        self.assertEqual(len(reports), 3)
        self.assertTrue(all(len(report) == 64 for report in reports))
        self.assertIsNone(assembler.feed(reports[0]))
        self.assertIsNone(assembler.feed(reports[1]))
        self.assertEqual(assembler.feed(reports[2]), message)

    def test_single_outbound_report_has_both_boundary_flags(self):
        report = frame_hid_message(b"abc")[0]

        self.assertEqual(report[:4], b"\xc3abc")


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

    def test_reverse_track_1_is_detected_and_validated(self):
        bitstream = "".join(f"{byte:08b}" for byte in TRACK1_RAW)[::-1]
        reverse_raw = bytes(
            int(bitstream[offset : offset + 8], 2)
            for offset in range(0, len(bitstream), 8)
        )

        decoded = decode_raw_track(1, reverse_raw)

        self.assertEqual(decoded.text, "%ABC123?")
        self.assertEqual(decoded.direction, "reverse")

    def test_reverse_track_2_is_detected_and_validated(self):
        bitstream = "".join(f"{byte:08b}" for byte in TRACK2_RAW)[::-1]
        reverse_raw = bytes(
            int(bitstream[offset : offset + 8], 2)
            for offset in range(0, len(bitstream), 8)
        )

        decoded = decode_raw_track(2, reverse_raw)

        self.assertEqual(decoded.text, ";12345?")
        self.assertEqual(decoded.direction, "reverse")

    def test_track_2_with_reversed_byte_order_is_detected(self):
        decoded = decode_raw_track(2, TRACK2_RAW[::-1])

        self.assertEqual(decoded.text, ";12345?")
        self.assertEqual(decoded.direction, "reverse")

    def test_track_2_with_reversed_bits_in_each_byte_is_detected(self):
        raw = bytes(int(f"{byte:08b}"[::-1], 2) for byte in TRACK2_RAW)

        decoded = decode_raw_track(2, raw)

        self.assertEqual(decoded.text, ";12345?")
        self.assertEqual(decoded.direction, "reverse")

    def test_track_2_can_start_at_a_nonzero_bit_alignment(self):
        bitstream = "000" + "".join(f"{byte:08b}" for byte in TRACK2_RAW)
        bitstream += "0" * (-len(bitstream) % 8)
        raw = bytes(
            int(bitstream[offset : offset + 8], 2)
            for offset in range(0, len(bitstream), 8)
        )

        decoded = decode_raw_track(2, raw)

        self.assertEqual(decoded.text, ";12345?")

    def test_partial_decode_retains_failure_without_losing_other_tracks(self):
        damaged = bytes((TRACK2_RAW[0] ^ 1,)) + TRACK2_RAW[1:]
        card = RawCard({1: TRACK1_RAW, 2: damaged, 3: b""}, 0x30)

        decoded, errors = decode_card_partial(card)

        self.assertEqual(decoded[1].text, "%ABC123?")
        self.assertEqual(set(errors), {2})


class ISOCardTests(unittest.TestCase):
    def test_parse_and_validate_known_tracks(self):
        tracks = decode_iso_card(parse_iso_card(ISO_MESSAGE))

        self.assertEqual(tracks[1].text, "%ABC123?")
        self.assertEqual(tracks[2].text, ";12345?")
        self.assertEqual(tracks[3].text, ";12345?")

    def test_empty_track_field_is_omitted(self):
        message = (
            b"\x1b\x73\x1b\x01%ABC123?\x1b\x02;12345?"
            b"\x1b\x03\x3f\x1c\x1b\x30"
        )

        tracks = decode_iso_card(parse_iso_card(message))

        self.assertEqual(set(tracks), {1, 2})

    def test_explicit_empty_track_status_is_omitted(self):
        message = (
            b"\x1b\x73\x1b\x01%ABC123?\x1b\x02;12345?"
            b"\x1b\x03\x1b\x2b\x3f\x1c\x1b\x30"
        )

        tracks = decode_iso_card(parse_iso_card(message))

        self.assertEqual(set(tracks), {1, 2})

    def test_explicit_bad_track_status_is_reported(self):
        message = (
            b"\x1b\x73\x1b\x01\x1b\x2a\x1b\x02;12345?"
            b"\x1b\x03\x1b\x2b\x3f\x1c\x1b\x30"
        )

        card = parse_iso_card(message)

        self.assertEqual(card.bad_tracks, frozenset({1}))
        with self.assertRaisesRegex(CardReadError, "track.*1"):
            decode_iso_card(card)

    def test_stale_bytes_after_first_complete_response_are_ignored(self):
        trailing_stale_data = b"\xaa\xbb\x3f\x1c\x1b\x31"

        tracks = decode_iso_card(parse_iso_card(ISO_MESSAGE + trailing_stale_data))

        self.assertEqual(tracks[1].text, "%ABC123?")
        self.assertEqual(tracks[2].text, ";12345?")

    def test_transport_byte_between_ending_field_and_status_is_ignored(self):
        split_status = ISO_MESSAGE[:-2] + b"\x6f" + ISO_MESSAGE[-2:]

        tracks = decode_iso_card(parse_iso_card(split_status))

        self.assertEqual(tracks[2].text, ";12345?")

    def test_bad_reader_status_is_rejected(self):
        with self.assertRaises(CardReadError):
            decode_iso_card(ISOCard({2: ";12345?"}, 0x31))

    def test_malformed_trailer_is_rejected(self):
        with self.assertRaises(ProtocolError):
            parse_iso_card(ISO_MESSAGE[:-4])


class CardWriteProtocolTests(unittest.TestCase):
    def setUp(self):
        self.tracks = {
            1: DecodedTrack(1, "%ABC123?"),
            2: DecodedTrack(2, ";12345?"),
            3: DecodedTrack(3, ";12345?"),
        }

    def test_iso_write_message_matches_programming_manual(self):
        message = encode_iso_write_message(self.tracks)

        self.assertEqual(
            message,
            bytes.fromhex(
                "1b771b731b014142433132331b023132333435"
                "1b0331323334353f1c"
            ),
        )

    def test_iso_write_uses_empty_fields_for_missing_tracks(self):
        message = encode_iso_write_message({2: self.tracks[2]})

        self.assertEqual(message, b"\x1bw\x1bs\x1b\x01\x1b\x0212345\x1b\x03?\x1c")

    def test_raw_read_bytes_convert_to_manual_raw_write_bytes(self):
        self.assertEqual(
            raw_read_to_write(TRACK1_RAW),
            bytes.fromhex("c5b07814954e3e2a"),
        )
        self.assertEqual(
            raw_read_to_write(TRACK2_RAW),
            bytes.fromhex("2b8849eaaf"),
        )

    def test_raw_write_message_matches_programming_manual(self):
        message = encode_raw_write_message({1: TRACK1_RAW, 2: TRACK2_RAW, 3: TRACK2_RAW})

        self.assertEqual(
            message,
            bytes.fromhex(
                "1b6e1b731b0108c5b07814954e3e2a"
                "1b02052b8849eaaf1b03052b8849eaaf3f1c"
            ),
        )

    def test_invalid_sentinel_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "must start"):
            validate_iso_tracks({2: DecodedTrack(2, "%12345?")})

    def test_character_outside_track_alphabet_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "ISO alphabet"):
            validate_iso_tracks({2: DecodedTrack(2, ";12A45?")})

    def test_success_status_is_accepted(self):
        self.assertEqual(parse_status_response(b"\x1b0", "card write"), 0x30)

    def test_write_failure_status_has_description(self):
        with self.assertRaisesRegex(CardWriteError, "invalid card swipe"):
            parse_status_response(b"\x1b9", "card write")

    def test_malformed_status_is_rejected(self):
        with self.assertRaises(ProtocolError):
            parse_status_response(b"0", "card write")

    def test_json_capture_loads_without_using_service_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "original.json"
            path.write_text(
                '{"track1": "%ABC123?", "track2": ";12345?", '
                '"track3": null, "service_codes": {"consistent": true}}',
                encoding="utf-8",
            )

            loaded = load_json_tracks(path)

        self.assertEqual({number: track.text for number, track in loaded.items()}, {
            1: "%ABC123?",
            2: ";12345?",
        })

    def test_versioned_raw_capture_round_trips_without_iso_decoding(self):
        damaged = bytes((TRACK2_RAW[0] ^ 1,)) + TRACK2_RAW[1:]
        raw_card = RawCard({1: TRACK1_RAW, 2: damaged, 3: b""}, 0x30)
        content = format_json(
            {1: self.tracks[1]},
            raw_card=raw_card,
            bpi=DEFAULT_BPI,
            decode_errors={2: "not ISO"},
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capture.json"
            path.write_text(content, encoding="utf-8")

            capture = load_capture(path)

        self.assertEqual(capture.raw_tracks, {1: TRACK1_RAW, 2: damaged})
        self.assertEqual(capture.bpi, DEFAULT_BPI)
        self.assertEqual(capture.tracks[1].text, "%ABC123?")

    def test_raw_comparison_accepts_reverse_swipe_orientation(self):
        reverse = bytes(int(f"{value:08b}"[::-1], 2) for value in reversed(TRACK2_RAW[:-1]))
        reverse_read = reverse + b"\x00"

        result = compare_raw_tracks({2: TRACK2_RAW}, {2: reverse_read})

        self.assertTrue(result[2])

    def test_track_comparison_includes_absent_tracks(self):
        actual = {1: self.tracks[1], 2: self.tracks[2]}
        expected = {1: self.tracks[1], 2: self.tracks[2], 3: self.tracks[3]}

        self.assertEqual(
            compare_track_text(expected, actual),
            {1: True, 2: True, 3: False},
        )


class CardWriterTransportTests(unittest.TestCase):
    class FakeUSBDevice:
        def __init__(self):
            self.reports = []

        def ctrl_transfer(self, request_type, request, value, index, report):
            self.reports.append(
                (request_type, request, value, index, bytes(report))
            )

    def make_device(self):
        device = object.__new__(MSRDevice)
        device.report_size = 64
        device.dev = self.FakeUSBDevice()
        return device

    def test_send_hid_message_transmits_each_framed_report(self):
        device = self.make_device()
        message = bytes(range(100))

        device.send_hid_message(message)

        reports = [transfer[4] for transfer in device.dev.reports]
        self.assertEqual(tuple(reports), frame_hid_message(message))
        self.assertTrue(
            all(transfer[:4] == (0x21, 9, 0x300, 0) for transfer in device.dev.reports)
        )

    def test_iso_capture_uses_reader_decoding_command(self):
        device = self.make_device()
        device.read_message = lambda timeout: ISO_MESSAGE

        tracks = device.capture_iso(timeout=7.0)

        self.assertEqual(tracks[2].text, ";12345?")
        self.assertEqual(device.dev.reports[0][4][:3], b"\xc5\x1br")

    def test_raw_capture_returns_unmodified_track_fields(self):
        device = self.make_device()
        device.read_message = lambda timeout: RAW_MESSAGE

        card = device.capture_raw_card(timeout=7.0)

        self.assertEqual(card.tracks[1], TRACK1_RAW)
        self.assertEqual(device.dev.reports[0][4][:3], b"\xc5\x1bm")

    def test_write_waits_for_and_validates_status(self):
        device = self.make_device()
        received_timeouts = []
        device.read_message = lambda timeout: (
            received_timeouts.append(timeout) or b"\x1b0"
        )
        tracks = {2: DecodedTrack(2, ";12345?")}

        device.write_iso(tracks, timeout=12.5)

        self.assertEqual(received_timeouts, [12.5])
        reports = [transfer[4] for transfer in device.dev.reports]
        assembler = HIDMessageAssembler()
        self.assertEqual(assembler.feed(reports[0]), encode_iso_write_message(tracks))

    def test_raw_write_waits_for_and_validates_status(self):
        device = self.make_device()
        device.read_message = lambda timeout: b"\x1b0"
        tracks = {1: TRACK1_RAW, 2: TRACK2_RAW}

        device.write_raw(tracks, timeout=12.5)

        assembler = HIDMessageAssembler()
        reports = [transfer[4] for transfer in device.dev.reports]
        self.assertEqual(assembler.feed(reports[0]), encode_raw_write_message(tracks))

    def test_raw_configuration_uses_manual_bpc_and_bpi_selectors(self):
        device = self.make_device()
        responses = iter((b"\x1b0\x08\x08\x08", b"\x1b0", b"\x1b0", b"\x1b0"))
        device.read_message = lambda timeout: next(responses)

        device.set_bpc(8, 8, 8)
        device.set_bpi_all(DEFAULT_BPI)

        commands = [transfer[4][:6] for transfer in device.dev.reports]
        self.assertEqual(commands[0], b"\xc5\x1bo\x08\x08\x08")
        self.assertEqual(commands[1][:4], b"\xc3\x1bb\xa1")
        self.assertEqual(commands[2][:4], b"\xc3\x1bb\x4b")
        self.assertEqual(commands[3][:4], b"\xc3\x1bb\xc1")

    def test_erase_uses_selected_track_bitmask_and_waits_for_status(self):
        device = self.make_device()
        received_timeouts = []
        device.read_message = lambda timeout: (
            received_timeouts.append(timeout) or b"\x1b0"
        )

        device.erase((1, 3), timeout=8.0)

        self.assertEqual(received_timeouts, [8.0])
        report = device.dev.reports[0][4]
        self.assertEqual(report[:6], b"\xc5\x1bc\x05\x00\x00")

    def test_erase_rejects_an_empty_selection(self):
        device = self.make_device()

        with self.assertRaisesRegex(ValueError, "at least one"):
            device.erase(())

    def test_track_one_only_uses_device_specific_zero_select_byte(self):
        device = self.make_device()
        device.read_message = lambda timeout: b"\x1b0"

        device.erase((1,))

        self.assertEqual(device.dev.reports[0][4][:6], b"\xc5\x1bc\x00\x00\x00")


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

    def test_flipper_mag_export_uses_current_line_based_layout(self):
        output = format_flipper_mag(self.tracks)

        self.assertEqual(
            output,
            "Filetype: Flipper Mag device\n"
            "Version: 1\n"
            "# Mag device track data\n"
            "Track 1: %ABC123?\n"
            "Track 2: ;12345?\n"
            "Track 3: ;12345?\n",
        )

    def test_legacy_flipper_mag_export_uses_quoted_data_and_crlf(self):
        output = format_flipper_legacy_mag(self.tracks)

        self.assertEqual(
            output,
            "Filetype: Flipper Magspoof device\r\n"
            "Version: 1\r\n"
            'Data:"%ABC123?\r\n;12345?\r\n;12345?"\r\n'
            "\r\n",
        )

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
