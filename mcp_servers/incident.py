"""incident-mcp: PagerDuty incident read, Jira issue create, Confluence postmortem write.
Writes go to Jira/Confluence only - never to production. Without JIRA_*/CONFLUENCE_* env the writes land in
audit/ as files so the flow runs offline."""

from __future__ import annotations

import base64
import json
import os
import urllib.request
from datetime import UTC, datetime

from mcp.server.mcpserver import MCPServer

from agents.common import tools as bundle_tools
from agents.common.bundle import ROOT

server = MCPServer("incident-mcp", instructions="Incident record, Jira issues, Confluence postmortems. No production access.")
LOCAL = ROOT / "audit"


def _post(url: str, auth: str, body: dict) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Authorization": auth, "Content-Type": "application/json", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def _basic(user_env: str, token_env: str) -> str:
    return "Basic " + base64.b64encode(f"{os.environ[user_env]}:{os.environ[token_env]}".encode()).decode()


@server.tool()
def get_incident() -> dict:
    """The incident header the page opened (PagerDuty payload in the customer's setup)."""
    return bundle_tools.bundle.incident()


@server.tool()
def create_issue(summary: str, description: str, labels: list[str] | None = None) -> dict:
    """Create a Jira issue (JIRA_SITE, JIRA_PROJECT, JIRA_USER, JIRA_TOKEN) or a local record if unset."""
    labels = labels or ["sre", "postmortem-action"]
    if os.environ.get("JIRA_SITE"):
        body = {"fields": {"project": {"key": os.environ["JIRA_PROJECT"]}, "summary": summary, "labels": labels,
                           "issuetype": {"name": "Task"},
                           "description": {"type": "doc", "version": 1, "content": [
                               {"type": "paragraph", "content": [{"type": "text", "text": description}]}]}}}
        res = _post(f"https://{os.environ['JIRA_SITE']}/rest/api/3/issue", _basic("JIRA_USER", "JIRA_TOKEN"), body)
        return {"key": res["key"], "url": f"https://{os.environ['JIRA_SITE']}/browse/{res['key']}"}
    LOCAL.mkdir(exist_ok=True)
    rec = {"ts": datetime.now(UTC).isoformat(), "summary": summary, "description": description, "labels": labels}
    with (LOCAL / "issues.jsonl").open("a") as f:
        f.write(json.dumps(rec) + "\n")
    return {"key": "LOCAL-" + str(sum(1 for _ in (LOCAL / "issues.jsonl").open())), "stored": str(LOCAL / "issues.jsonl")}


@server.tool()
def write_postmortem(markdown: str) -> dict:
    """Publish the postmortem to Confluence (CONFLUENCE_SITE, CONFLUENCE_SPACE, CONFLUENCE_USER, CONFLUENCE_TOKEN)
    or write postmortems/<incident>.md if unset."""
    if os.environ.get("CONFLUENCE_SITE"):
        title = f"Postmortem {bundle_tools.bundle.incident()['id']}"
        body = {"type": "page", "title": title, "space": {"key": os.environ["CONFLUENCE_SPACE"]},
                "body": {"storage": {"value": f"<pre>{markdown}</pre>", "representation": "storage"}}}
        res = _post(f"https://{os.environ['CONFLUENCE_SITE']}/wiki/rest/api/content",
                    _basic("CONFLUENCE_USER", "CONFLUENCE_TOKEN"), body)
        return {"id": res["id"], "title": title}
    return bundle_tools.write_postmortem(markdown)


if __name__ == "__main__":
    from mcp_servers.common import serve
    serve(server)
