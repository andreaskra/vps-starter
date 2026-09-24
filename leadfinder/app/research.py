"""The research pipeline: ICP text -> queries -> Tavily search -> dedup ->
Claude scoring -> store locally -> deliver to Notion. Hard caps keep every
run inside a fixed cost ceiling. DRY_RUN fabricates results instead of
calling any paid API."""
import logging
import threading
from urllib.parse import urlparse

import httpx

from . import config, db, llm, notion

log = logging.getLogger("leadfinder.research")

_run_lock = threading.Lock()

TAVILY_URL = "https://api.tavily.com/search"
RESULTS_PER_QUERY = 8

# hosts that are never a lead's own website
EXCLUDED = {
    "linkedin.com", "facebook.com", "instagram.com", "x.com", "twitter.com",
    "tiktok.com", "pinterest.com", "youtube.com", "reddit.com", "medium.com",
    "quora.com", "wikipedia.org", "yelp.com", "tripadvisor.com", "google.com",
    "amazon.com", "yellowpages.com", "bbb.org", "glassdoor.com", "indeed.com",
    "crunchbase.com", "bloomberg.com", "forbes.com", "clutch.co", "trustpilot.com",
}


def is_running() -> bool:
    if _run_lock.acquire(blocking=False):
        _run_lock.release()
        return False
    return True


def start_in_background() -> bool:
    """Kick off a run unless one is already going. Returns False if busy."""
    if is_running():
        return False
    threading.Thread(target=run, daemon=True).start()
    return True


def registered_domain(url: str) -> str | None:
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    if not host or "." not in host:
        return None
    parts = host.split(".")
    base = ".".join(parts[-2:])
    if base in EXCLUDED or host in EXCLUDED:
        return None
    return host


def _tavily_search(api_key: str, query: str) -> list[dict]:
    with httpx.Client(timeout=30) as client:
        r = client.post(
            TAVILY_URL,
            json={"api_key": api_key, "query": query, "max_results": RESULTS_PER_QUERY},
        )
        r.raise_for_status()
        return r.json().get("results", [])


def _dry_run_results(query: str, i: int) -> list[dict]:
    fakes = [
        ("Golden Comb Studio", "https://www.goldencombstudio.example"),
        ("Mane Street Salon", "https://manestreetsalon.example"),
        ("The Polished Look", "https://thepolishedlook.example"),
        ("Shear Bliss Hair Co", "https://shearblisshair.example"),
        ("Luxe Locks Boutique", "https://luxelocks.example"),
        ("Fade Factory Barbers", "https://fadefactory.example"),
    ]
    name, url = fakes[i % len(fakes)]
    return [{
        "title": f"{name} — demo result {i + 1}",
        "url": url.replace(".example", f"-{i}.example"),
        "content": f"(DRY RUN) Fabricated candidate for query: {query}",
    }]


def run() -> None:
    with _run_lock:
        run_id = db.start_run()
        try:
            _run(run_id)
        except Exception as e:  # noqa: BLE001 — a run must never crash the app
            log.exception("run %s failed", run_id)
            db.finish_run(run_id, "failed", 0, 0, 0, str(e)[:500])


def _run(run_id: int) -> None:
    icp = db.get_setting("icp_description").strip()
    tavily_key = db.get_setting("tavily_api_key").strip()
    max_queries = max(1, min(12, int(db.get_setting("max_queries") or 6)))
    max_new = max(1, min(50, int(db.get_setting("max_new_leads") or 15)))

    if not icp:
        db.finish_run(run_id, "skipped", 0, 0, 0,
                      "No ideal-customer description configured in Settings.")
        return
    if not config.DRY_RUN and not tavily_key:
        db.finish_run(run_id, "skipped", 0, 0, 0,
                      "No Tavily API key configured in Settings.")
        return

    # 1) queries
    if config.DRY_RUN:
        queries = [f"(dry) {icp[:60]} query {i + 1}" for i in range(max_queries)]
    else:
        queries = llm.build_queries(icp, max_queries)

    # 2) search + extract candidates
    known = db.lead_domains()
    seen_this_run: set[str] = set()
    candidates: list[dict] = []
    found = 0
    for qi, query in enumerate(queries):
        if len(candidates) >= max_new:
            break
        try:
            results = (
                _dry_run_results(query, qi) if config.DRY_RUN
                else _tavily_search(tavily_key, query)
            )
        except httpx.HTTPError as e:
            log.warning("Tavily search failed for %r: %s", query, e)
            continue
        found += len(results)
        for r in results:
            domain = registered_domain(r.get("url", ""))
            if not domain or domain in known or domain in seen_this_run:
                continue
            seen_this_run.add(domain)
            candidates.append({
                "domain": domain,
                "name": (r.get("title") or domain)[:200],
                "url": r["url"],
                "snippet": (r.get("content") or "")[:500],
                "source_query": query,
            })
            if len(candidates) >= max_new:
                break

    # 3) score with Claude (skipped in DRY_RUN / without a key)
    scores = {} if config.DRY_RUN else llm.score_candidates(icp, candidates)
    for c in candidates:
        s = scores.get(c["domain"])
        if s:
            c["name"] = s["name"][:200] or c["name"]
            c["score"] = s["score"]
            c["reason"] = s["reason"][:500]

    # 4) store locally
    for c in candidates:
        c["run_id"] = run_id
        c["id"] = db.insert_lead(c)

    # 5) deliver to Notion (never fails the run)
    delivered = 0 if config.DRY_RUN else notion.deliver(candidates)

    notes = []
    if config.DRY_RUN:
        notes.append("DRY RUN — fabricated results, no API calls.")
    if not config.DRY_RUN and db.get_setting("notion_token").strip():
        notes.append(f"{delivered}/{len(candidates)} delivered to Notion.")
    if not db.get_setting("anthropic_api_key").strip() and not config.DRY_RUN:
        notes.append("No Anthropic key — template queries, unscored leads.")
    db.finish_run(run_id, "ok", len(queries), found, len(candidates), " ".join(notes))
    log.info("run %s: %d queries, %d results, %d new leads", run_id, len(queries), found, len(candidates))
