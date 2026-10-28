"""Real loopback HTTP tests; the image provider is always a local test double."""

import base64
from contextlib import contextmanager, redirect_stderr, redirect_stdout
import http.client
import io
import json
from pathlib import Path
import socket
import sys
import tempfile
import threading
import unittest
from unittest import mock
import urllib.error

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import app
import prompt_builder


# A complete 1x1 PNG used only to test the binary response contract.
PNG_B64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aP9sAAAAASUVORK5CYII="
GOOD_RESPONSE = json.dumps({"data": [{"b64_json": PNG_B64}]}).encode()


@contextmanager
def running_server(api_key="test-key-never-sent", provider=None, cooldown=0):
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / "assets").mkdir()
        (root / "index.html").write_text("<!doctype html><h1>Local test</h1>")
        (root / "app.js").write_text("'use strict';")
        (root / "styles.css").write_text("body{color:black}")
        (root / "assets" / "sample-dog-walk.png").write_bytes(base64.b64decode(PNG_B64))
        (root / "not-allowlisted.txt").write_text("must not be served")
        server = app.LabServer(port=0, api_key=api_key, static_root=root,
                               provider=provider or (lambda prompt, key: GOOD_RESPONSE),
                               cooldown_seconds=cooldown)
        thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
        thread.start()
        try:
            yield server
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


def request(server, method="GET", path="/api/config", payload=None, headers=None, raw=None):
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=4)
    authority = "127.0.0.1:%d" % server.server_port
    values = {"Host": authority}
    if method == "POST":
        values.update({"Origin": "http://" + authority, "X-CSRF-Token": server.csrf_token,
                       "Content-Type": "application/json"})
        if raw is None:
            raw = json.dumps({} if payload is None else payload).encode()
    if headers:
        for key, value in headers.items():
            if value is None:
                values.pop(key, None)
            else:
                values[key] = value
    connection.request(method, path, body=raw, headers=values)
    response = connection.getresponse()
    result = (response.status, dict(response.getheaders()), response.read())
    connection.close()
    return result


class PromptTests(unittest.TestCase):
    def test_default_exact_reference_bytes(self):
        reference = prompt_builder.REFERENCE_PATH.read_bytes()
        self.assertEqual(prompt_builder.build_prompt().encode("utf-8"), reference)
        self.assertEqual(prompt_builder.build_prompt({"scene": prompt_builder.DEFAULT_SCENE,
                                                    "objects": prompt_builder.DEFAULT_OBJECTS}).encode(), reference)

    def test_custom_scene_and_objects_replace_only_their_spans(self):
        text = prompt_builder.build_prompt({"scene": "a person feeds a cat", "objects": "one person and one cat"})
        self.assertIn("depicting a person feeds a cat.", text)
        self.assertIn("only one person and one cat.", text)
        self.assertNotIn(prompt_builder.DEFAULT_SCENE, text)
        self.assertNotIn("The dog is", text)
        self.assertIn("Any pet in the scene", text)

    def test_inserted_default_phrase_is_not_reprocessed(self):
        text = prompt_builder.build_prompt({"scene": prompt_builder.DEFAULT_OBJECTS, "objects": "a cup"})
        self.assertIn("depicting " + prompt_builder.DEFAULT_OBJECTS + ".", text)
        self.assertIn("only a cup.", text)

    def test_input_limits_types_controls_and_allowlist(self):
        bad = [None, [], {"scene": ""}, {"objects": " "}, {"scene": 4}, {"objects": None},
               {"scene": "s" * 601}, {"objects": "o" * 301}, {"scene": "bad\x00text"},
               {"scene": "bad\ud800text"}, {"objects": "bad\udffftext"},
               {"model": "other-model"}, {"base_url": "http://evil.invalid"}, {"apiKey": "secret"}]
        for value in bad:
            with self.subTest(value=str(value)[:30]), self.assertRaises(prompt_builder.InputError):
                prompt_builder.validate_input(value)
        self.assertTrue(prompt_builder.build_prompt({"scene": "中" * 600, "objects": "物" * 300}))


class HTTPTests(unittest.TestCase):
    def test_real_input_to_prompt_path_and_config(self):
        with running_server(api_key="") as server:
            status, headers, raw = request(server)
            config = json.loads(raw)
            self.assertEqual(status, 200)
            self.assertFalse(config["configured"])
            self.assertEqual(config["model"], "gpt-image-2.5-flare")
            self.assertEqual(config["csrfToken"], server.csrf_token)
            self.assertEqual(config["limits"], {"scene": 600, "objects": 300})
            status, _, raw = request(server, "POST", "/api/prompt", config["defaults"])
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(raw)["prompt"].encode(), prompt_builder.REFERENCE_PATH.read_bytes())
            self.assertNotIn("test-key", raw.decode())

    def test_generate_mock_provider_returns_png_and_prompt_once(self):
        calls = []
        def provider(prompt, key):
            calls.append((prompt, key))
            return GOOD_RESPONSE
        with running_server(provider=provider) as server:
            status, _, raw = request(server, "POST", "/api/generate", {"scene": "a sleeping cat", "objects": "one cat"})
            result = json.loads(raw)
            self.assertEqual(status, 200)
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0][1], "test-key-never-sent")
            self.assertEqual(result["image"], "data:image/png;base64," + PNG_B64)
            self.assertIn("a sleeping cat", result["prompt"])
            self.assertNotIn("test-key", raw.decode())

    def test_unconfigured_blocks_generation_without_provider_call(self):
        provider = mock.Mock()
        with running_server(api_key="", provider=provider) as server:
            status, _, raw = request(server, "POST", "/api/generate")
            self.assertEqual(status, 503)
            self.assertEqual(json.loads(raw)["code"], "not_configured")
            provider.assert_not_called()

    def test_cross_origin_rebinding_missing_or_duplicate_tokens_rejected(self):
        with running_server() as server:
            hostile = [
                {"Host": "evil.invalid:%d" % server.server_port},
                {"Host": "127.0.0.1.evil.invalid:%d" % server.server_port},
                {"Origin": "https://evil.invalid"}, {"Origin": "null"}, {"Origin": None},
                {"Origin": "http://localhost:%d" % server.server_port},
                {"Sec-Fetch-Site": "cross-site"}, {"X-CSRF-Token": None}, {"X-CSRF-Token": "wrong"},
            ]
            for overrides in hostile:
                with self.subTest(overrides=overrides):
                    status, _, _ = request(server, "POST", "/api/prompt", headers=overrides)
                    self.assertEqual(status, 403)
            status, _, _ = request(server, headers={"Host": "example.com"})
            self.assertEqual(status, 403)
            authority = "localhost:%d" % server.server_port
            status, _, _ = request(server, "POST", "/api/prompt", headers={"Host": authority, "Origin": "http://" + authority})
            self.assertEqual(status, 200)

    def test_duplicate_security_headers_rejected_on_real_http(self):
        with running_server() as server:
            authority = "127.0.0.1:%d" % server.server_port
            for duplicate, value in [("Host", authority), ("Origin", "http://" + authority),
                                     ("X-CSRF-Token", server.csrf_token), ("Content-Length", "2")]:
                connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
                connection.putrequest("POST", "/api/prompt", skip_host=True)
                fields = [("Host", authority), ("Origin", "http://" + authority),
                          ("X-CSRF-Token", server.csrf_token), ("Content-Type", "application/json"), ("Content-Length", "2")]
                for name, item in fields + [(duplicate, value)]:
                    connection.putheader(name, item)
                connection.endheaders(b"{}")
                response = connection.getresponse()
                self.assertIn(response.status, (400, 403))
                response.read()
                connection.close()

    def test_content_type_and_body_limits(self):
        with running_server() as server:
            for content_type in ("text/plain", "application/x-www-form-urlencoded", "multipart/form-data", None):
                status, _, _ = request(server, "POST", "/api/prompt", headers={"Content-Type": content_type})
                self.assertEqual(status, 415)
            status, _, _ = request(server, "POST", "/api/prompt", raw=b" " * (app.MAX_BODY + 1))
            self.assertEqual(status, 413)
            for raw in (b"{bad", b"null", b"[]", b'{"scene":"one","scene":"two"}', b"\xff"):
                with self.subTest(raw=raw):
                    status, _, _ = request(server, "POST", "/api/prompt", raw=raw)
                    self.assertEqual(status, 400)
            status, _, _ = request(server, "POST", "/api/prompt", headers={"Transfer-Encoding": "chunked"})
            self.assertEqual(status, 400)

    def test_non_ascii_csrf_unicode_surrogates_and_deep_json_fail_cleanly(self):
        with running_server() as server:
            status, _, raw = request(server, "POST", "/api/prompt", headers={"X-CSRF-Token": "é" * len(server.csrf_token)})
            self.assertEqual(status, 403)
            self.assertEqual(json.loads(raw)["code"], "invalid_csrf")
            status, _, raw = request(server, "POST", "/api/prompt", payload={"scene": "bad\ud800text"})
            self.assertEqual(status, 400)
            self.assertEqual(json.loads(raw)["code"], "invalid_input")
            deep = b'{"scene":' + b'[' * 1500 + b'0' + b']' * 1500 + b'}'
            status, _, raw = request(server, "POST", "/api/prompt", raw=deep)
            self.assertEqual(status, 400)
            self.assertEqual(json.loads(raw)["code"], "invalid_json")

    def test_unknown_fields_cannot_change_model_or_provider(self):
        provider = mock.Mock()
        with running_server(provider=provider) as server:
            for payload in ({"model": "anything"}, {"url": "http://evil.invalid"}, {"api_key": "secret"}):
                status, _, _ = request(server, "POST", "/api/generate", payload)
                self.assertEqual(status, 400)
            provider.assert_not_called()

    def test_static_allowlist_no_path_traversal_or_source_leak(self):
        with running_server() as server:
            for url in ("/", "/app.js", "/styles.css", "/assets/sample-dog-walk.png"):
                self.assertEqual(request(server, path=url)[0], 200)
            for url in ("/app.py", "/prompts/reference-v2.txt", "/not-allowlisted.txt", "/../app.py", "/%2e%2e/app.py", "/?path=app.py"):
                self.assertEqual(request(server, path=url)[0], 404)

    def test_static_symlink_escape_rejected(self):
        with running_server() as server, tempfile.TemporaryDirectory() as other:
            secret = Path(other) / "private.txt"
            secret.write_text("do-not-serve")
            target = server.static_root / "app.js"
            target.unlink()
            target.symlink_to(secret)
            status, _, raw = request(server, path="/app.js")
            self.assertEqual(status, 404)
            self.assertNotIn(b"do-not-serve", raw)

    def test_headers_and_preflight(self):
        with running_server() as server:
            _, headers, _ = request(server, path="/")
            self.assertEqual(headers["Cache-Control"], "no-store")
            self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
            self.assertEqual(headers["X-Frame-Options"], "DENY")
            self.assertIn("default-src 'none'", headers["Content-Security-Policy"])
            self.assertIn("connect-src 'self'", headers["Content-Security-Policy"])
            self.assertNotIn("Access-Control-Allow-Origin", headers)
            self.assertEqual(request(server, "OPTIONS")[0], 405)

    def test_provider_errors_are_redacted_and_never_retried(self):
        calls = []
        def provider(prompt, key):
            calls.append(1)
            raise RuntimeError("secret-key-and-private-diary-provider-body")
        captured = io.StringIO()
        with redirect_stdout(captured), redirect_stderr(captured), running_server(provider=provider) as server:
            status, _, raw = request(server, "POST", "/api/generate")
            self.assertEqual(status, 502)
            self.assertEqual(len(calls), 1)
            self.assertNotIn(b"secret-key", raw)
        self.assertNotIn("private-diary", captured.getvalue())

    def test_generation_concurrency_single_request(self):
        entered = threading.Event()
        release = threading.Event()
        calls = []
        results = []
        def provider(prompt, key):
            calls.append(1)
            entered.set()
            release.wait(timeout=3)
            return GOOD_RESPONSE
        with running_server(provider=provider) as server:
            first = threading.Thread(target=lambda: results.append(request(server, "POST", "/api/generate")))
            first.start()
            self.assertTrue(entered.wait(timeout=2))
            second = request(server, "POST", "/api/generate")
            self.assertEqual(second[0], 429)
            self.assertEqual(json.loads(second[2])["code"], "busy")
            release.set()
            first.join(timeout=3)
            self.assertEqual(results[0][0], 200)
            self.assertEqual(len(calls), 1)

    def test_provider_failure_still_applies_cooldown(self):
        provider = mock.Mock(side_effect=app.ProviderError())
        with running_server(provider=provider, cooldown=3) as server:
            self.assertEqual(request(server, "POST", "/api/generate")[0], 502)
            status, _, raw = request(server, "POST", "/api/generate")
            self.assertEqual(status, 429)
            self.assertEqual(json.loads(raw)["code"], "cooldown")
            self.assertEqual(provider.call_count, 1)


class ProviderTests(unittest.TestCase):
    def test_payload_is_fixed_and_omits_unsupported_response_format(self):
        payload = app.provider_payload("example")
        self.assertEqual(payload, {"model": "gpt-image-2.5-flare", "prompt": "example", "n": 1,
                                  "size": "1024x1024", "quality": "high", "output_format": "png", "background": "opaque"})

    def test_png_validation_rejects_urls_invalid_base64_and_wrong_magic(self):
        self.assertEqual(app.validate_image_response(GOOD_RESPONSE), "data:image/png;base64," + PNG_B64)
        bad = [b"not-json", b"[]", b'{"data":[]}', b'{"data":[{"url":"https://evil.invalid"}]}',
               b'{"data":[{"b64_json":"%%%"}]}', b'{"data":[{"b64_json":"aGVsbG8="}]}',
               b'{"data":[{"b64_json":null}]}', b"x" * (app.MAX_PROVIDER_RESPONSE + 1)]
        for raw in bad:
            with self.subTest(length=len(raw)), self.assertRaises(app.ProviderError):
                app.validate_image_response(raw)

    def test_transport_disallows_redirects_and_uses_fixed_url_with_timeout(self):
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.status = 200
        response.headers = {"Content-Length": str(len(GOOD_RESPONSE))}
        response.read.return_value = GOOD_RESPONSE
        opener = mock.Mock()
        opener.open.return_value = response
        with mock.patch.object(app.urllib.request, "build_opener", return_value=opener) as build:
            self.assertEqual(app.call_provider("my scene", "dummy-secret"), GOOD_RESPONSE)
        handlers = build.call_args.args
        self.assertTrue(any(isinstance(handler, app.NoRedirect) for handler in handlers))
        outbound = opener.open.call_args.args[0]
        self.assertEqual(outbound.full_url, "https://api.openai.com/v1/images/generations")
        self.assertEqual(outbound.get_header("Authorization"), "Bearer dummy-secret")
        self.assertEqual(opener.open.call_args.kwargs["timeout"], 120)
        self.assertEqual(response.read.call_args.args[0], app.MAX_PROVIDER_RESPONSE + 1)
        self.assertIsNone(app.NoRedirect().redirect_request(outbound, None, 302, "redirect", {}, "https://evil.invalid"))

    def test_transport_timeout_and_oversized_headers_are_safe(self):
        opener = mock.Mock()
        opener.open.side_effect = socket.timeout("secret request context")
        with mock.patch.object(app.urllib.request, "build_opener", return_value=opener), self.assertRaises(app.ProviderError) as caught:
            app.call_provider("private diary", "dummy-key")
        self.assertEqual(caught.exception.code, "provider_timeout")
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.status = 200
        response.headers = {"Content-Length": str(app.MAX_PROVIDER_RESPONSE + 1)}
        opener.open.side_effect = None
        opener.open.return_value = response
        with mock.patch.object(app.urllib.request, "build_opener", return_value=opener), self.assertRaises(app.ProviderError):
            app.call_provider("private diary", "dummy-key")
        response.read.assert_not_called()

    def test_server_binding_is_always_ipv4_loopback(self):
        with running_server() as server:
            self.assertEqual(server.server_address[0], "127.0.0.1")


if __name__ == "__main__":
    unittest.main()
