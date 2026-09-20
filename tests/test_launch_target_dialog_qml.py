"""Source-level guards for the program launch target dialog.

The dialog must stay inside the QML import surface the PyInstaller specs keep
(an unmapped ``import Qt...`` compiles fine from a source checkout and then
fails inside the packaged build), follow the modal conventions the other
overlays use, and keep every user-facing string in the translation table
instead of hard-coding it.
"""

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
DIALOG_PATH = ROOT / "ui" / "qml" / "LaunchTargetDialog.qml"
DIALOG_QML = DIALOG_PATH.read_text(encoding="utf-8")

# Mirrors QML_IMPORT_TO_QT_LIBS in test_spec_coverage.py: the specs already
# ship these, so importing one of them needs no spec change.
MAPPED_IMPORTS = {
    "QtQml",
    "QtQuick",
    "QtQuick.Window",
    "QtQuick.Layouts",
    "QtQuick.Effects",
    "QtQuick.Shapes",
    "QtQuick.Controls",
    "QtQuick.Controls.Material",
}


class LaunchTargetDialogQmlTests(unittest.TestCase):
    def test_dialog_exists(self):
        self.assertTrue(DIALOG_PATH.is_file())

    def test_only_already_mapped_qml_imports(self):
        imports = re.findall(r"^import\s+(Qt[\w.]*)", DIALOG_QML, re.MULTILINE)
        self.assertTrue(imports)
        unmapped = sorted(set(imports) - MAPPED_IMPORTS)
        self.assertFalse(
            unmapped,
            f"{unmapped} needs a spec and coverage-map update; prefer the "
            f"imports the other dialogs already use",
        )

    def test_theme_module_is_imported_for_the_palette(self):
        self.assertIn('import "Theme.js" as Theme', DIALOG_QML)

    def test_modal_overlay_conventions(self):
        for token in ('anchors.fill: parent', 'color: "#80000000"', 'z: 100'):
            with self.subTest(token=token):
                self.assertIn(token, DIALOG_QML)

    def test_exposes_the_expected_entry_points(self):
        for token in ("function open()", "function openNew()",
                      "function openEdit(", "function close()"):
            with self.subTest(token=token):
                self.assertIn(token, DIALOG_QML)

    def test_emits_saved_and_cancelled(self):
        self.assertIn("signal saved(string targetId)", DIALOG_QML)
        self.assertIn("signal cancelled()", DIALOG_QML)

    def test_uses_the_shared_theme_palette_and_font(self):
        self.assertIn("Theme.palette(uiState.darkMode)", DIALOG_QML)
        self.assertIn("uiState.fontFamily", DIALOG_QML)

    def test_text_comes_from_the_translation_table(self):
        self.assertIn('property var s: lm.strings', DIALOG_QML)
        self.assertIn('s["launch_target.', DIALOG_QML)

    def test_no_hard_coded_native_text(self):
        # Every string the user reads lives in ui/locale_manager.py, written
        # with \uXXXX escapes there; nothing native belongs in the QML.
        self.assertIsNone(re.search(r"[\u3000-\u9fff\uff00-\uffef]", DIALOG_QML))

    def test_arguments_are_validated_before_saving(self):
        self.assertIn("backend.validateLaunchArgs(", DIALOG_QML)
        self.assertIn("backend.validateLaunchTarget(", DIALOG_QML)

    def test_arguments_are_validated_while_typing(self):
        # The inline error must react to typing, not only to pressing save.
        args_block = DIALOG_QML.split("id: argsField", 1)[1][:500]
        self.assertIn("validateLaunchArgs", args_block)

    def test_path_and_directory_pickers_are_used(self):
        self.assertIn("backend.browseLaunchTargetPath()", DIALOG_QML)
        self.assertIn("backend.browseLaunchDirectory()", DIALOG_QML)

    def test_new_target_suggests_a_name_from_the_path(self):
        self.assertIn("backend.suggestLaunchTargetName(", DIALOG_QML)

    def test_backend_api_surface_matches_the_dialog(self):
        backend = (ROOT / "ui" / "backend.py").read_text(encoding="utf-8")
        for slot in ("addLaunchTarget", "updateLaunchTarget",
                     "removeLaunchTarget", "validateLaunchTarget",
                     "validateLaunchArgs", "launchTargetName",
                     "suggestLaunchTargetName", "browseLaunchTargetPath",
                     "browseLaunchDirectory", "findLaunchTargetForLaunch"):
            with self.subTest(slot=slot):
                self.assertIn(f"def {slot}(", backend)

    def test_translation_keys_used_by_the_dialog_exist(self):
        locale = (ROOT / "ui" / "locale_manager.py").read_text(encoding="utf-8")
        used = sorted(set(re.findall(r's\["(launch_target\.[\w.]+)"\]',
                                     DIALOG_QML)))
        self.assertTrue(used)
        for key in used:
            with self.subTest(key=key):
                # Three tables: English, Simplified and Traditional Chinese.
                self.assertEqual(locale.count(f'"{key}"'), 3)

    def test_registered_targets_are_listed_for_management(self):
        self.assertIn("backend.launchTargets", DIALOG_QML)
        self.assertIn("dialog.openEdit(modelData.id)", DIALOG_QML)
        self.assertIn("dialog.removeTarget(modelData.id)", DIALOG_QML)


if __name__ == "__main__":
    unittest.main()
