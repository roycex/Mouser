"""Unit tests for the program launch target logic.

Deliberately toolkit-free: ``core.program_launcher`` must stay importable and
testable without a Qt installation, which is also what lets this module run in
minimal CI.  The two behaviours worth guarding hardest are the tokenizer (a
``shlex``-based implementation would silently eat backslashes in Windows paths)
and the macOS ``.app`` argv fork (a bundle is a directory, so handing it to
Popen fails).
"""

import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from core import program_launcher as pl


EXISTING_PROGRAM = sys.executable
EXISTING_DIR = os.path.dirname(EXISTING_PROGRAM)
MISSING_PROGRAM = os.path.join(tempfile.gettempdir(),
                               "mouser-no-such-dir-9f1", "app.exe")
MISSING_DIR = os.path.join(tempfile.gettempdir(),
                           "mouser-no-such-dir-9f1", "cwd")


def _target(path=EXISTING_PROGRAM, name="Program", args="", cwd=""):
    return {"id": "t_test", "name": name, "path": path, "args": args, "cwd": cwd}


class ActionIdTests(unittest.TestCase):
    def test_round_trip(self):
        self.assertEqual(pl.launch_action_id("t_1"), "launch:t_1")
        self.assertTrue(pl.is_launch_action("launch:t_1"))
        self.assertEqual(pl.launch_target_id("launch:t_1"), "t_1")

    def test_empty_payload_is_not_a_launch_action(self):
        self.assertFalse(pl.is_launch_action("launch:"))
        self.assertFalse(pl.is_launch_action(""))
        self.assertFalse(pl.is_launch_action("none"))
        self.assertFalse(pl.is_launch_action("custom:ctrl+a"))
        self.assertEqual(pl.launch_target_id("launch:"), "")

    def test_empty_id_encodes_to_empty_string(self):
        self.assertEqual(pl.launch_action_id(""), "")
        self.assertEqual(pl.launch_action_id(None), "")

    def test_non_launch_ids_pass_through_the_label_helper(self):
        self.assertEqual(pl.launch_action_label("none"), "none")
        self.assertEqual(pl.launch_action_label("custom:ctrl+a"), "custom:ctrl+a")
        self.assertEqual(pl.launch_action_label("launch:"), "launch:")

    def test_label_resolves_a_registered_target(self):
        targets = [pl.make_target(EXISTING_PROGRAM, name="My Editor",
                                  target_id="t_1")]
        self.assertEqual(pl.launch_action_label("launch:t_1", targets),
                         "My Editor")

    def test_label_marks_a_dangling_target(self):
        self.assertEqual(pl.launch_action_label("launch:t_gone", []),
                         "Launch: t_gone (missing)")
        self.assertEqual(pl.launch_action_label("launch:t_gone", None),
                         "Launch: t_gone (missing)")


class ParseArgsTests(unittest.TestCase):
    def test_empty_input_yields_no_tokens(self):
        self.assertEqual(pl.parse_launch_args(""), [])
        self.assertEqual(pl.parse_launch_args("   "), [])
        self.assertEqual(pl.parse_launch_args(None), [])

    def test_whitespace_separates_and_collapses(self):
        self.assertEqual(pl.parse_launch_args("--new-window"), ["--new-window"])
        self.assertEqual(pl.parse_launch_args("--a  --b"), ["--a", "--b"])
        self.assertEqual(pl.parse_launch_args("a\tb"), ["a", "b"])

    def test_backslashes_are_always_literal(self):
        # The reason this tokenizer exists: shlex(posix=True) would turn the
        # Windows path below into "--path=C:foo".
        self.assertEqual(pl.parse_launch_args(r"--path=C:\foo"), [r"--path=C:\foo"])
        self.assertEqual(
            pl.parse_launch_args('--path="C:\\Program Files\\x"'),
            [r"--path=C:\Program Files\x"],
        )

    def test_quotes_group_a_token(self):
        self.assertEqual(pl.parse_launch_args('"a b" c'), ["a b", "c"])
        self.assertEqual(pl.parse_launch_args("'a b' c"), ["a b", "c"])
        self.assertEqual(pl.parse_launch_args('"a"b'), ["ab"])
        self.assertEqual(pl.parse_launch_args("''"), [""])

    def test_unclosed_quote_raises(self):
        with self.assertRaises(pl.LaunchArgsError):
            pl.parse_launch_args('"unclosed')
        with self.assertRaises(pl.LaunchArgsError):
            pl.parse_launch_args("'unclosed")

    def test_too_many_tokens_raises(self):
        ok = " ".join(f"a{i}" for i in range(pl.MAX_ARG_TOKENS))
        self.assertEqual(len(pl.parse_launch_args(ok)), pl.MAX_ARG_TOKENS)
        too_many = " ".join(f"a{i}" for i in range(pl.MAX_ARG_TOKENS + 1))
        with self.assertRaises(pl.LaunchArgsError):
            pl.parse_launch_args(too_many)

    def test_format_round_trips_through_the_parser(self):
        tokens = ["--a", "b c", ""]
        self.assertEqual(pl.parse_launch_args(pl.format_launch_args(tokens)),
                         tokens)
        self.assertEqual(pl.format_launch_args([]), "")


class TargetModelTests(unittest.TestCase):
    def test_new_target_id_is_unique_and_prefixed(self):
        first = pl.new_target_id()
        second = pl.new_target_id()
        self.assertTrue(first.startswith("t_"))
        self.assertNotEqual(first, second)

    def test_normalize_name_strips_controls_and_truncates(self):
        self.assertEqual(pl.normalize_name("  Editor \n"), "Editor")
        self.assertEqual(pl.normalize_name("a\r\n\tb"), "ab")
        self.assertEqual(len(pl.normalize_name("x" * 200)),
                         pl.MAX_TARGET_NAME_LEN)
        self.assertEqual(pl.normalize_name(None), "")

    def test_make_target_normalizes_paths_to_forward_slashes(self):
        target = pl.make_target(EXISTING_PROGRAM, name="Program")
        self.assertNotIn("\\", target["path"])
        self.assertTrue(os.path.isabs(target["path"]))
        self.assertEqual(target["args"], "")
        self.assertEqual(target["cwd"], "")

    def test_make_target_derives_a_name_from_the_path(self):
        target = pl.make_target("C:/tools/Code.exe")
        self.assertEqual(target["name"], "Code")

    def test_make_target_keeps_an_explicit_id(self):
        target = pl.make_target(EXISTING_PROGRAM, name="N", target_id="t_keep")
        self.assertEqual(target["id"], "t_keep")

    def test_basename_label_handles_bundles_and_extensions(self):
        self.assertEqual(pl._basename_label("C:/x/Code.exe"), "Code")
        self.assertEqual(pl._basename_label("/Applications/Visual Studio Code.app"),
                         "Visual Studio Code")
        self.assertEqual(pl._basename_label("/usr/bin/foo"), "foo")
        self.assertEqual(pl._basename_label(""), "")

    def test_normalize_targets_is_fault_tolerant(self):
        for bad in ({}, None, "nope", 42, [None, 3, "x"], [{"id": "a"}]):
            with self.subTest(raw=bad):
                self.assertEqual(pl.normalize_targets(bad), [])

    def test_normalize_targets_drops_duplicates_and_fills_names(self):
        raw = [
            {"id": "a", "path": "C:/tools/Code.exe", "name": ""},
            {"id": "a", "path": "C:/tools/Other.exe", "name": "Other"},
            {"id": "b", "path": "C:/tools/Two.exe", "name": "Two"},
        ]
        targets = pl.normalize_targets(raw)
        self.assertEqual([t["id"] for t in targets], ["a", "b"])
        self.assertEqual(targets[0]["name"], "Code")
        self.assertEqual(targets[0]["path"], "C:/tools/Code.exe")

    def test_normalize_targets_accepts_a_tuple(self):
        targets = pl.normalize_targets(
            ({"id": "a", "path": "C:/tools/Code.exe"},))
        self.assertEqual(len(targets), 1)


class ValidateTargetTests(unittest.TestCase):
    def test_rejects_a_non_dict(self):
        self.assertEqual(pl.validate_target(None), "Invalid target")
        self.assertEqual(pl.validate_target([]), "Invalid target")

    def test_requires_a_path(self):
        self.assertEqual(pl.validate_target({"path": "", "name": "N"}),
                         "Program path is required")

    def test_requires_an_absolute_path(self):
        self.assertEqual(
            pl.validate_target({"path": "relative/app.exe", "name": "N"}),
            "Program path must be absolute")

    def test_requires_an_existing_path(self):
        self.assertEqual(
            pl.validate_target({"path": MISSING_PROGRAM, "name": "N"}),
            f"Program not found: {MISSING_PROGRAM}")

    def test_requires_a_name(self):
        self.assertEqual(
            pl.validate_target({"path": EXISTING_PROGRAM, "name": "",
                                "args": "", "cwd": ""}),
            "Name is required")

    def test_rejects_unparseable_arguments(self):
        self.assertEqual(
            pl.validate_target({"path": EXISTING_PROGRAM, "name": "N",
                                "args": '"unclosed', "cwd": ""}),
            "Invalid arguments: unclosed quote")

    def test_rejects_a_missing_working_directory(self):
        self.assertEqual(
            pl.validate_target({"path": EXISTING_PROGRAM, "name": "N",
                                "args": "", "cwd": MISSING_DIR}),
            f"Working directory not found: {MISSING_DIR}")

    def test_accepts_a_complete_target(self):
        self.assertEqual(pl.validate_target(_target()), "")

    def test_accepts_an_existing_working_directory(self):
        self.assertEqual(pl.validate_target(_target(cwd=EXISTING_DIR)), "")


class BuildArgvTests(unittest.TestCase):
    def test_plain_executable_is_started_directly(self):
        argv = pl.build_launch_argv(_target(args="--a b"), platform="linux")
        self.assertEqual(argv, [EXISTING_PROGRAM, "--a", "b"])

    def test_empty_args_produce_a_single_element_argv(self):
        self.assertEqual(pl.build_launch_argv(_target(), platform="win32"),
                         [EXISTING_PROGRAM])

    def test_macos_bundle_goes_through_open(self):
        target = _target(path="/Applications/Visual Studio Code.app",
                         args="--new-window")
        with patch("core.program_launcher.os.path.isdir", return_value=True):
            argv = pl.build_launch_argv(target, platform="darwin")
        self.assertEqual(argv, ["open", "-a", target["path"],
                                "--args", "--new-window"])

    def test_macos_bundle_without_args_omits_the_args_separator(self):
        target = _target(path="/Applications/Code.app")
        with patch("core.program_launcher.os.path.isdir", return_value=True):
            argv = pl.build_launch_argv(target, platform="darwin")
        self.assertEqual(argv, ["open", "-a", "/Applications/Code.app"])

    def test_macos_non_bundle_is_started_directly(self):
        argv = pl.build_launch_argv(_target(path="/usr/local/bin/foo"),
                                    platform="darwin")
        self.assertEqual(argv, ["/usr/local/bin/foo"])

    def test_bundle_detection_requires_darwin(self):
        target = pl.is_macos_bundle
        with patch("core.program_launcher.os.path.isdir", return_value=True):
            self.assertTrue(target("/Applications/Code.app", "darwin"))
            self.assertFalse(target("/Applications/Code.app", "win32"))
        with patch("core.program_launcher.os.path.isdir", return_value=False):
            self.assertFalse(target("/Applications/Code.app", "darwin"))


class ResolveCwdTests(unittest.TestCase):
    def test_blank_cwd_falls_back_to_the_program_folder(self):
        self.assertEqual(pl.resolve_launch_cwd(_target()), EXISTING_DIR)

    def test_existing_cwd_wins(self):
        self.assertEqual(pl.resolve_launch_cwd(_target(cwd=EXISTING_DIR)),
                         EXISTING_DIR)

    def test_missing_cwd_falls_back_to_the_program_folder(self):
        self.assertEqual(pl.resolve_launch_cwd(_target(cwd=MISSING_DIR)),
                         EXISTING_DIR)

    def test_macos_bundle_uses_the_enclosing_folder(self):
        target = _target(path="/Applications/Code.app")
        with patch("core.program_launcher.os.path.isdir", return_value=True):
            self.assertEqual(pl.resolve_launch_cwd(target), "/Applications")

    def test_non_dict_target_is_safe(self):
        self.assertEqual(pl.resolve_launch_cwd(None), "")


class LaunchTargetTests(unittest.TestCase):
    def test_invalid_target_never_reaches_popen(self):
        with patch("core.program_launcher.subprocess.Popen") as popen:
            ok, message = pl.launch_target(_target(path=MISSING_PROGRAM))
        self.assertFalse(ok)
        self.assertTrue(message.startswith("Program not found"))
        popen.assert_not_called()

    def test_success_returns_the_display_name(self):
        process = MagicMock()
        process.poll.return_value = None
        with patch("core.program_launcher.subprocess.Popen",
                   return_value=process) as popen:
            ok, message = pl.launch_target(_target(name="My Editor"))
        self.assertTrue(ok)
        self.assertEqual(message, "My Editor")
        argv = popen.call_args.args[0]
        self.assertIsInstance(argv, list)
        self.assertFalse(popen.call_args.kwargs["shell"])

    def test_arguments_are_passed_as_separate_argv_entries(self):
        process = MagicMock()
        with patch("core.program_launcher.subprocess.Popen",
                   return_value=process) as popen:
            pl.launch_target(_target(args="--new-window"))
        self.assertEqual(popen.call_args.args[0],
                         [EXISTING_PROGRAM, "--new-window"])

    def test_working_directory_is_forwarded(self):
        process = MagicMock()
        with patch("core.program_launcher.subprocess.Popen",
                   return_value=process) as popen:
            pl.launch_target(_target(cwd=EXISTING_DIR))
        self.assertEqual(popen.call_args.kwargs["cwd"], EXISTING_DIR)

    def test_missing_program_is_reported_not_raised(self):
        with patch("core.program_launcher.subprocess.Popen",
                   side_effect=FileNotFoundError):
            ok, message = pl.launch_target(_target())
        self.assertFalse(ok)
        self.assertEqual(message, f"Program not found: {EXISTING_PROGRAM}")

    def test_permission_failure_is_reported_not_raised(self):
        with patch("core.program_launcher.subprocess.Popen",
                   side_effect=PermissionError):
            ok, message = pl.launch_target(_target())
        self.assertFalse(ok)
        self.assertEqual(message, f"Permission denied: {EXISTING_PROGRAM}")

    def test_other_os_error_is_reported_not_raised(self):
        with patch("core.program_launcher.subprocess.Popen",
                   side_effect=OSError("boom")):
            ok, message = pl.launch_target(_target())
        self.assertFalse(ok)
        self.assertEqual(message, "Launch failed: boom")

    def test_recent_processes_are_pruned_when_they_exit(self):
        finished = MagicMock()
        finished.poll.return_value = 0
        with patch("core.program_launcher.subprocess.Popen",
                   return_value=finished):
            pl.launch_target(_target())
            pl.launch_target(_target())
        self.assertLessEqual(len(pl._recent_processes), 2)


class NoToolkitDependencyTests(unittest.TestCase):
    def test_module_has_no_toolkit_imports(self):
        source = pl.__file__
        with open(source, encoding="utf-8") as handle:
            text = handle.read()
        self.assertNotIn("PySide6", text)
        self.assertNotIn("Qt", text)

    def test_module_never_uses_a_shell(self):
        with open(pl.__file__, encoding="utf-8") as handle:
            text = handle.read()
        self.assertNotIn("shell=True", text)
        self.assertNotIn("os.system", text)
        self.assertNotIn("subprocess.run(", text)


if __name__ == "__main__":
    unittest.main()
