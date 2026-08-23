"""Deterministic OpenAI-compatible proposal fixture for browser E2E tests.

The fixture emits semantic proposals only. The application still performs all
compilation, policy, confirmation, persistence, and execution decisions.
Requests are processed in memory and are never logged or persisted.
"""

from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


def _decision(message: str) -> dict[str, object]:
    normalized = " ".join(message.casefold().strip().split())
    if normalized == "i want a refund for order 1 because it arrived damaged.":
        return {
            "intent": "refund_request",
            "request_type": "write_action",
            "target": {"type": "explicit_order", "order_id": 1},
            "reason": "arrived damaged",
            "clarification_required": False,
            "requires_retrieval": False,
        }
    if normalized == "cancel order 3":
        return {
            "intent": "order_cancel",
            "request_type": "write_action",
            "target": {"type": "explicit_order", "order_id": 3},
            "reason": "Deterministic operator E2E cancellation proposal.",
            "clarification_required": False,
            "requires_retrieval": False,
        }
    if normalized == "refund my order":
        return {
            "intent": "refund_request",
            "request_type": "write_action",
            "target": None,
            "reason": "",
            "clarification_required": False,
            "requires_retrieval": False,
        }
    if normalized == "what is the refund policy for damaged products?":
        return {
            "intent": "refund_policy",
            "request_type": "knowledge_only",
            "target": None,
            "reason": "Customer requested refund policy information.",
            "clarification_required": False,
            "requires_retrieval": True,
            "knowledge_query": "refund policy damaged products",
        }
    return {
        "intent": "unknown",
        "request_type": "unclear",
        "target": None,
        "reason": "Unsupported deterministic browser scenario.",
        "clarification_required": True,
        "requires_retrieval": False,
    }


def _latest_user_message(payload: dict[str, Any]) -> str:
    messages = payload.get("messages")
    if not isinstance(messages, list):
        return ""
    for item in reversed(messages):
        if not isinstance(item, dict) or item.get("role") != "user":
            continue
        content = item.get("content")
        if isinstance(content, str):
            return content
    return ""


class ProposalHandler(BaseHTTPRequestHandler):
    server_version = "operator-e2e-provider"

    def log_message(self, format: str, *args: object) -> None:
        del format, args

    def _json(self, status: HTTPStatus, payload: object) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            self._json(HTTPStatus.OK, {"status": "ready"})
            return
        self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/v1/chat/completions":
            self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            parsed = json.loads(self.rfile.read(length))
            if not isinstance(parsed, dict):
                raise ValueError("request must be an object")
        except (ValueError, json.JSONDecodeError):
            self._json(HTTPStatus.BAD_REQUEST, {"error": "invalid_request"})
            return
        model = str(parsed.get("model") or "operator-e2e-semantic-v3")
        proposal = _decision(_latest_user_message(parsed))
        self._json(
            HTTPStatus.OK,
            {
                "id": "operator-e2e-proposal",
                "object": "chat.completion",
                "created": 1787461200,
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(proposal, separators=(",", ":")),
                        },
                        "finish_reason": "stop",
                    }
                ],
            },
        )


def main() -> None:
    server = ThreadingHTTPServer(("0.0.0.0", 8081), ProposalHandler)
    server.serve_forever()


if __name__ == "__main__":
    main()
