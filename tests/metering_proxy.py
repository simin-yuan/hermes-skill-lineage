"""Metering proxy: forwards OpenAI-compatible calls to a real upstream and records token usage.

``e2e_worker.py``'s real-model mode points Hermes at this loopback server instead of the upstream
API, so every request's ``usage`` is recorded as it happens. Token counts and cost come from these
records, never from an estimate after the fact.

Streaming is refused on purpose: a streamed reply spreads usage across chunks and the numbers would
stop being auditable. The worker writes ``streaming: false`` into the throwaway config.

Loopback only, one instance per run, dies with the worker.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


class MeteringProxy:
    def __init__(self, upstream: str, api_key: str, model_id: str):
        self.upstream = upstream.rstrip("/")
        self.api_key = api_key
        self.model_id = model_id
        self.calls: list[dict] = []
        self.errors: list[str] = []
        self._lock = threading.Lock()
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: Any) -> None:
                pass

            def _reply(self, code: int, payload: bytes) -> None:
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def do_GET(self) -> None:
                if self.path.rstrip("/").endswith("/models"):
                    body = {"object": "list", "data": [{"id": server.model_id, "object": "model",
                                                        "context_length": 1_000_000}]}
                    self._reply(200, json.dumps(body).encode("utf-8"))
                else:
                    self._reply(404, b'{"error":{"message":"not found"}}')

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) or b"{}"
                try:
                    body = json.loads(raw)
                except Exception:
                    body = {}
                if body.get("stream"):
                    with server._lock:
                        server.errors.append("stream=true refused (usage would not be auditable)")
                    self._reply(400, b'{"error":{"message":"streaming disabled for metering"}}')
                    return
                req = urllib.request.Request(
                    server.upstream + self.path, data=raw,
                    headers={"Authorization": f"Bearer {server.api_key}",
                             "Content-Type": "application/json"})
                try:
                    resp = urllib.request.urlopen(req, timeout=300)
                    payload, code = resp.read(), resp.status
                except urllib.error.HTTPError as exc:
                    payload, code = exc.read(), exc.code
                except Exception as exc:  # network / TLS / timeout
                    with server._lock:
                        server.errors.append(f"{type(exc).__name__}: {exc}")
                    self._reply(502, json.dumps({"error": {"message": str(exc)}}).encode("utf-8"))
                    return
                if code == 200:
                    try:
                        parsed = json.loads(payload)
                        usage = parsed.get("usage") or {}
                        with server._lock:
                            server.calls.append({
                                "prompt_tokens": usage.get("prompt_tokens") or 0,
                                "completion_tokens": usage.get("completion_tokens") or 0,
                                "cached_tokens": (usage.get("prompt_tokens_details") or {}).get("cached_tokens") or 0,
                                "reasoning_tokens": (usage.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0,
                                "model": parsed.get("model"),
                            })
                    except Exception as exc:
                        with server._lock:
                            server.errors.append(f"usage parse: {type(exc).__name__}: {exc}")
                self._reply(code, payload)

        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self._httpd.server_address[1]}/v1"

    def __enter__(self) -> "MeteringProxy":
        self._thread.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()

    def totals(self) -> dict:
        """Per-run totals. ``cost_usd`` uses the off-peak deepseek-flash rates; peak is 2x."""
        with self._lock:
            calls, errors = list(self.calls), list(self.errors)
        prompt = sum(c["prompt_tokens"] for c in calls)
        completion = sum(c["completion_tokens"] for c in calls)
        cached = sum(c["cached_tokens"] for c in calls)
        billable_prompt = max(prompt - cached, 0)
        cost = billable_prompt * 0.15 / 1_000_000 + cached * 0.003 / 1_000_000 \
            + completion * 0.60 / 1_000_000
        return {"requests": len(calls), "prompt_tokens": prompt, "completion_tokens": completion,
                "cached_tokens": cached,
                "reasoning_tokens": sum(c["reasoning_tokens"] for c in calls),
                "cost_usd": round(cost, 6), "errors": errors, "calls": calls}
