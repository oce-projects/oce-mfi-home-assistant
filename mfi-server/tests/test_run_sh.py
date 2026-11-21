"""Offline checks of the compatibility recorder wiring of the mfi-controller add-on.

Run from the repository root:
    python3 -m unittest discover -s mfi-server/tests -t mfi-server -v

Standard library only; no network, no YAML reader. The files are read as text:
mfi-controller/run.sh (the recorder block and its start), config.yaml (options,
schema and map) and the English and Italian translations.
"""
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ADDON = ROOT / "mfi-controller"
LANGUAGES = ("en", "it")
OPTION_KEYS = ("record_traffic", "record_max_mb")
SED_DELETE = 'sed -i "/^# mfi-recorder begin$/,/^# mfi-recorder end$/d"'
RECORD_ON = 'if [ "$RECORD_TRAFFIC" = true ]'


def top_level_section(text: str, key: str) -> list[str]:
    """Stripped lines under a top-level YAML key, up to the next top-level key."""
    lines = []
    inside = False
    for line in text.splitlines():
        if line.startswith(key + ":"):
            inside = True
            continue
        if inside and line and not line.startswith(" "):
            break
        if inside:
            lines.append(line.strip())
    return lines


def translation_text(text: str, key: str, field: str) -> str | None:
    """Value of field under configuration.<key>, or None when missing."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line == f"  {key}:":
            prefix = f"    {field}: "
            for body in lines[i + 1:]:
                if body.startswith("  ") and not body.startswith("    "):
                    break
                if body.startswith(prefix):
                    return body[len(prefix):].strip().strip('"')
            return None
    return None


class TestRunScript(unittest.TestCase):
    def setUp(self):
        self.run_sh = (ADDON / "run.sh").read_text(encoding="utf-8")

    def test_recorder_markers_and_ports_are_written(self):
        for needle in ("# mfi-recorder begin", "# mfi-recorder end", "unifi.https.port=16443"):
            with self.subTest(needle=needle):
                self.assertIn(needle, self.run_sh)
        self.assertNotIn("unifi.http.port", self.run_sh)

    def test_options_are_read_with_jq(self):
        for key in OPTION_KEYS:
            with self.subTest(key=key):
                self.assertIn("." + key, self.run_sh)

    def test_old_block_is_removed_before_the_block_is_written(self):
        removed = self.run_sh.find(SED_DELETE)
        guard = self.run_sh.find(RECORD_ON)
        port = self.run_sh.find("unifi.https.port=16443")
        self.assertNotEqual(removed, -1, "the sed command that removes the old block is missing")
        self.assertNotEqual(guard, -1, "the block is not written under a record_traffic check")
        self.assertLess(removed, guard)
        self.assertLess(guard, port)

    def test_recorder_is_started_only_when_recording_is_on(self):
        start = self.run_sh.find("start_recorder &")
        self.assertNotEqual(start, -1, "start_recorder is never started")
        self.assertNotEqual(self.run_sh.rfind(RECORD_ON, 0, start), -1)
        self.assertIn("/recorder.py", self.run_sh)
        self.assertIn("--chuid mfi:mfi", self.run_sh)

    def test_recordings_folder_is_private(self):
        self.assertIn('chmod 0700 "$out"', self.run_sh)

    def test_certificate_and_missing_https_message(self):
        self.assertIn("openssl req -x509 -newkey rsa:2048", self.run_sh)
        self.assertIn("https recording unavailable: the controller did not move to 16443", self.run_sh)

    def test_java_starts_without_supervisor_tokens(self):
        start = self.run_sh.find("as_mfi() {")
        self.assertNotEqual(start, -1, "as_mfi is missing")
        end = self.run_sh.find("\n}", start)
        self.assertNotEqual(end, -1, "as_mfi is not closed")
        body = self.run_sh[start:end]
        env = body.find("env -u SUPERVISOR_TOKEN -u HASSIO_TOKEN")
        self.assertNotEqual(env, -1, "as_mfi does not drop the Supervisor tokens")
        self.assertLess(env, body.find("start-stop-daemon"))

    def test_recorder_starts_without_supervisor_tokens(self):
        sep = self.run_sh.find("-- /recorder.py")
        self.assertNotEqual(sep, -1, "the recorder start command is missing")
        begin = self.run_sh.rfind("start-stop-daemon", 0, sep)
        self.assertNotEqual(begin, -1, "start-stop-daemon for the recorder is missing")
        line_start = self.run_sh.rfind("\n", 0, begin) + 1
        prefix = self.run_sh[line_start:begin]
        self.assertIn("env -u SUPERVISOR_TOKEN -u HASSIO_TOKEN", prefix)


class TestAddonConfig(unittest.TestCase):
    def setUp(self):
        self.config = (ADDON / "config.yaml").read_text(encoding="utf-8")

    def test_options_have_recorder_defaults(self):
        options = top_level_section(self.config, "options")
        self.assertIn("record_traffic: false", options)
        self.assertIn("record_max_mb: 200", options)

    def test_schema_types(self):
        schema = top_level_section(self.config, "schema")
        self.assertIn("record_traffic: bool", schema)
        self.assertIn('record_max_mb: "int(10,2000)"', schema)

    def test_map_shares_the_share_folder(self):
        self.assertIn("- share:rw", top_level_section(self.config, "map"))


class TestTranslations(unittest.TestCase):
    def setUp(self):
        self.texts = {
            lang: (ADDON / "translations" / f"{lang}.yaml").read_text(encoding="utf-8")
            for lang in LANGUAGES
        }

    def test_both_languages_have_the_option_texts(self):
        for lang in LANGUAGES:
            for key in OPTION_KEYS:
                for field in ("name", "description"):
                    with self.subTest(lang=lang, key=key, field=field):
                        self.assertTrue(translation_text(self.texts[lang], key, field),
                                        f"{lang}.{key}.{field} is missing or empty")

    def test_italian_description_differs_from_english(self):
        for key in OPTION_KEYS:
            with self.subTest(key=key):
                en = translation_text(self.texts["en"], key, "description")
                it = translation_text(self.texts["it"], key, "description")
                self.assertTrue(it)
                self.assertNotEqual(it, en)


class TestUdpCapture(unittest.TestCase):
    def setUp(self):
        self.config = (ADDON / "config.yaml").read_text(encoding="utf-8")
        self.run_sh = (ADDON / "run.sh").read_text(encoding="utf-8")

    def test_host_network_is_top_level(self):
        self.assertIn("host_network: true", self.config.splitlines())

    def test_net_raw_is_granted_under_privileged(self):
        self.assertIn("privileged:", self.config.splitlines())
        self.assertIn("- NET_RAW", top_level_section(self.config, "privileged"))

    def test_recording_stays_off_by_default(self):
        self.assertIn("record_traffic: false", top_level_section(self.config, "options"))

    def test_udp_capture_flag_is_in_the_recorder_arguments(self):
        self.assertIn("--udp-capture", self.run_sh)
        arg_lines = [line for line in self.run_sh.splitlines() if line.strip().startswith("args=(")]
        self.assertEqual(len(arg_lines), 1)
        self.assertIn("--udp-capture", arg_lines[0])

    def test_recorder_runs_as_user_mfi_after_dropping_from_root(self):
        arg_lines = [line for line in self.run_sh.splitlines() if line.strip().startswith("args=(")]
        self.assertIn("--user mfi", arg_lines[0])

    def test_inform_is_forwarded_from_16080_to_6080(self):
        arg_lines = [line for line in self.run_sh.splitlines() if line.strip().startswith("args=(")]
        self.assertEqual(len(arg_lines), 1)
        self.assertIn("--inform-listen 16080 --inform-target 6080", arg_lines[0])

    def test_tcp_capture_of_6080_is_in_the_arguments(self):
        arg_lines = [line for line in self.run_sh.splitlines() if line.strip().startswith("args=(")]
        self.assertEqual(len(arg_lines), 1)
        self.assertIn("--tcp-capture 6080", arg_lines[0])

    def test_recorder_waits_for_the_controller_on_6080(self):
        self.assertIn("port_open 6080 && port_open 16443", self.run_sh)
        self.assertNotIn("port_open 16080", self.run_sh)

    def test_recorder_is_not_started_with_chuid(self):
        sep = self.run_sh.find("-- /recorder.py")
        self.assertNotEqual(sep, -1, "the recorder start command is missing")
        begin = self.run_sh.rfind("start-stop-daemon", 0, sep)
        self.assertNotEqual(begin, -1, "start-stop-daemon for the recorder is missing")
        command = self.run_sh[begin:sep]
        self.assertNotIn("--chuid", command)


if __name__ == "__main__":
    unittest.main()
