#!/usr/bin/env python3
"""Runner: receive OpenClaw's forwarded Slack mentions and hand them to the bridge handler.

RIDES OpenClaw's gateway — does NOT open a Socket-Mode connection. OpenClaw holds the single
allowed Socket connection for the appToken; configure it to forward normalized mention events to
this local endpoint (the `webhookPath`/forward seam), e.g. POST http://127.0.0.1:8799/slack/a2a
with body {channel, thread_ts, user, text}. This process replies via the bot-token Web API
(slack_tool), so only ONE Socket connection (OpenClaw's) ever exists.

Env (source the fleet .env for execution; never printed):
  LANGGRAPH_DEPLOYMENT_URL / LANGSMITH_API_KEY / LANGSMITH_TENANT_ID  (a2a_client)
  SLACK_BOT_TOKEN                                                     (slack_tool replies)
  OPENCLAW_ALLOW_FROM   = "U08L384N6VD"   (csv; from openclaw.json channels.slack.allowFrom)
  BRIDGE_REPORT_ONLY    = "1" (default)   (probation: agent->peer turns recorded, not auto-acted)
  BRIDGE_PORT           = "8799" (default)

Stdlib-only HTTP server (deps-free CI venv friendly). Start under launchd or `&`.
"""
from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# Make the worktree importable so `from agent_toolkit import ...` resolves.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_toolkit import slack_a2a_bridge  # noqa: E402

_REPORT_ONLY = os.environ.get("BRIDGE_REPORT_ONLY", "1") != "0"


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802
        try:
            length = int(self.headers.get("Content-Length", "0"))
            event = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            return self._json(400, {"status": "bad_request"})
        # handle_mention is fail-safe (never raises) and does its own allowFrom auth.
        result = slack_a2a_bridge.handle_mention(event, report_only=_REPORT_ONLY)
        return self._json(200, result)

    def _json(self, code: int, body: dict) -> None:
        payload = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *_a) -> None:  # silence default logging (no secret/PII leakage)
        return


def main() -> None:
    port = int(os.environ.get("BRIDGE_PORT", "8799"))
    srv = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    # bind line only — no secrets
    print(f"slack-a2a bridge listening on 127.0.0.1:{port} (report_only={_REPORT_ONLY})", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
