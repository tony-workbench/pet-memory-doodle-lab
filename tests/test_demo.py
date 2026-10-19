"""Static-package checks and Python/browser prompt parity (Node is test-only)."""

import hashlib
from html.parser import HTMLParser
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from urllib.parse import urljoin, urlparse


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import prompt_builder

SPEC = importlib.util.spec_from_file_location("build_doodle_demo", ROOT / "scripts" / "build_demo.py")
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)
NODE = shutil.which("node")


class Resources(HTMLParser):
    def __init__(self):
        super().__init__()
        self.scripts = []
        self.resources = []
        self.mode = None
        self.csp = None

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "html":
            self.mode = values.get("data-mode")
        if tag == "script":
            self.scripts.append(values.get("src"))
            self.resources.append(values.get("src"))
        if tag == "link" and values.get("rel") == "stylesheet":
            self.resources.append(values.get("href"))
        if tag == "img":
            self.resources.append(values.get("src"))
        if tag == "meta" and values.get("http-equiv", "").lower() == "content-security-policy":
            self.csp = values.get("content")


RUN_ADAPTER = r"""
const fs = require('node:fs');
const vm = require('node:vm');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const calls = [];
const window = {};
const context = vm.createContext({window, URL,
  document: {currentScript: {src: 'https://example.test/repository/nested/demo-adapter.js'}, baseURI: 'https://example.test/repository/nested/index.html'},
  fetch: async (url, options) => { calls.push({url, options}); return {ok: true, json: async () => input.config}; }
});
vm.runInContext(fs.readFileSync(input.adapter, 'utf8'), context);
(async () => {
  const first = await window.DoodleDemo.config();
  const untouched = first.defaults.scene;
  first.defaults.scene = 'mutated-by-caller';
  first.limits.scene = 9999;
  const again = await window.DoodleDemo.config();
  const results = [];
  for (const payload of input.cases) {
    try { results.push({prompt: (await window.DoodleDemo.prompt(payload)).prompt}); }
    catch (error) { results.push({error: error.message}); }
  }
  process.stdout.write(JSON.stringify({results, calls, config: again,
    isolated: again.defaults.scene === untouched && again.limits.scene === 600,
    exports: Object.keys(window.DoodleDemo)}));
})().catch(error => { process.stderr.write(String(error)); process.exitCode = 1; });
"""


class StaticPackageTests(unittest.TestCase):
    def test_config_uses_canonical_reference_and_constants(self):
        config = builder.prompt_config()
        self.assertEqual(config["reference"].encode("utf-8"), prompt_builder.REFERENCE_PATH.read_bytes())
        self.assertEqual(config["defaults"], {"scene": prompt_builder.DEFAULT_SCENE, "objects": prompt_builder.DEFAULT_OBJECTS})
        self.assertEqual(config["limits"], prompt_builder.LIMITS)
        self.assertEqual(config["mode"], "demo")
        self.assertFalse(config["configured"])
        self.assertNotIn("apiKey", config)
        self.assertNotIn("csrfToken", config)

    def test_allowlisted_package_relative_resources_and_script_order(self):
        with tempfile.TemporaryDirectory() as directory:
            output = builder.build_demo(Path(directory) / "dist")
            files = {path.relative_to(output).as_posix() for path in output.rglob("*") if path.is_file()}
            self.assertEqual(files, builder.PACKAGE_FILES)
            parsed = Resources()
            parsed.feed((output / "index.html").read_text(encoding="utf-8"))
            self.assertEqual(parsed.mode, "demo")
            self.assertIn("default-src 'none'", parsed.csp)
            self.assertEqual(len(parsed.scripts), 2)
            self.assertEqual(Path(parsed.scripts[0]).name, "demo-adapter.js")
            self.assertEqual(Path(parsed.scripts[1]).name, "app.js")
            base = "https://example.test/repository/nested/"
            for resource in parsed.resources:
                self.assertTrue(resource)
                self.assertFalse(resource.startswith("/"), resource)
                self.assertFalse(urlparse(resource).scheme, resource)
                resolved = urljoin(base, resource)
                self.assertTrue(resolved.startswith(base), resolved)
                self.assertTrue((output / resource).is_file(), resource)
            image = "assets/sample-dog-walk.png"
            self.assertEqual(hashlib.sha256((output / image).read_bytes()).digest(),
                             hashlib.sha256((ROOT / "static" / image).read_bytes()).digest())
            self.assertEqual((output / "app.js").read_bytes(), (ROOT / "static" / "app.js").read_bytes())

    def test_package_has_no_server_source_private_paths_keys_or_loopback_urls(self):
        with tempfile.TemporaryDirectory() as directory:
            output = builder.build_demo(Path(directory) / "dist")
            for path in output.rglob("*"):
                if not path.is_file() or path.suffix == ".png":
                    continue
                text = path.read_text(encoding="utf-8")
                self.assertNotRegex(text, r"(?:/Users/|/home/|[A-Za-z]:\\Users\\)")
                self.assertNotRegex(text, r"https?://(?:localhost|127\.0\.0\.1|\[::1\])(?::\d+)?")
                self.assertNotRegex(text, r"sk-[A-Za-z0-9_-]{16,}")
            self.assertFalse(any(path.suffix in (".py", ".pem", ".key") for path in output.rglob("*")))
            self.assertFalse((output / ".env").exists())

    def test_rebuild_is_deterministic_and_preserves_unexpected_files(self):
        with tempfile.TemporaryDirectory() as directory:
            output = builder.build_demo(Path(directory) / "dist")
            before = {path.relative_to(output).as_posix(): path.read_bytes() for path in output.rglob("*") if path.is_file()}
            builder.build_demo(output)
            after = {path.relative_to(output).as_posix(): path.read_bytes() for path in output.rglob("*") if path.is_file()}
            self.assertEqual(before, after)
            (output / "user-note.txt").write_text("keep this")
            with self.assertRaisesRegex(RuntimeError, "unexpected"):
                builder.build_demo(output)
            self.assertEqual((output / "user-note.txt").read_text(), "keep this")

    def test_existing_symlink_output_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "real"
            target.mkdir()
            destination = Path(directory) / "dist"
            destination.symlink_to(target, target_is_directory=True)
            with self.assertRaisesRegex(RuntimeError, "normal directory"):
                builder.build_demo(destination)


@unittest.skipUnless(NODE, "Node is needed only for browser/Python parity tests, not to build or run the demo")
class AdapterParityTests(unittest.TestCase):
    def run_cases(self, cases):
        result = subprocess.run(
            [NODE, "-e", RUN_ADAPTER],
            input=json.dumps({"config": builder.prompt_config(), "adapter": str(ROOT / "demo" / "demo-adapter.js"), "cases": cases}),
            text=True, capture_output=True, timeout=10, check=True,
        )
        return json.loads(result.stdout)

    def assert_python_parity(self, cases):
        actual = self.run_cases(cases)
        for payload, result in zip(cases, actual["results"]):
            try:
                prompt_builder.validate_input(payload)
                expected = {"prompt": prompt_builder.build_prompt(payload)}
            except prompt_builder.InputError as error:
                expected = {"error": str(error)}
            self.assertEqual(result, expected, repr(payload)[:150])
        return actual

    def test_default_custom_chinese_and_embedded_reference_parity(self):
        actual = self.assert_python_parity([
            {}, {"scene": prompt_builder.DEFAULT_SCENE, "objects": prompt_builder.DEFAULT_OBJECTS},
            {"scene": "a person reads beside a small cat", "objects": "one person, one cat and a book"},
            {"scene": "我坐在地上读书，小猫趴在摊开的书旁边。", "objects": "一个简笔人物、一只小猫、一本书"},
            {"scene": prompt_builder.DEFAULT_OBJECTS, "objects": "one cup"},
        ])
        self.assertEqual(actual["results"][0]["prompt"].encode(), prompt_builder.REFERENCE_PATH.read_bytes())
        self.assertNotIn("The dog is", actual["results"][2]["prompt"])
        self.assertIn("Any pet in the scene", actual["results"][2]["prompt"])

    def test_validation_limits_controls_unicode_and_unknown_fields_parity(self):
        self.assert_python_parity([
            None, [], "text", {"scene": ""}, {"objects": "  "}, {"scene": 3}, {"objects": False},
            {"scene": "s" * 600}, {"scene": "s" * 601}, {"objects": "物" * 300}, {"objects": "物" * 301},
            {"scene": "😀" * 600}, {"scene": "😀" * 601},
            {"scene": "before\x00after"}, {"objects": "a\x7fb"}, {"scene": "bad\ud800text"}, {"objects": "bad\udfff"},
            {"scene": "\u0085\x1c  a cat  \u0085\x1c"}, {"scene": "\ufeff"},
            {"scene": "a\nb\tc"}, {"model": "anything"}, {"apiKey": "fake"}, {"__proto__": "no"},
        ])

    def test_adapter_fetches_only_one_static_configuration_and_isolates_return_values(self):
        actual = self.run_cases([{}, {"scene": "PRIVATE_DIARY_DO_NOT_SEND", "objects": "one cat"}])
        self.assertEqual(len(actual["calls"]), 1)
        call = actual["calls"][0]
        self.assertEqual(call["url"], "https://example.test/repository/nested/prompt-config.json")
        self.assertEqual(call["options"], {"credentials": "omit", "mode": "same-origin", "cache": "no-store"})
        self.assertNotIn("PRIVATE_DIARY_DO_NOT_SEND", json.dumps(call))
        self.assertEqual(actual["exports"], ["config", "prompt"])
        self.assertTrue(actual["isolated"])
        self.assertEqual(actual["config"]["mode"], "demo")
        self.assertFalse(actual["config"]["configured"])
        self.assertIsNone(actual["config"]["csrfToken"])


if __name__ == "__main__":
    unittest.main()
