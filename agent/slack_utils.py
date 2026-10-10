"""
Slack integration: verifying inbound interaction payloads and formatting
the approval message. Requires SLACK_SIGNING_SECRET and (for actually
posting) SLACK_BOT_TOKEN / a webhook URL, none of which are needed for the
local demo - the dashboard's Approve/Reject buttons hit the same
/incidents/{id}/approve endpoint this Slack handler calls.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from typing import Optional
from urllib.parse import parse_qs

SLACK_SIGNING_SECRET = os.getenv("SLACK_SIGNING_SECRET", "")


def verify_signature(headers, body: bytes) -> bool:
    """
    Verifies Slack's HMAC signature per
    https://api.slack.com/authentication/verifying-requests-from-slack
    Returns True automatically when no signing secret is configured, so
    local/demo mode (no real Slack app) isn't blocked.
    """
    if not SLACK_SIGNING_SECRET:
        return True

    timestamp = headers.get("X-Slack-Request-Timestamp", "")
    signature = headers.get("X-Slack-Signature", "")
    if not timestamp or not signature:
        return False
    if abs(time.time() - int(timestamp)) > 60 * 5:
        return False  # replay-attack guard

    basestring = f"v0:{timestamp}:{body.decode()}"
    computed = "v0=" + hmac.new(
        SLACK_SIGNING_SECRET.encode(), basestring.encode(), hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(computed, signature)


def parse_interaction(body: bytes) -> dict:
    """Slack sends interaction payloads as application/x-www-form-urlencoded
    with a 'payload' field containing JSON."""
    form = parse_qs(body.decode())
    payload = json.loads(form["payload"][0])
    action = payload["actions"][0]
    return {
        "incident_id": action["value"].split(":")[1],
        "action": action["action_id"],  # "approve" or "reject"
    }


def build_incident_blocks(incident) -> list:
    """Block Kit message shown to the on-call engineer."""
    diag = incident.diagnosis
    fix = incident.proposed_fix
    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": f"🚨 Incident {incident.id}"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*Alert:* {incident.alert_summary}"}},
    ]
    if diag:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Root cause* ({diag.confidence:.0%} confidence):\n{diag.root_cause}"},
        })
    if fix and fix.fix_id == "escalate":
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Escalated to on-call:* {fix.justification or fix.description}"},
        })
    elif fix:
        why = f"\n*Why:* {fix.justification}" if fix.justification else ""
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Proposed fix* (risk: {fix.risk.value}):\n{fix.description}\n```{fix.diff}```{why}"},
        })
    if fix and incident.status.value == "awaiting_approval":
        blocks.append({
            "type": "actions",
            "elements": [
                {"type": "button", "text": {"type": "plain_text", "text": "✅ Approve"},
                 "style": "primary", "action_id": "approve", "value": f"incident:{incident.id}"},
                {"type": "button", "text": {"type": "plain_text", "text": "❌ Reject"},
                 "style": "danger", "action_id": "reject", "value": f"incident:{incident.id}"},
            ],
        })
    return blocks
