"""Claude integration: turn the ICP description into search queries and
score each found candidate for fit. Both calls use structured outputs so
the responses are guaranteed-valid JSON."""
import json
import logging

import anthropic

from . import db

log = logging.getLogger("leadfinder.llm")

QUERIES_SCHEMA = {
    "type": "object",
    "properties": {
        "queries": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["queries"],
    "additionalProperties": False,
}

SCORES_SCHEMA = {
    "type": "object",
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "domain": {"type": "string"},
                    "company_name": {"type": "string"},
                    "score": {"type": "integer", "enum": [1, 2, 3, 4, 5]},
                    "reason": {"type": "string"},
                },
                "required": ["domain", "company_name", "score", "reason"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["results"],
    "additionalProperties": False,
}


def _client() -> anthropic.Anthropic | None:
    key = db.get_setting("anthropic_api_key").strip()
    return anthropic.Anthropic(api_key=key) if key else None


def _create(client: anthropic.Anthropic, prompt: str, schema: dict, max_tokens: int) -> dict:
    response = client.messages.create(
        model=db.get_setting("model") or "claude-opus-4-8",
        max_tokens=max_tokens,
        output_config={"format": {"type": "json_schema", "schema": schema}},
        messages=[{"role": "user", "content": prompt}],
    )
    if response.stop_reason == "refusal":
        raise RuntimeError("Claude declined the request")
    text = next(b.text for b in response.content if b.type == "text")
    return json.loads(text)


def build_queries(icp: str, n: int) -> list[str]:
    """Return up to n web-search queries. Falls back to simple templates if
    no Anthropic key is configured or the call fails."""
    client = _client()
    if client is not None:
        try:
            data = _create(
                client,
                "You help a small business find potential customers via web search.\n"
                f"Their ideal customer, in their own words:\n\n{icp}\n\n"
                f"Write {n} diverse web-search queries that would surface the actual "
                "websites of businesses matching this description (not directories, "
                "not listicles). Vary geography, industry wording, and angle.",
                QUERIES_SCHEMA,
                max_tokens=1500,
            )
            queries = [q.strip() for q in data["queries"] if q.strip()]
            if queries:
                return queries[:n]
        except (anthropic.APIError, RuntimeError, json.JSONDecodeError, KeyError) as e:
            log.warning("query generation via Claude failed, using templates: %s", e)

    base = " ".join(icp.split())[:120]
    templates = [
        f"{base}",
        f"{base} company website",
        f"{base} services",
        f"best {base}",
        f"{base} near me",
        f"{base} small business",
    ]
    return templates[:n]


def score_candidates(icp: str, candidates: list[dict]) -> dict[str, dict]:
    """Score candidates 1-5 for ICP fit. Returns {domain: {name, score, reason}}.
    Empty dict when no Anthropic key is configured (leads are kept unscored)."""
    client = _client()
    if client is None or not candidates:
        return {}
    listing = "\n".join(
        f"- domain: {c['domain']} | title: {c['name']} | snippet: {c['snippet'][:200]}"
        for c in candidates
    )
    try:
        data = _create(
            client,
            "You qualify sales leads for a small business.\n"
            f"Their ideal customer:\n\n{icp}\n\n"
            "For each candidate below, give a clean company name, a fit score "
            "from 1 (not a fit) to 5 (perfect fit), and a one-line reason. "
            "Score directories, blogs, and non-businesses as 1.\n\n"
            f"Candidates:\n{listing}",
            SCORES_SCHEMA,
            max_tokens=4000,
        )
        return {
            r["domain"]: {
                "name": r["company_name"],
                "score": r["score"],
                "reason": r["reason"],
            }
            for r in data["results"]
        }
    except (anthropic.APIError, RuntimeError, json.JSONDecodeError, KeyError) as e:
        log.warning("scoring via Claude failed, keeping leads unscored: %s", e)
        return {}
