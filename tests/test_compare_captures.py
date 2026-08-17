import importlib.util
from pathlib import Path
import unittest


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "compare-captures.py"
SPEC = importlib.util.spec_from_file_location("compare_captures", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
compare_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(compare_module)


class CompareCapturesTests(unittest.TestCase):
    def test_identical_captures_match(self):
        capture = {
            "track1": "%B123?",
            "track2": ";123?",
            "track3": None,
            "service_codes": {"consistent": True},
        }

        tracks, service_codes = compare_module.compare_captures(capture, capture)

        self.assertTrue(all(tracks.values()))
        self.assertTrue(service_codes)

    def test_track_difference_is_detected_without_returning_track_data(self):
        original = {"track1": "%B123?", "track2": ";123?", "track3": None}
        replay = {"track1": "%B124?", "track2": ";123?", "track3": None}

        tracks, _service_codes = compare_module.compare_captures(original, replay)

        self.assertEqual(
            tracks, {"track1": False, "track2": True, "track3": True}
        )

    def test_service_code_metadata_difference_is_detected(self):
        original = {"service_codes": {"track2": {"value": "201"}}}
        replay = {"service_codes": {"track2": {"value": "101"}}}

        _tracks, service_codes = compare_module.compare_captures(original, replay)

        self.assertFalse(service_codes)


if __name__ == "__main__":
    unittest.main()
