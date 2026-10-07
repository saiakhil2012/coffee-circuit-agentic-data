"""Set up n8n (self-hosted community edition) for Coffee Circuit through its local REST API:
local owner account -> Mailpit SMTP credential -> recall-notification workflow -> published.
Idempotent. Credentials for the local owner come from .env (see .env.example)."""

import json
import os
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
N8N = "http://localhost:5678"
NAME = "Quality hold notification (area managers)"


def env() -> dict:
    vals = {}
    for line in (ROOT / ".env").read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            vals[k.strip()] = v.strip()
    return {**vals, **{k: v for k, v in os.environ.items() if k.startswith("N8N_")}}


def main() -> None:
    cfg = env()
    email, password = cfg["N8N_OWNER_EMAIL"], cfg["N8N_OWNER_PASSWORD"]
    for _ in range(60):
        try:
            if requests.get(f"{N8N}/rest/settings", timeout=2).ok:  # REST routes mount after /healthz is up
                break
        except requests.RequestException:
            pass
        time.sleep(2)
    s = requests.Session()
    owner = {"email": email, "firstName": "Coffee", "lastName": "Owner", "password": password}
    s.post(f"{N8N}/rest/owner/setup", json=owner)  # no-op once an owner exists
    r = s.post(f"{N8N}/rest/login", json={"emailOrLdapLoginId": email, "password": password})
    if not r.ok:
        sys.exit(f"n8n login failed: {r.status_code} {r.text[:200]}")

    creds = s.get(f"{N8N}/rest/credentials").json()["data"]
    cred = next((c for c in creds if c["name"] == "Mailpit (local SMTP)"), None)
    if not cred:
        cred = s.post(
            f"{N8N}/rest/credentials",
            json={
                "name": "Mailpit (local SMTP)",
                "type": "smtp",
                "data": {
                    "user": "mailpit",
                    "password": "mailpit",
                    "host": "mailpit",
                    "port": 1025,
                    "secure": False,
                    "disableStartTls": True,
                },
            },
        ).json()["data"]

    wf = json.loads((ROOT / "n8n" / "recall-notify.workflow.json").read_text())
    for node in wf["nodes"]:
        if "credentials" in node:
            node["credentials"]["smtp"] = {"id": cred["id"], "name": cred["name"]}

    existing = [w for w in s.get(f"{N8N}/rest/workflows").json()["data"] if w["name"] == NAME]
    if existing:
        w = s.get(f"{N8N}/rest/workflows/{existing[0]['id']}").json()["data"]
    else:
        w = s.post(f"{N8N}/rest/workflows", json={**wf, "name": NAME, "active": False}).json()["data"]
    if not w.get("activeVersionId"):
        r = s.post(f"{N8N}/rest/workflows/{w['id']}/activate", json={"versionId": w["versionId"]})
        if not r.ok:
            sys.exit(f"activate failed: {r.status_code} {r.text[:300]}")
    print(f"✓ n8n ready · workflow '{NAME}' published · POST {N8N}/webhook/recall-notify · inbox http://localhost:8025")


if __name__ == "__main__":
    main()
