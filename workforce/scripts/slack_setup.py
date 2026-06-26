"""One-shot Slack setup: create required channels and post a hello message.

Usage:
    SLACK_BOT_TOKEN=xoxb-... python3 scripts/slack_setup.py

Required bot token scopes:
    channels:read, channels:write, chat:write, chat:write.customize

This is a one-time setup script, not an agent graph.
"""
import os
import sys

# Ensure the package is importable when run from the repo root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_toolkit.slack_tool import ensure_channels, post_digest

DEMO_AGENTS = [
    ("daily_digest",    "📅 Agent Fleet is Online",         "#executive-updates", "The agent workforce is now wired to Slack. You'll see daily digests, revenue reports, and exec updates here."),
    ("cto",             "💻 Engineering channel active",     "#engineering",       "CTO and engineering agents will post deploy reports, PR summaries, and incident updates here."),
    ("cmo",             "📢 Marketing channel active",       "#marketing",         "CMO, ASO, and content agents will post campaign updates, store listing drafts, and growth reports here."),
    ("qa_lead_aggregator", "✅ QA channel active",           "#qa-reports",        "QA lead and platform test agents will post shippability verdicts, bug findings, and coverage reports here."),
    ("coo",             "⚙️ Ops channel active",             "#daily-ops",         "COO, git auditor, and ops agents will post operational health updates here."),
]


def main() -> None:
    token = os.environ.get("SLACK_BOT_TOKEN", "").strip()
    webhook = os.environ.get("SLACK_WEBHOOK_URL", "").strip()

    if not token and not webhook:
        print("ERROR: Set SLACK_BOT_TOKEN or SLACK_WEBHOOK_URL before running this script.")
        print("\nTo get a bot token:")
        print("  1. Go to https://api.slack.com/apps → Create New App → From scratch")
        print("  2. Name it 'Scheduler Agent Fleet'")
        print("  3. OAuth & Permissions → Bot Token Scopes: channels:read channels:write chat:write chat:write.customize")
        print("  4. Install to Workspace → copy the Bot User OAuth Token (xoxb-...)")
        print("  5. Set SLACK_BOT_TOKEN=xoxb-... and re-run this script")
        sys.exit(1)

    print("Step 1: Creating required channels...")
    result = ensure_channels(token)
    print(f"  Status: {result.get('status')}")
    for name, status in (result.get("channels") or {}).items():
        icon = "✓" if status in ("exists", "created") else "✗"
        print(f"  {icon} #{name}: {status}")

    print("\nStep 2: Posting hello messages to each channel...")
    for agent, title, channel, body in DEMO_AGENTS:
        res = post_digest(agent, title, body, channel=channel)
        icon = "✓" if res.get("status") == "posted" else "~"
        print(f"  {icon} {channel} via {agent}: {res.get('status')} {res.get('detail', '')}")

    print("\nSetup complete. Check your Slack workspace.")


if __name__ == "__main__":
    main()
