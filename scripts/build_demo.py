#!/usr/bin/env python3
"""Build an allowlisted static demo; no server, credential or image API is used."""

import ast
import importlib.util
import json
from pathlib import Path
import re
import shutil
import tempfile


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "demo" / "dist"
STATIC_FILES = ("index.html", "app.js", "styles.css", "assets/sample-dog-walk.png")
PACKAGE_FILES = frozenset(STATIC_FILES + ("demo-adapter.js", "prompt-config.json"))
CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self'; "
    "img-src 'self' data:; connect-src 'self'; base-uri 'none'; "
    "object-src 'none'; form-action 'none'"
)


def _prompt_module():
    spec = importlib.util.spec_from_file_location("doodle_demo_prompt_reference", ROOT / "prompt_builder.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fixed_model():
    # Read only the literal model constant; do not import or run the HTTP server.
    source = ast.parse((ROOT / "app.py").read_text(encoding="utf-8"))
    for node in source.body:
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "MODEL" for target in node.targets):
            model = ast.literal_eval(node.value)
            if isinstance(model, str) and model:
                return model
    raise RuntimeError("The fixed model name was not found.")


def prompt_config():
    module = _prompt_module()
    reference = module.REFERENCE_PATH.read_text(encoding="utf-8")
    if module.build_prompt() != reference:
        raise RuntimeError("The default prompt does not match the reviewed reference.")
    return {
        "version": 1, "mode": "demo", "configured": False, "model": _fixed_model(),
        "reference": reference,
        "defaults": {"scene": module.DEFAULT_SCENE, "objects": module.DEFAULT_OBJECTS},
        "limits": dict(module.LIMITS),
    }


def demo_html(source):
    match = re.search(r"<html\b[^>]*>", source, re.IGNORECASE)
    if not match:
        raise RuntimeError("The static page needs an html element.")
    tag = re.sub(r"\sdata-mode\s*=\s*(['\"]).*?\1", "", match.group(0), flags=re.IGNORECASE)
    source = source[:match.start()] + tag[:-1] + ' data-mode="demo">' + source[match.end():]
    # Source pages also run locally. Convert only their known root-relative assets.
    for path in ("styles.css", "app.js", "assets/sample-dog-walk.png"):
        source = source.replace('"/' + path + '"', '"./' + path + '"')
        source = source.replace("'/" + path + "'", "'./" + path + "'")
    source = source.replace('href="/"', 'href="./"').replace("href='/'", "href='./'")
    app_script = re.search(r"<script\b[^>]*\bsrc\s*=\s*(['\"])(?:\./)?app\.js\1[^>]*>\s*</script>", source, re.IGNORECASE)
    if not app_script:
        raise RuntimeError("The static page needs its local app.js script.")
    adapter = '<script src="./demo-adapter.js" defer></script>\n    '
    source = source[:app_script.start()] + adapter + source[app_script.start():]
    head = re.search(r"<head\b[^>]*>", source, re.IGNORECASE)
    if not head:
        raise RuntimeError("The static page needs a head element.")
    meta = '\n    <meta http-equiv="Content-Security-Policy" content="' + CSP + '">'
    return source[:head.end()] + meta + source[head.end():]


def _check_existing_output(destination):
    if destination.is_symlink() or (destination.exists() and not destination.is_dir()):
        raise RuntimeError("The demo output must be a normal directory.")
    if destination.exists():
        for path in destination.rglob("*"):
            if path.is_symlink() or (path.is_file() and path.relative_to(destination).as_posix() not in PACKAGE_FILES):
                raise RuntimeError("The demo output contains an unexpected file; move it before rebuilding.")


def build_demo(destination=None):
    """Write only six public files. destination is an optional test-only directory."""
    destination = Path(destination) if destination is not None else OUTPUT
    _check_existing_output(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".doodle-demo-build-", dir=str(destination.parent)) as temporary:
        stage = Path(temporary) / "dist"
        stage.mkdir()
        for name in STATIC_FILES:
            source = ROOT / "static" / name
            target = stage / name
            target.parent.mkdir(parents=True, exist_ok=True)
            if name == "index.html":
                target.write_text(demo_html(source.read_text(encoding="utf-8")), encoding="utf-8")
            else:
                shutil.copyfile(source, target)
        shutil.copyfile(ROOT / "demo" / "demo-adapter.js", stage / "demo-adapter.js")
        (stage / "prompt-config.json").write_text(
            json.dumps(prompt_config(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        # The existing output was checked against the build-owned allowlist above.
        if destination.exists():
            backup = Path(temporary) / "previous-dist"
            destination.rename(backup)
            try:
                stage.rename(destination)
            except OSError:
                backup.rename(destination)
                raise
        else:
            stage.rename(destination)
    return destination


if __name__ == "__main__":
    build_demo()
    print("Built demo/dist: %d static files; browser-only prompt preview, no image service." % len(PACKAGE_FILES))
