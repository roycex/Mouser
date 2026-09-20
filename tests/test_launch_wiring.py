"""Source-level guards for the program-launch feature wiring.

Three failure modes are invisible to a plain unit test yet fatal in practice:

* ``core.key_simulator`` has a separate ``execute_action`` per platform. Miss
  one and that platform's buttons silently do nothing for launch actions.
* ``ui/qml/MousePage.qml`` repeats the action picker ten times. Miss one and
  the "Add Program…" entry cannot be reached from that surface.
* ``ProgramLaunchController`` must deliver its signal through a queued
  connection. Without it the process start runs on the mouse-hook thread and
  the pointer stalls while the program boots.

Each guard counts occurrences in the real files, so it fails loudly when a
future edit drops one.
"""

from pathlib import Path
import re
import unittest

from core import config


ROOT = Path(__file__).resolve().parents[1]


def _read(*parts):
    return (ROOT.joinpath(*parts)).read_text(encoding="utf-8")


class KeySimulatorWiringTests(unittest.TestCase):
    """Every platform branch dispatches launch actions (RK-01)."""

    def setUp(self):
        self.source = _read("core", "key_simulator.py")

    def test_all_platform_branches_handle_launch_actions(self):
        # 1 definition + one call in each of the win32/darwin/linux branches.
        self.assertEqual(self.source.count("request_launch_action"), 4)

    def test_unsupported_platform_stub_is_left_alone(self):
        # The trailing `else:` stub on unsupported platforms must keep its
        # empty implementation; it is not a place to add dispatch.
        self.assertIn("def execute_action(action_id): pass", self.source)

    def test_hook_thread_never_starts_a_process_inline(self):
        # The whole point of the handler indirection: this module must not
        # reach the process-spawning machinery itself.
        self.assertNotIn("subprocess", self.source)

    def test_launch_helper_mirrors_the_screenshot_helper(self):
        for token in ("_launch_action_handler = None",
                      "def set_launch_action_handler(",
                      "def request_launch_action(",
                      "except Exception as exc:"):
            self.assertIn(token, self.source)

    def test_launch_dispatch_follows_the_screenshot_dispatch(self):
        matches = list(re.finditer(
            r"if request_screenshot_action\(action_id\):\s*\n\s*return\s*\n"
            r"(\s*)if request_launch_action\(action_id\):", self.source))
        self.assertEqual(len(matches), 3)
        for match in matches:
            self.assertTrue(match.group(1))


class ControllerWiringTests(unittest.TestCase):
    """The controller hands off instead of blocking the hook thread (RK-03)."""

    def setUp(self):
        self.source = _read("ui", "program_launch.py")

    def test_queued_connection_is_explicit(self):
        self.assertIn("Qt.ConnectionType.QueuedConnection", self.source)

    def test_request_action_only_emits(self):
        body = self.source.split("def request_action(", 1)[1].split(
            "def ", 1)[0]
        self.assertIn("emit(action_id)", body)
        for token in ("subprocess", "Popen", "time.sleep", "open("):
            self.assertNotIn(token, body)

    def test_missing_target_is_reported(self):
        self.assertIn("Launch target is missing", self.source)

    def test_single_controller_without_platform_fork(self):
        self.assertNotIn("sys.platform", self.source)


class LaunchModuleSafetyTests(unittest.TestCase):
    """The launcher stays toolkit-free and shell-free (R-019 / R-022)."""

    def setUp(self):
        self.source = _read("core", "program_launcher.py")

    def test_no_toolkit_imports(self):
        self.assertNotIn("PySide6", self.source)
        self.assertNotIn("Qt", self.source)

    def test_no_shell_execution(self):
        self.assertNotIn("shell=True", self.source)
        self.assertNotIn("os.system", self.source)
        self.assertNotIn("subprocess.run(", self.source)


class ConfigMigrationWiringTests(unittest.TestCase):
    """The new settings key is a list and the version bump rode along (RK-04)."""

    def test_default_launch_targets_is_an_empty_list(self):
        self.assertEqual(config.DEFAULT_CONFIG["settings"]["launch_targets"], [])
        self.assertEqual(config.DEFAULT_CONFIG["version"], 12)

    def test_v11_config_migrates_without_losing_data(self):
        legacy = {
            "version": 11,
            "settings": {"dpi": 1234},
            "profiles": {"default": {"mappings": {"middle": "none"}}},
        }
        migrated = config._migrate(legacy)
        self.assertEqual(migrated["version"], config.DEFAULT_CONFIG["version"])
        self.assertEqual(migrated["settings"]["launch_targets"], [])
        self.assertEqual(migrated["settings"]["dpi"], 1234)
        self.assertEqual(migrated["profiles"]["default"]["mappings"]["middle"],
                         "none")

    def test_a_corrupt_launch_targets_value_is_repaired(self):
        legacy = {"version": 11, "settings": {"launch_targets": {"oops": 1}}}
        migrated = config._migrate(legacy)
        self.assertEqual(migrated["settings"]["launch_targets"], [])


class PickerWiringTests(unittest.TestCase):
    """Every action picker can reach the dialog (RK-02)."""

    def setUp(self):
        self.source = _read("ui", "qml", "MousePage.qml")

    def test_every_picker_intercepts_the_sentinel(self):
        self.assertGreaterEqual(self.source.count('"__launch__"'), 10)

    def test_sentinel_lookup_does_not_assume_a_position(self):
        # The old length-based fallback would highlight the wrong sentinel now
        # that two of them exist. Checked against code only: the explanatory
        # comment above the helpers legitimately quotes the removed expression.
        code = "\n".join(line.split("//", 1)[0]
                         for line in self.source.splitlines())
        self.assertNotIn("actions.length - 1", code)
        self.assertIn('sentinelIndex("__custom__")', code)
        self.assertIn('sentinelIndex("__launch__")', code)

    def test_dialog_is_instantiated(self):
        self.assertIn("LaunchTargetDialog {", self.source)
        self.assertIn("id: launchTargetDialog", self.source)


class MainEntryWiringTests(unittest.TestCase):
    """The controller is created, kept alive and registered (RK-06)."""

    def setUp(self):
        self.source = _read("main_qml.py")

    def test_controller_is_wired_and_referenced(self):
        self.assertIn("set_launch_action_handler(", self.source)
        self.assertIn("app._mouser_program_launcher", self.source)

    def test_handler_is_registered_before_the_qml_engine(self):
        self.assertLess(self.source.index("set_launch_action_handler("),
                        self.source.index("qml_engine = QQmlApplicationEngine("))


if __name__ == "__main__":
    unittest.main()
