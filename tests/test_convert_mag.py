import importlib.util
import os
from pathlib import Path
import tempfile
import unittest


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "convert-mag.py"
SPEC = importlib.util.spec_from_file_location("convert_mag", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
convert_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(convert_module)


class ConvertMagTests(unittest.TestCase):
    def test_parses_crlf_legacy_file(self):
        content = (
            "Filetype: Flipper Magspoof device\r\n"
            "Version: 1\r\n"
            'Data:"%B123^TEST/USER^9912101?\r\n;123=9912101?"\r\n\r\n'
        )

        tracks = convert_module.parse_legacy_mag(content)

        self.assertEqual(tracks[1].text, "%B123^TEST/USER^9912101?")
        self.assertEqual(tracks[2].text, ";123=9912101?")

    def test_track_two_only_is_not_misidentified_as_track_one(self):
        content = (
            "Filetype: Flipper Magspoof device\n"
            "Version: 1\n"
            'Data:";123=9912101?"\n'
        )

        tracks = convert_module.parse_legacy_mag(content)

        self.assertEqual(set(tracks), {2})

    def test_rejects_invalid_header(self):
        with self.assertRaisesRegex(ValueError, "not a version-1 legacy"):
            convert_module.parse_legacy_mag('Data:";123?"\n')

    def test_convert_file_creates_private_current_format(self):
        content = (
            "Filetype: Flipper Magspoof device\r\n"
            "Version: 1\r\n"
            'Data:"%ABC?\r\n;123?"\r\n\r\n'
        )
        with tempfile.TemporaryDirectory() as directory:
            input_path = Path(directory) / "legacy.mag"
            output_path = Path(directory) / "current.mag"
            input_path.write_text(content, encoding="utf-8", newline="")

            convert_module.convert_file(input_path, output_path)

            self.assertEqual(
                output_path.read_text(encoding="utf-8"),
                "Filetype: Flipper Mag device\n"
                "Version: 1\n"
                "# Mag device track data\n"
                "Track 1: %ABC?\n"
                "Track 2: ;123?\n"
                "Track 3: \n",
            )
            self.assertEqual(os.stat(output_path).st_mode & 0o777, 0o600)

    def test_convert_file_refuses_to_replace_output(self):
        content = (
            "Filetype: Flipper Magspoof device\n"
            "Version: 1\n"
            'Data:";123?"\n'
        )
        with tempfile.TemporaryDirectory() as directory:
            input_path = Path(directory) / "legacy.mag"
            output_path = Path(directory) / "current.mag"
            input_path.write_text(content, encoding="utf-8")
            output_path.write_text("keep me", encoding="utf-8")

            with self.assertRaises(FileExistsError):
                convert_module.convert_file(input_path, output_path)

            self.assertEqual(output_path.read_text(encoding="utf-8"), "keep me")


if __name__ == "__main__":
    unittest.main()
