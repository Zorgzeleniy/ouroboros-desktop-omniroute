import os
import pathlib
import sys
import unittest


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

REPO = pathlib.Path(__file__).resolve().parents[1]


class TestSettingsUiGuards(unittest.TestCase):
    def _read_settings_sources(self):
        return {
            "settings": (REPO / "web/modules/settings.js").read_text(encoding="utf-8"),
            "settings_ui": (REPO / "web/modules/settings_ui.js").read_text(encoding="utf-8"),
            "settings_controls": (REPO / "web/modules/settings_controls.js").read_text(encoding="utf-8"),
            "settings_catalog": (REPO / "web/modules/settings_catalog.js").read_text(encoding="utf-8"),
        }

    def test_save_checks_http_status(self):
        source = self._read_settings_sources()["settings"]
        self.assertIn("if (!resp.ok) throw new Error(data.error || `HTTP ${resp.status}`);", source)

    def test_save_does_not_overwrite_masked_secrets(self):
        source = self._read_settings_sources()["settings"]
        self.assertIn("function collectSecretValue(id, body) {", source)
        self.assertIn("if (input.dataset.forceClear === '1') {", source)
        self.assertIn("if (value && !value.includes('...')) body[settingKey] = value;", source)

    def test_masked_secret_inputs_clear_on_focus(self):
        source = self._read_settings_sources()["settings_ui"]
        self.assertIn("if (input.value.includes('...')) input.value = '';", source)
        self.assertIn("target.dataset.forceClear = '1';", source)

    def test_models_section_explains_local_switching(self):
        source = self._read_settings_sources()["settings_ui"]
        self.assertIn("These fields are cloud model IDs.", source)
        self.assertIn("through the GGUF server configured above.", source)

    def test_strange_settings_have_inline_explainer_copy(self):
        source = self._read_settings_sources()["settings_ui"]
        self.assertIn("Adds a password wall only for non-localhost browser and API access.", source)
        self.assertIn("still runs review but lets you decide", source)
        self.assertIn("Backward-compatibility escape hatch for older installs.", source)

    def test_settings_tabs_are_single_row_scrollable(self):
        css = (REPO / "web/settings.css").read_text(encoding="utf-8")
        self.assertIn("flex-wrap: nowrap;", css)
        self.assertIn("overflow-x: auto;", css)

    def test_save_reloads_settings_after_success(self):
        source = self._read_settings_sources()["settings"]
        self.assertIn("await loadSettings();", source)

    def test_model_picker_uses_single_custom_dropdown(self):
        sources = self._read_settings_sources()
        self.assertNotIn('list="settings-model-catalog"', sources["settings_ui"])
        self.assertNotIn('<datalist id="settings-model-catalog">', sources["settings_ui"])
        self.assertIn('autocomplete="off"', sources["settings_ui"])
        self.assertIn('spellcheck="false"', sources["settings_ui"])
        self.assertIn("closeAll();", sources["settings_controls"])
        self.assertIn("closeAll(picker);", sources["settings_controls"])
        self.assertIn("broadcastCatalog(items);", sources["settings_catalog"])
