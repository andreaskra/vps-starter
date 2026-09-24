"""leadfinder — dashboard + nightly scheduler in one process."""
import csv
import io
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import auth, config, db, domains, research

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("leadfinder")

scheduler = BackgroundScheduler()


def _nightly_tick() -> None:
    """Runs every minute; fires the pipeline once per day at the configured hour."""
    try:
        hour = int(db.get_setting("run_hour") or 2)
    except ValueError:
        hour = 2
    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    if now.hour == hour and db.get_setting("last_auto_run_date") != today:
        db.set_setting("last_auto_run_date", today)
        log.info("nightly run starting (hour=%s)", hour)
        research.start_in_background()


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init()
    scheduler.add_job(_nightly_tick, "interval", minutes=1, id="nightly-tick")
    scheduler.add_job(domains.renew_certificates, "cron", hour=4, minute=17, id="cert-renew")
    scheduler.start()
    yield
    scheduler.shutdown(wait=False)


app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))


# ---- auth helpers ----

def logged_in(request: Request) -> bool:
    token = request.cookies.get(auth.COOKIE_NAME, "")
    return bool(token) and auth.check_session_token(token)


def login_redirect() -> RedirectResponse:
    return RedirectResponse("/login", status_code=303)


def render(request: Request, template: str, **ctx) -> HTMLResponse:
    ctx.update(request=request, dry_run=config.DRY_RUN)
    return templates.TemplateResponse(request, template, ctx)


# ---- routes ----

@app.get("/health")
def health():
    return {"ok": True}


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    if logged_in(request):
        return RedirectResponse("/", status_code=303)
    return render(request, "login.html", error=None)


@app.post("/login")
def login(request: Request, password: str = Form("")):
    ip = request.client.host if request.client else "?"
    if auth.rate_limited(ip):
        return render(request, "login.html",
                      error="Too many attempts — wait 15 minutes and try again.")
    if not auth.verify_password(password):
        auth.record_failure(ip)
        return render(request, "login.html", error="Wrong password.")
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(
        auth.COOKIE_NAME, auth.make_session_token(),
        max_age=auth.SESSION_MAX_AGE, httponly=True, samesite="lax",
    )
    return response


@app.get("/logout")
def logout():
    response = login_redirect()
    response.delete_cookie(auth.COOKIE_NAME)
    return response


@app.get("/", response_class=HTMLResponse)
def leads_page(request: Request):
    if not logged_in(request):
        return login_redirect()
    return render(
        request, "leads.html",
        leads=db.list_leads(),
        runs=db.last_runs(5),
        running=research.is_running(),
        configured=bool(db.get_setting("tavily_api_key").strip()) or config.DRY_RUN,
        notion_on=bool(db.get_setting("notion_token").strip()),
    )


@app.post("/run")
def run_now(request: Request):
    if not logged_in(request):
        return login_redirect()
    research.start_in_background()
    return RedirectResponse("/", status_code=303)


@app.get("/export.csv")
def export_csv(request: Request):
    if not logged_in(request):
        return login_redirect()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["name", "website", "domain", "score", "reason", "query", "in_notion", "added"])
    for lead in db.list_leads(limit=10000):
        writer.writerow([
            lead["name"], lead["url"], lead["domain"], lead["score"],
            lead["reason"], lead["source_query"],
            "yes" if lead["notion_ok"] else "no", lead["created_at"],
        ])
    buf.seek(0)
    return StreamingResponse(
        buf, media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=leads.csv"},
    )


@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, saved: int = 0):
    if not logged_in(request):
        return login_redirect()
    values = db.all_settings()
    masked = {
        k: (f"••••••••{values[k][-4:]}" if values[k] else "")
        for k in db.SECRET_SETTINGS
    }
    return render(request, "settings.html", values=values, masked=masked, saved=bool(saved))


@app.post("/settings")
def save_settings(
    request: Request,
    tavily_api_key: str = Form(""),
    anthropic_api_key: str = Form(""),
    notion_token: str = Form(""),
    notion_parent_page: str = Form(""),
    certbot_email: str = Form(""),
    icp_description: str = Form(""),
    run_hour: str = Form("2"),
    max_queries: str = Form("6"),
    max_new_leads: str = Form("15"),
    model: str = Form("claude-opus-4-8"),
):
    if not logged_in(request):
        return login_redirect()
    # secret fields: an empty submit means "keep the stored value"
    for key, value in {
        "tavily_api_key": tavily_api_key,
        "anthropic_api_key": anthropic_api_key,
        "notion_token": notion_token,
    }.items():
        if value.strip():
            db.set_setting(key, value.strip())
    if notion_parent_page.strip() != db.get_setting("notion_parent_page"):
        db.set_setting("notion_parent_page", notion_parent_page.strip())
        db.set_setting("notion_db_id", "")  # new parent -> new Leads database
    db.set_setting("certbot_email", certbot_email.strip())
    db.set_setting("icp_description", icp_description.strip())
    db.set_setting("run_hour", str(max(0, min(23, int(run_hour or 2)))))
    db.set_setting("max_queries", str(max(1, min(12, int(max_queries or 6)))))
    db.set_setting("max_new_leads", str(max(1, min(50, int(max_new_leads or 15)))))
    db.set_setting("model", model.strip() or "claude-opus-4-8")
    return RedirectResponse("/settings?saved=1", status_code=303)


@app.get("/domains", response_class=HTMLResponse)
def domains_page(request: Request, message: str = "", error: str = ""):
    if not logged_in(request):
        return login_redirect()
    try:
        ip = domains.public_ip()
    except domains.DomainError:
        ip = "unknown"
    return render(request, "domains.html",
                  domains=db.list_domains(), ip=ip, message=message, error=error)


@app.post("/domains")
def connect_domain(request: Request, domain: str = Form(...)):
    if not logged_in(request):
        return login_redirect()
    try:
        message = domains.connect(domain)
        return RedirectResponse(f"/domains?message={message}", status_code=303)
    except domains.DomainError as e:
        return RedirectResponse(f"/domains?error={e}", status_code=303)


@app.post("/domains/delete")
def disconnect_domain(request: Request, domain: str = Form(...)):
    if not logged_in(request):
        return login_redirect()
    domains.disconnect(domain)
    return RedirectResponse("/domains?message=Domain disconnected.", status_code=303)
