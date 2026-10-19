#!/usr/bin/env python3
"""Loopback-only doodle lab. Python 3.9+, standard library, no credentials on disk."""

import argparse
import base64
import binascii
import hmac
import json
import os
from pathlib import Path
import secrets
import socket
import ssl
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from prompt_builder import DEFAULT_OBJECTS, DEFAULT_SCENE, InputError, LIMITS, build_prompt


MODEL = "gpt-image-2.5-flare"
PROVIDER_URL = "https://api.openai.com/v1/images/generations"
MAX_BODY = 8192
MAX_PROVIDER_RESPONSE = 25 * 1024 * 1024
PROVIDER_TIMEOUT = 120
DEFAULT_PORT = 8767
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
STATIC_PATHS = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
    "/assets/sample-dog-walk.png": ("assets/sample-dog-walk.png", "image/png"),
}


class ProviderError(Exception):
    """Contains a public error category, never provider text or credentials."""

    def __init__(self, code="provider_error"):
        self.code = code
        super().__init__(code)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        # urllib must never forward an Authorization header to a redirect target.
        return None


def provider_payload(prompt):
    return {
        "model": MODEL, "prompt": prompt, "n": 1, "size": "1024x1024",
        "quality": "high", "output_format": "png", "background": "opaque",
    }


def call_provider(prompt, api_key):
    """One request, no retries and no redirect following."""
    request = urllib.request.Request(
        PROVIDER_URL,
        data=json.dumps(provider_payload(prompt), ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": "Bearer " + api_key, "Content-Type": "application/json",
                 "Accept": "application/json", "Accept-Encoding": "identity"},
        method="POST",
    )
    opener = urllib.request.build_opener(
        NoRedirect(), urllib.request.HTTPSHandler(context=ssl.create_default_context())
    )
    try:
        with opener.open(request, timeout=PROVIDER_TIMEOUT) as response:
            if response.status != 200:
                raise ProviderError()
            length = response.headers.get("Content-Length")
            if length:
                try:
                    if int(length) < 0 or int(length) > MAX_PROVIDER_RESPONSE:
                        raise ProviderError("invalid_provider_response")
                except ValueError:
                    raise ProviderError("invalid_provider_response") from None
            raw = response.read(MAX_PROVIDER_RESPONSE + 1)
            if len(raw) > MAX_PROVIDER_RESPONSE:
                raise ProviderError("invalid_provider_response")
            return raw
    except (socket.timeout, TimeoutError):
        raise ProviderError("provider_timeout") from None
    except urllib.error.HTTPError as error:
        error.close()
        raise ProviderError() from None
    except urllib.error.URLError as error:
        code = "provider_timeout" if isinstance(error.reason, (socket.timeout, TimeoutError)) else "provider_error"
        raise ProviderError(code) from None
    except (OSError, ValueError):
        raise ProviderError() from None


def validate_image_response(raw):
    if not isinstance(raw, bytes) or len(raw) > MAX_PROVIDER_RESPONSE:
        raise ProviderError("invalid_provider_response")
    try:
        document = json.loads(raw.decode("utf-8"))
        data = document["data"]
        if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], dict):
            raise ValueError()
        encoded = data[0]["b64_json"]
        if not isinstance(encoded, str) or not encoded:
            raise ValueError()
        image = base64.b64decode(encoded, validate=True)
        if not image.startswith(PNG_MAGIC):
            raise ValueError()
    except (UnicodeError, ValueError, KeyError, TypeError, binascii.Error, RecursionError):
        raise ProviderError("invalid_provider_response") from None
    return "data:image/png;base64," + encoded


def _unique_json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON fields are not accepted.")
        result[key] = value
    return result


class LabServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, port=DEFAULT_PORT, api_key=None, static_root=None,
                 provider=None, cooldown_seconds=3.0):
        # Test overrides inject a transport function and temporary static directory;
        # neither browser requests nor CLI flags can change the provider URL/model.
        super().__init__(("127.0.0.1", port), LabHandler)
        self.api_key = os.environ.get("OPENAI_API_KEY", "").strip() if api_key is None else api_key
        self.static_root = Path(static_root) if static_root is not None else Path(__file__).resolve().parent / "static"
        self.csrf_token = secrets.token_urlsafe(32)
        self.provider = provider or call_provider
        self.generation_lock = threading.Lock()
        self.cooldown_seconds = max(0, cooldown_seconds)
        self.last_generation_end = float("-inf")

    def handle_error(self, request, client_address):
        # Suppress traceback/request content from malformed or disconnected clients.
        pass


class LabHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "LocalDoodleLab"
    sys_version = ""

    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def log_message(self, format, *args):
        # No access logs: URLs, prompt text, API credentials and provider bodies
        # are intentionally never written to stdout/stderr or a local log file.
        pass

    def _headers(self, status, content_type, length):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; base-uri 'none'; object-src 'none'; form-action 'none'; frame-ancestors 'none'")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True

    def _json(self, status, payload):
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self._headers(status, "application/json; charset=utf-8", len(data))
        if self.command != "HEAD":
            self.wfile.write(data)

    def _error(self, status, code, message):
        self._json(status, {"error": message, "code": code})

    def send_error(self, code, message=None, explain=None):
        # The standard handler echoes request methods/paths into HTML errors.
        self._error(code, "invalid_request", "The request could not be processed.")

    def _check_origin(self, require_origin=False):
        hosts = self.headers.get_all("Host", [])
        allowed_hosts = {"localhost:%d" % self.server.server_port, "127.0.0.1:%d" % self.server.server_port}
        if len(hosts) != 1 or hosts[0] not in allowed_hosts:
            self._error(403, "invalid_host", "This local app only accepts its own loopback address.")
            return False
        origins = self.headers.get_all("Origin", [])
        if (len(origins) > 1 or (require_origin and len(origins) != 1)
                or (origins and origins[0] != "http://" + hosts[0])
                or self.headers.get("Sec-Fetch-Site", "") == "cross-site"):
            self._error(403, "invalid_origin", "Open and use this app from its own local browser tab.")
            return False
        return True

    def do_GET(self):
        if not self._check_origin():
            return
        if self.path == "/api/config":
            self._json(200, {
                "configured": bool(self.server.api_key), "model": MODEL,
                "csrfToken": self.server.csrf_token,
                "defaults": {"scene": DEFAULT_SCENE, "objects": DEFAULT_OBJECTS},
                "limits": LIMITS,
            })
            return
        route = STATIC_PATHS.get(self.path)
        if route is None:
            self._error(404, "not_found", "This local page was not found.")
            return
        name, content_type = route
        try:
            root = self.server.static_root.resolve()
            target = (root / name).resolve()
            if root not in target.parents:
                raise OSError()
            data = target.read_bytes()
        except OSError:
            self._error(404, "not_found", "This local file was not found.")
            return
        self._headers(200, content_type, len(data))
        self.wfile.write(data)

    def _payload(self):
        if not self._check_origin(require_origin=True):
            return None
        tokens = self.headers.get_all("X-CSRF-Token", [])
        if (len(tokens) != 1 or len(tokens[0]) != len(self.server.csrf_token)
                or not tokens[0].isascii() or not hmac.compare_digest(tokens[0], self.server.csrf_token)):
            self._error(403, "invalid_csrf", "Reload this page before trying again.")
            return None
        types = self.headers.get_all("Content-Type", [])
        if len(types) != 1 or types[0].lower().replace(" ", "") not in ("application/json", "application/json;charset=utf-8"):
            self._error(415, "invalid_content_type", "Send this request as application/json.")
            return None
        lengths = self.headers.get_all("Content-Length", [])
        if self.headers.get_all("Transfer-Encoding", []) or len(lengths) != 1:
            self._error(400, "invalid_body", "A single, bounded JSON request body is required.")
            return None
        try:
            if not lengths[0].isascii() or not lengths[0].isdigit():
                raise ValueError()
            length = int(lengths[0])
        except ValueError:
            self._error(400, "invalid_body", "The request body length is invalid.")
            return None
        if length > MAX_BODY:
            self._error(413, "body_too_large", "This request is too large.")
            return None
        try:
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise ValueError()
            payload = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_json_object)
        except (ValueError, UnicodeError, socket.timeout, RecursionError):
            self._error(400, "invalid_json", "The request must contain valid JSON without duplicate fields.")
            return None
        # The JSON null value is an error, never a sentinel for successful parsing.
        if not isinstance(payload, dict):
            self._error(400, "invalid_input", "Send a JSON object with scene and objects fields.")
            return None
        return payload

    def do_POST(self):
        payload = self._payload()
        if payload is None:
            return
        if self.path not in ("/api/prompt", "/api/generate"):
            self._error(404, "not_found", "This local API was not found.")
            return
        try:
            prompt = build_prompt(payload)
        except InputError as error:
            self._error(400, "invalid_input", str(error))
            return
        except (OSError, RuntimeError):
            self._error(500, "prompt_unavailable", "The local prompt reference could not be loaded.")
            return
        if self.path == "/api/prompt":
            self._json(200, {"prompt": prompt})
            return
        if not self.server.api_key:
            self._error(503, "not_configured", "Set OPENAI_API_KEY in the server environment, then restart the local app.")
            return
        if not self.server.generation_lock.acquire(blocking=False):
            self._error(429, "busy", "One image is already being generated. Wait for it to finish.")
            return
        started = False
        try:
            if time.monotonic() - self.server.last_generation_end < self.server.cooldown_seconds:
                self._error(429, "cooldown", "Wait a few seconds before generating another image.")
                return
            started = True
            raw = self.server.provider(prompt, self.server.api_key)
            image = validate_image_response(raw)
            self._json(200, {"image": image, "prompt": prompt})
        except ProviderError as error:
            if error.code == "provider_timeout":
                self._error(504, "provider_timeout", "Image generation timed out. No automatic retry was made.")
            else:
                self._error(502, "provider_error", "The image service did not return a usable PNG. No automatic retry was made.")
        except Exception:
            self._error(502, "provider_error", "Image generation could not complete. No automatic retry was made.")
        finally:
            if started:
                self.server.last_generation_end = time.monotonic()
            self.server.generation_lock.release()

    def do_HEAD(self):
        if self._check_origin():
            self._error(405, "method_not_allowed", "Use GET or POST for this local app.")

    def do_OPTIONS(self):
        if self._check_origin():
            self._error(405, "method_not_allowed", "Cross-origin API calls are not allowed.")


def main():
    parser = argparse.ArgumentParser(description="Run the local pet memory doodle lab on 127.0.0.1.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Loopback HTTP port (default: 8767)")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    server = LabServer(port=args.port)
    print("Pet memory doodle lab: http://127.0.0.1:%d" % server.server_port, flush=True)
    print("Image service: %s" % ("configured" if server.api_key else "not configured; prompt preview is available"), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
