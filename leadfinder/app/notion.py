"""Notion delivery: create (once) and write to a "Leads" database under a
page the user shared with their integration. A missing or broken Notion
setup never fails a run — leads always land in the local dashboard."""
import logging
import re

import httpx

from . import db

log = logging.getLogger("leadfinder.notion")

API = "https://api.notion.com/v1"
VERSION = "2022-06-28"

DB_PROPERTIES = {
    "Name": {"title": {}},
    "Website": {"url": {}},
    "Score": {"number": {}},
    "Why": {"rich_text": {}},
    "Query": {"rich_text": {}},
    "Domain": {"rich_text": {}},
    "Added": {"date": {}},
}


def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": VERSION,
        "Content-Type": "application/json",
    }


def parse_page_id(raw: str) -> str | None:
    """Accept a full Notion URL or a bare page id."""
    m = re.search(r"([0-9a-f]{32})", raw.replace("-", "").lower())
    if not m:
        return None
    h = m.group(1)
    return f"{h[0:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


def _get_or_create_db(client: httpx.Client, token: str) -> str | None:
    db_id = db.get_setting("notion_db_id").strip()
    if db_id:
        r = client.get(f"{API}/databases/{db_id}", headers=_headers(token))
        if r.status_code == 200:
            return db_id
        log.warning("cached Notion database gone (%s), recreating", r.status_code)
    page_id = parse_page_id(db.get_setting("notion_parent_page"))
    if not page_id:
        log.warning("Notion parent page not configured or unparseable")
        return None
    r = client.post(
        f"{API}/databases",
        headers=_headers(token),
        json={
            "parent": {"type": "page_id", "page_id": page_id},
            "title": [{"type": "text", "text": {"content": "Leads"}}],
            "properties": DB_PROPERTIES,
        },
    )
    if r.status_code != 200:
        log.warning("could not create Notion database: %s %s", r.status_code, r.text[:300])
        return None
    db_id = r.json()["id"]
    db.set_setting("notion_db_id", db_id)
    return db_id


def deliver(leads: list[dict]) -> int:
    """Write leads to Notion. Returns how many were delivered (0 on any
    configuration problem — never raises)."""
    token = db.get_setting("notion_token").strip()
    if not token or not leads:
        return 0
    delivered = 0
    try:
        with httpx.Client(timeout=20) as client:
            db_id = _get_or_create_db(client, token)
            if not db_id:
                return 0
            for lead in leads:
                r = client.post(
                    f"{API}/pages",
                    headers=_headers(token),
                    json={
                        "parent": {"database_id": db_id},
                        "properties": {
                            "Name": {"title": [{"text": {"content": lead["name"][:200]}}]},
                            "Website": {"url": lead["url"][:1000]},
                            "Score": {"number": lead.get("score")},
                            "Why": {"rich_text": [{"text": {"content": (lead.get("reason") or "")[:1900]}}]},
                            "Query": {"rich_text": [{"text": {"content": (lead.get("source_query") or "")[:1900]}}]},
                            "Domain": {"rich_text": [{"text": {"content": lead["domain"][:200]}}]},
                            "Added": {"date": {"start": db.now().replace(" ", "T") + "Z"}},
                        },
                    },
                )
                if r.status_code == 200:
                    delivered += 1
                    if lead.get("id"):
                        db.mark_notion_ok(lead["id"])
                else:
                    log.warning("Notion write failed: %s %s", r.status_code, r.text[:200])
    except httpx.HTTPError as e:
        log.warning("Notion delivery error: %s", e)
    return delivered
