"""The CallVerse web API: login/session, GET /api/company, the supervisor's Console reads, and, per company
(ShopNova under /api/shop, Atlas Travel under /api/atlas), the customer pages, the chat and the admin queue.

Routes (all under /api, JSON):
- POST /api/auth/login      {username, password, portal} -> the session (sets the HttpOnly cookie); portal =
                            shop | atlas | console, checked against the account file before a session exists
- POST /api/auth/logout     deletes the session and clears the cookie
- GET  /api/auth/session    the logged-in account, or 401
- GET  /api/company         the company profile (shopnova by default, ?company=atlas)
- GET  /api/console/tickets, /tickets/filters, /tickets/{id}                                    [supervisor]
- GET  /api/console/dashboard?days=, /api/console/agents?days=, /api/console/groq          (step 6) [supervisor]
- GET  /api/admin/dashboard?days=7|30|90  (ShopNova, view_dashboard), /api/atlas/admin/dashboard?days=7|30|all
- ShopNova customer (role user, company shopnova):
  GET  /api/shop/orders, /api/shop/orders/{id}                                                  (step 2)
  GET  /api/shop/chat?ticket=, POST /api/shop/chat/send (SSE), GET /api/shop/chat/job,
  GET  /api/shop/chat/job/stream, POST /api/shop/chat/tickets/{id}/read                         (step 3)
- ShopNova admin (permission approve_refunds, company shopnova):
  GET  /api/admin/approvals?status=, GET /api/admin/approvals/{id}, POST /api/admin/approvals/{id}/decide  (step 4)
- Atlas customer (role user, company atlas):                                                    (step 5)
  GET  /api/atlas/bookings, GET /api/atlas/bookings/{flight|hotel}/{id}
  the same chat routes under /api/atlas/chat (about_booking instead of about_order)
- Atlas admin (company atlas): the same approval routes under /api/atlas/admin/approvals (permission
  approve_refunds; refunds AND compensations) and the read-only Records under /api/atlas/admin/records/{table}
  (permission view_dashboard).
- Agent D's owner screens (T27, permission approve_refunds of the company):
  GET  /api/admin/promotions?status=pending|decided, POST /api/admin/promotions/{id}/decision, POST /api/admin/stock-check
  GET  /api/atlas/admin/deals?status=pending|decided,  POST /api/atlas/admin/deals/{id}/decision,  POST /api/atlas/admin/room-check

Protection: every route except login reads the session cookie; the role, the permission AND the company are
checked on the server through callverse.auth.accounts (never trusted from the browser), so an Atlas account
with the same numeric user id as a ShopNova one is refused on ShopNova's routes and the other way round. POST
routes need the X-Requested-With header (see settings.py). Chat jobs and recorded decisions are keyed by company
too. Read routes never create a missing company database (the data_ready check runs before any read function,
because the core's connect() would seed a missing file).

Run with: python -m webui.api.run  (127.0.0.1:8610). Tests: pytest webui/api/tests.
"""

from datetime import datetime

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from callverse import companies
from callverse.auth import accounts
from callverse.config import PROJECT_ROOT
from callverse.data import writes   # the ShopNova admin's write functions (Manage routes); the core checks every input again
from callverse.tickets import store
from callverse.tools.shopnova_tools import get_company_profile   # the function behind the platform's GET /company

from webui.api import admin, atlas_reads, auth, chat, console_reads, manage, owner, settings, shop_reads

ATLAS = "atlas"
COMPANY_NAMES = {companies.DEFAULT: "ShopNova", ATLAS: "Atlas Travel"}

ERRORS = {
    "not_logged_in": "Please log in to see this page.",
    "forbidden": "This page is for the CallVerse supervisor only.",
    "customer_only": "This page is for ShopNova customers only.",
    "busy_user": "Your previous message is still being processed. Please wait for the reply.",
    "empty_text": "Please type a message or add a photo.",
    "photo_too_large": "This photo is too large. Please send a photo under 5 MB.",
    "photo_type": "We could not read this photo. Please send a JPEG, PNG or WebP image.",
    "text_too_long": f"A message may have at most {chat.MAX_TEXT} characters.",
    "no_job": "No message is being processed.",
    "admin_only": "This page is for the ShopNova admin (permission approve_refunds) only.",
    "bad_portal": "Unknown sign-in page (allowed: shop, atlas, console).",
    "decision_in_progress": "A decision on this approval is already being processed. Check its state in a moment.",
    "reason_required": "A reason is required to refuse.",
    "already_decided": "This approval was already decided.",
    "recheck_refused": "The Coordinator's re-check refused the approval: nothing was written.",
    "write_refused": "Nothing was written.",
    "decision_uncertain": "The decision raised an error after it started. Its result is not confirmed: see the "
                          "recorded state.",
    "client_id_reused": "This request id was already used for a different request. Send the new one with a new id.",
    "setup_required": "ShopNova's data is not set up on this PC yet (shopnova.db is missing). Run the seed "
                      "command from docs/DEMO_RUNBOOK.md, then try again.",
    "bad_login": "Wrong username or password, or this account does not sign in on this page.",
    "no_accounts": accounts.NO_ACCOUNTS_MESSAGE,
    "csrf": f"Missing {settings.CSRF_HEADER} header.",
    "not_found": "Not found.",
    "scan_in_progress": "A check is already running. Wait for its result.",
    "scan_failed": "The check could not run. Nothing new was proposed.",
}


def _error(status: int, code: str, message: str | None = None, extra: dict | None = None) -> JSONResponse:
    """Every error answer has the same shape: {error: code, message: words, ...extra}. The browser keys on `error`."""
    return JSONResponse({"error": code, "message": message or ERRORS.get(code, code), **(extra or {})},
                        status_code=status)


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str | None = None, extra: dict | None = None):
        self.status, self.code, self.message, self.extra = status, code, message, extra


class LoginIn(BaseModel):
    username: str
    password: str
    portal: str = ""   # the sign-in page: shop | atlas | console (it limits WHO may sign in, it grants nothing)


class ProductIn(BaseModel):
    name: str
    category: str
    price: float
    stock: int
    client_id: str | None = None


class ProductPatch(BaseModel):
    name: str | None = None
    category: str | None = None
    price: float | None = None
    stock: int | None = None
    client_id: str | None = None


class UserIn(BaseModel):
    name: str
    email: str
    phone: str
    city: str
    client_id: str | None = None


class UserPatch(BaseModel):
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    city: str | None = None
    client_id: str | None = None


class StatusIn(BaseModel):
    status: str
    client_id: str | None = None


class ClientIdIn(BaseModel):
    client_id: str | None = None


class DecisionIn(BaseModel):
    approve: bool
    reason: str = ""
    client_id: str | None = None   # the browser's id for this decision: asking again with it returns the result


class ChatIn(BaseModel):
    text: str
    ticket_id: str | None = None
    about_order: int | None = None     # ShopNova: "Ask about this order"
    about_booking: int | None = None   # Atlas: "Ask about this booking" (the channel takes both as about_order)
    client_id: str | None = None       # the browser's id for this send: a retry with the same id is not run twice
    image_b64: str | None = None       # T35: one photo (JPEG / PNG / WebP, base64, at most 5 MB); never stored


def create_app(sessions: auth.SessionStore | None = None, jobs: chat.Registry | None = None,
               decisions: admin.Decisions | None = None) -> FastAPI:
    """Build the app. The tests give their own stores so each test starts clean."""
    sessions = sessions or auth.SessionStore()
    jobs = jobs or chat.Registry()
    decisions = decisions or admin.Decisions()
    scans = owner.Scans()   # T27: one Agent D scan at a time per company
    app = FastAPI(title="CallVerse web API", docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.state.sessions = sessions
    app.state.jobs = jobs
    app.state.decisions = decisions

    @app.exception_handler(ApiError)
    async def api_error(request: Request, exc: ApiError):
        return _error(exc.status, exc.code, exc.message, exc.extra)

    # ---------- dependencies ----------

    def current_username(request: Request) -> str | None:
        return sessions.username(request.cookies.get(settings.COOKIE_NAME))

    def logged_in(request: Request) -> dict:
        """The logged-in account, or 401 (also when the session expired or the account was removed)."""
        info = auth.session_info(current_username(request))
        if info is None:
            raise ApiError(401, "not_logged_in")
        return info

    def supervisor(request: Request) -> dict:
        """The logged-in SUPERVISOR, or 401 / 403. Called by every Console route."""
        username = current_username(request)
        if username is None:
            raise ApiError(401, "not_logged_in")
        found = auth.has_role(username, "supervisor")
        if found is None:
            raise ApiError(403, "forbidden")
        return found

    def customer_of(company: str):
        """A dependency: the logged-in CUSTOMER of `company` (role user, that company, linked to a user id), or
        401 / 403. accounts.check_role refuses an account of the other company even with the same numeric user id,
        and any admin or supervisor. The user id then comes from the accounts file, never from the request."""
        def dep(request: Request) -> dict:
            username = current_username(request)
            if username is None:
                raise ApiError(401, "not_logged_in")
            found = accounts.check_role({"authentication_status": True, "username": username}, "user", company)
            if found is None:
                raise ApiError(403, "customer_only", f"This page is for {COMPANY_NAMES[company]} customers only.")
            return found
        return dep

    def admin_of(company: str, permission: str = "approve_refunds"):
        """A dependency: the logged-in ADMIN of `company` with `permission`, or 401 / 403 (the same check as the
        Streamlit admin pages: accounts.check_permission). The username comes from the accounts file."""
        def dep(request: Request) -> dict:
            username = current_username(request)
            if username is None:
                raise ApiError(401, "not_logged_in")
            found = accounts.check_permission({"authentication_status": True, "username": username}, permission,
                                              company)
            if found is None:
                raise ApiError(403, "admin_only",
                               f"This page is for the {COMPANY_NAMES[company]} admin (permission {permission}) only.")
            return found
        return dep

    def data_ready(company: str) -> None:
        """503 when the company's database file is missing. Checked BEFORE any read function runs, because the
        core's connect() would create and seed a missing file: a read must never create data. The Console does
        not need this: its reads open files read-only and never create them."""
        if company == ATLAS:
            from callverse.data.atlas import db as company_db
            name = "atlas.db"
        else:
            from callverse.data import db as company_db
            name = "shopnova.db"
        if not company_db.db_path().exists():
            raise ApiError(503, "setup_required", f"{COMPANY_NAMES[company]}'s data is not set up on this PC yet "
                           f"({name} is missing). Run the seed command from docs/DEMO_RUNBOOK.md, then try again.")

    def csrf_checked(request: Request) -> None:
        if request.headers.get(settings.CSRF_HEADER) != settings.CSRF_VALUE:
            raise ApiError(403, "csrf")

    shopnova_customer = customer_of(companies.DEFAULT)
    atlas_customer = customer_of(ATLAS)

    # ---------- auth ----------

    @app.post("/api/auth/login", dependencies=[Depends(csrf_checked)])
    def login(body: LoginIn, request: Request, response: Response):
        """Sign in through one portal. Order: the portal name is known (else 400), the password is right, the
        account (from the FILE: role + company) belongs to that portal. A wrong password, an unknown username and
        an account of another portal get the SAME 401 `bad_login` (same words, a bcrypt check every time), so the
        page never says which part was wrong nor that an account exists elsewhere. A refused attempt changes
        nothing: an existing session stays as it was. A successful one replaces the browser's previous session
        (that token is deleted on the server): one browser, one session, whichever page it came through."""
        if accounts.load_accounts() is None:
            raise ApiError(503, "no_accounts")
        if body.portal not in auth.PORTALS:
            raise ApiError(400, "bad_portal")
        username = body.username.strip()
        if not auth.verify_password(username, body.password):
            raise ApiError(401, "bad_login")
        info = auth.session_info(username)
        if info is None or not auth.may_use_portal(info, body.portal):
            raise ApiError(401, "bad_login")
        sessions.delete(request.cookies.get(settings.COOKIE_NAME))   # the previous session of this browser, if any
        token = sessions.create(username)
        response.set_cookie(settings.COOKIE_NAME, token, httponly=True, samesite="strict", secure=False,
                            max_age=int(settings.SESSION_HOURS * 3600), path="/api")
        return {"session": {**info, "portal": body.portal}}

    @app.post("/api/auth/logout", dependencies=[Depends(csrf_checked)])
    def logout(request: Request, response: Response):
        sessions.delete(request.cookies.get(settings.COOKIE_NAME))
        response.delete_cookie(settings.COOKIE_NAME, path="/api")
        return {"ok": True}

    @app.get("/api/auth/session")
    def session(info: dict = Depends(logged_in)):
        """The logged-in account and the portal it belongs to (from the file), so the browser can send a
        logout or an expired session back to the right sign-in page."""
        return {"session": {**info, "portal": auth.portal_of(info)}}

    # ---------- company ----------

    @app.get("/api/company")
    def company(company: str = companies.DEFAULT, _: dict = Depends(logged_in)):
        """The company profile. ShopNova: the platform server's function. Atlas: its profile file from the
        company registry (callverse.tools.atlas_tools is not imported: it pulls in the policy search index)."""
        if company == companies.DEFAULT:
            profile = get_company_profile()
        else:
            try:
                import json
                profile = json.loads(companies.path(company, "profile_file").read_text(encoding="utf-8"))
            except ValueError as e:          # unknown company (companies.get raises ValueError) or broken JSON
                raise ApiError(404, "not_found", str(e))
            except OSError as e:
                profile = {"error": f"company profile not available: {type(e).__name__}"}
        if "error" in profile:
            raise ApiError(500, "profile_unavailable", profile["error"])
        return {"company": company, "profile": profile}

    # ---------- console (supervisor only, read only) ----------

    @app.get("/api/console/tickets")
    def tickets(company: str | None = None, status: str | None = None, priority: str | None = None,
                agent: str | None = None, _: dict = Depends(supervisor)):
        return console_reads.live_tickets(company or None, status or None, priority or None, agent or None)

    @app.get("/api/console/tickets/filters")
    def filters(_: dict = Depends(supervisor)):
        return console_reads.filter_values()

    @app.get("/api/console/tickets/{ticket_id}")
    def ticket(ticket_id: str, _: dict = Depends(supervisor)):
        detail = console_reads.ticket_detail(ticket_id)
        if detail is None:
            raise ApiError(404, "not_found", f"Ticket {ticket_id} does not exist.")
        return detail

    # ---------- Console dashboards (supervisor only, read only; step 6) ----------
    # The numbers are the core's (callverse.console.reads): the API adds only the period list, whether any
    # ticket exists at all, and the computer time the numbers were read at. Nothing is computed here.

    def console_days(days: str | None) -> int | None:
        """The period as the Console defines it: None (all), 7 or 30 days of COMPUTER time (reads.PERIODS)."""
        allowed = {str(v): v for v in console_reads.reads.PERIODS.values() if v is not None}
        if days in (None, "", "all"):
            return None
        if days not in allowed:
            raise ApiError(400, "bad_period", f"days must be one of all, {', '.join(allowed)}")
        return allowed[days]

    @app.get("/api/console/dashboard")
    def console_dashboard(days: str | None = None, _: dict = Depends(supervisor)):
        period = console_days(days)
        has_tickets = bool(console_reads.reads.ticket_ids())
        return {"days": period, "periods": console_reads.reads.PERIODS, "has_tickets": has_tickets,
                "no_tickets_message": console_reads.reads.NO_TICKETS, "clock": "computer time",
                "dashboard": console_reads.reads.dashboard(period) if has_tickets else None,
                "read_at": datetime.now().isoformat(timespec="seconds")}

    @app.get("/api/console/agents")
    def console_agents(days: str | None = None, _: dict = Depends(supervisor)):
        period = console_days(days)
        has_tickets = bool(console_reads.reads.ticket_ids())
        return {"days": period, "periods": console_reads.reads.PERIODS, "has_tickets": has_tickets,
                "no_tickets_message": console_reads.reads.NO_TICKETS, "clock": "computer time",
                "agents": console_reads.reads.agents(period) if has_tickets else [],
                "read_at": datetime.now().isoformat(timespec="seconds")}

    @app.get("/api/console/groq")
    def console_groq(_: dict = Depends(supervisor)):
        """Groq tokens used today (computer date) out of the configured daily quota, as the core counts them."""
        return {"groq_today": console_reads.reads.groq_today(), "read_at": datetime.now().isoformat(timespec="seconds")}

    # ---------- the two company admin dashboards (view_dashboard; step 6) ----------

    @app.get("/api/admin/dashboard")
    def shop_dashboard(days: int = 30, _: dict = Depends(admin_of(companies.DEFAULT, "view_dashboard"))):
        """admin_reads.dashboard for the last 7 / 30 / 90 days of the SIMULATION clock (its own periods)."""
        data_ready(companies.DEFAULT)
        from callverse.data import admin_reads
        if days not in admin_reads.PERIODS:
            raise ApiError(400, "bad_period", f"days must be one of {', '.join(str(d) for d in admin_reads.PERIODS)}")
        from callverse.data import shop_reads as core_shop_reads   # the readable category names of the shop
        return {"days": days, "periods": list(admin_reads.PERIODS), "default_days": admin_reads.DEFAULT_PERIOD,
                "clock": "simulation clock", "low_stock_limit": admin_reads.LOW_STOCK,
                "category_names": dict(core_shop_reads.CATEGORY_NAMES),
                "dashboard": admin_reads.dashboard(days), "read_at": datetime.now().isoformat(timespec="seconds")}

    @app.get("/api/atlas/admin/dashboard")
    def atlas_dashboard(days: str | None = None, _: dict = Depends(admin_of(ATLAS, "view_dashboard"))):
        """atlas_app_reads.dashboard for the last 7 / 30 days or all (its own periods, simulation clock)."""
        data_ready(ATLAS)
        from callverse.data.atlas import atlas_app_reads
        allowed = {str(v): v for v in atlas_app_reads.PERIODS.values() if v is not None}
        if days in (None, "", "all"):
            period = None
        elif days in allowed:
            period = allowed[days]
        else:
            raise ApiError(400, "bad_period", f"days must be one of all, {', '.join(allowed)}")
        return {"days": period, "periods": atlas_app_reads.PERIODS, "default": atlas_app_reads.DEFAULT_PERIOD,
                "clock": "simulation clock", "upcoming_days": atlas_app_reads.UPCOMING_DAYS,
                "dashboard": atlas_app_reads.dashboard(period), "read_at": datetime.now().isoformat(timespec="seconds")}

    # ---------- ShopNova customer (own orders only, read only) ----------

    @app.get("/api/shop/orders")
    def shop_orders(customer: dict = Depends(shopnova_customer)):
        data_ready(companies.DEFAULT)   # after the role check (a non-customer learns nothing about the files)
        return shop_reads.orders(customer["user_id"])

    @app.get("/api/shop/orders/{order_id}")
    def shop_order(order_id: int, customer: dict = Depends(shopnova_customer)):
        data_ready(companies.DEFAULT)
        found = shop_reads.order(customer["user_id"], order_id)
        if found is None:   # missing or not this customer's: the same answer on purpose
            raise ApiError(404, "not_found", f"Order {order_id} is not one of your orders.")
        return found

    # ---------- Atlas customer (own bookings only, read only; step 5) ----------

    @app.get("/api/atlas/bookings")
    def atlas_bookings(customer: dict = Depends(atlas_customer)):
        data_ready(ATLAS)
        return atlas_reads.bookings(customer["user_id"])

    @app.get("/api/atlas/bookings/{kind}/{booking_id}")
    def atlas_booking(kind: str, booking_id: int, customer: dict = Depends(atlas_customer)):
        """One owned booking of the given TYPE (flight / hotel). Wrong type, someone else's or missing: 404."""
        data_ready(ATLAS)
        found = atlas_reads.booking(customer["user_id"], kind, booking_id)
        if found is None:
            raise ApiError(404, "not_found", f"{kind.capitalize() if kind in atlas_reads.KINDS else 'This'} booking "
                           f"{booking_id} is not one of your bookings.")
        return found

    # ---------- the customer chat, per company (step 3; Atlas in step 5) ----------

    def register_chat(prefix: str, company: str, customer_dep, owns_context, context_word: str):
        """The chat routes of one company under `prefix`. owns_context(customer, id) says whether the "about
        this order / booking" id is the customer's own. Jobs are keyed by (company, user id): the two companies
        never share a job, even with the same numeric user id."""

        def owned_ticket(customer: dict, ticket_id: str | None) -> dict | None:
            """The ticket if it is this customer's AND this company's, else 404 (the same for a missing id)."""
            if not ticket_id:
                return None
            found = store.get_ticket(ticket_id)
            if found is None or found["company"] != company or found["user_id"] != customer["user_id"]:
                raise ApiError(404, "not_found", f"Ticket {ticket_id} is not one of your conversations.")
            return found

        def job_view(customer: dict) -> dict | None:
            job = jobs.current(company, customer["user_id"])
            return job.view() if job else None

        def stream_response(job):
            return StreamingResponse(chat.stream(job), media_type="text/event-stream",
                                     headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

        @app.get(f"{prefix}/chat")
        def get_chat(ticket: str | None = None, customer: dict = Depends(customer_dep)):
            """The conversation: the named owned ticket, or the customer's current ticket (the latest one a new
            message may still go on, as the Streamlit page does after a reload), or none (new conversation)."""
            data_ready(company)
            found = owned_ticket(customer, ticket) if ticket else store.current_ticket(company, customer["user_id"])
            return {
                "company": company,
                "ticket": found,
                "messages": store.messages(found["id"]) if found else [],
                "unread": [{"id": t["id"], "status": t["status"], "updated_real": t.get("updated_real")}
                           for t in store.unread_tickets(company, customer["user_id"])],
                "job": job_view(customer),
                "server_time": datetime.now().isoformat(timespec="seconds"),
            }

        @app.post(f"{prefix}/chat/send", dependencies=[Depends(csrf_checked)])
        def chat_send(body: ChatIn, customer: dict = Depends(customer_dep)):
            """Validate everything first (role, data, text, ticket and context ownership), then start the job
            and return its SSE stream. A second click with the same client_id gets the same job's stream."""
            data_ready(company)
            text = body.text.strip()
            try:
                image = chat.decode_photo(body.image_b64)   # checked before any job starts
            except ValueError as e:
                raise ApiError(400, str(e))   # photo_too_large or photo_type
            if not text and image is None:   # a photo with no text is allowed (the channel handles it)
                raise ApiError(400, "empty_text")
            if len(text) > chat.MAX_TEXT:
                raise ApiError(400, "text_too_long")
            owned_ticket(customer, body.ticket_id)
            about = body.about_booking if company == ATLAS else body.about_order
            if about is not None and not owns_context(customer, about):
                raise ApiError(404, "not_found", f"{context_word.capitalize()} {about} is not one of yours.")
            try:
                job, _created = jobs.start(customer["user_id"], company, text, body.ticket_id, about,
                                           body.client_id, chat.run_job, image=image)
            except ValueError as e:
                raise ApiError(409, str(e))   # busy_user or client_id_reused
            return stream_response(job)

        @app.get(f"{prefix}/chat/job")
        def chat_job(customer: dict = Depends(customer_dep)):
            return {"job": job_view(customer)}

        @app.get(f"{prefix}/chat/job/stream")
        def chat_job_stream(customer: dict = Depends(customer_dep)):
            job = jobs.current(company, customer["user_id"])
            if job is None:
                raise ApiError(404, "no_job")
            return stream_response(job)

        @app.post(f"{prefix}/chat/tickets/{{ticket_id}}/read", dependencies=[Depends(csrf_checked)])
        def chat_read(ticket_id: str, customer: dict = Depends(customer_dep)):
            """The customer opened this ticket's new reply: clear the notice (store.set_unread), owned only."""
            owned_ticket(customer, ticket_id)
            store.set_unread(ticket_id, False)
            return {"ok": True}

    register_chat("/api/shop", companies.DEFAULT, shopnova_customer,
                  lambda c, order_id: shop_reads.order_summary(c["user_id"], order_id) is not None, "order")
    register_chat("/api/atlas", ATLAS, atlas_customer,
                  lambda c, booking_id: atlas_reads.owned_any(c["user_id"], booking_id) is not None, "booking")

    # ---------- the admin approval queue, per company (step 4; Atlas in step 5) ----------

    def register_admin(prefix: str, company: str):
        admin_dep = admin_of(company, "approve_refunds")

        @app.get(f"{prefix}")
        def list_approvals(status: str = "pending", _: dict = Depends(admin_dep)):
            data_ready(company)
            if status == "pending":
                rows = admin.pending(company)
            elif status == "decided":
                rows = admin.decided(company)
            else:
                raise ApiError(400, "bad_status", "status must be pending or decided")
            return {"company": company, "status": status, "approvals": rows, "count": len(rows),
                    "server_time": datetime.now().isoformat(timespec="seconds")}

        @app.get(f"{prefix}/{{approval_id}}")
        def one_approval(approval_id: int, _: dict = Depends(admin_dep)):
            """The recorded state: the approval with its facts, what a decision has written so far (`evidence`,
            with its stage) and whether a decision on it is running in this process right now (`in_flight`)."""
            data_ready(company)
            found = admin.one(approval_id, company)
            if found is None:
                raise ApiError(404, "not_found", f"Approval {approval_id} is not one of {COMPANY_NAMES[company]}'s.")
            return {"approval": found, "evidence": admin.evidence(approval_id, company),
                    "in_flight": decisions.in_flight(company, approval_id)}

        @app.post(f"{prefix}/{{approval_id}}/decide", dependencies=[Depends(csrf_checked)])
        def decide_approval(approval_id: int, body: DecisionIn, who: dict = Depends(admin_dep)):
            """The decision. Browser inputs: the approval id, approve / refuse, the reason (and a client_id for
            recovery). The admin's username and the company come from the account. The approval's CURRENT state
            is re-read here (and again inside decide(), under its lock) before anything runs. The handler is a
            plain `def`: FastAPI runs it in a worker thread, so the slow part never blocks the event loop.

            Three kinds of answer: the core REFUSED (its error dict: nothing written, mapped to 4xx / 409); the
            core COMPLETED (200 with its result, recorded under the client_id); something RAISED after decide()
            began (500 `decision_uncertain` with the re-read evidence: the core may have committed its transaction,
            closed the approval, or not; the browser must not call that "nothing was done")."""
            data_ready(company)
            reason = body.reason.strip()
            if len(reason) > 1000:
                raise ApiError(400, "reason_too_long", "A reason may have at most 1000 characters.")
            kind, recorded = decisions.recorded(company, who["username"], approval_id, body.client_id,
                                                body.approve, reason)
            if kind == "mismatch":
                raise ApiError(409, "client_id_reused")
            if kind == "same":   # the identical decision asked again (lost response): its recorded result
                return {**recorded, "recorded": True}
            current = admin.one(approval_id, company)
            if current is None:
                raise ApiError(404, "not_found", f"Approval {approval_id} is not one of {COMPANY_NAMES[company]}'s.")
            if current["status"] != "pending":
                raise ApiError(409, "already_decided", f"Approval {approval_id} is already {current['status']} "
                               f"(by {current.get('decided_by') or '—'} at {current.get('decided_at') or '—'}).")
            if not body.approve and not reason:
                raise ApiError(400, "reason_required")
            if not decisions.begin(company, approval_id, {"admin": who["username"], "client_id": body.client_id,
                                                          "approve": body.approve, "reason": reason}):
                raise ApiError(409, "decision_in_progress")
            try:
                try:
                    out = admin.run_decision(who["username"], approval_id, body.approve, reason, company)
                except Exception as e:   # noqa: BLE001 — raised after the core started: the outcome is unknown
                    found = admin.evidence(approval_id, company)
                    raise ApiError(500, "decision_uncertain",
                                   f"{type(e).__name__}: {e}"[:300] + f" — recorded state: {found.get('stage_words')}",
                                   {"evidence": found})
                if "error" in out:   # the core refused explicitly: by its contract nothing was written
                    status, code = admin.classify(out)
                    raise ApiError(status, code, str(out["error"]))
                try:
                    result = admin.result_view(out)   # response preparation: a failure here is not a refusal
                except Exception as e:   # noqa: BLE001
                    found = admin.evidence(approval_id, company)
                    raise ApiError(500, "decision_uncertain",
                                   f"the decision completed but its answer could not be prepared "
                                   f"({type(e).__name__}: {e}) — recorded state: {found.get('stage_words')}",
                                   {"evidence": found})
                decisions.record(company, who["username"], approval_id, body.client_id, body.approve, reason, result)
                return result
            finally:
                decisions.end(company, approval_id)   # whatever happened above: the guard is released

    register_admin("/api/admin/approvals", companies.DEFAULT)
    register_admin("/api/atlas/admin/approvals", ATLAS)

    # ---------- Agent D's owner screens: Promotions (ShopNova), Hotel deals (Atlas), Check now (T27) ----------
    # The rows, the decisions and the scan are the core's (owner.py calls callverse.channels.approvals). A
    # decision uses the same guard as the approvals above (admin.Decisions, in its own slot per kind), so a
    # double click decides once and a lost answer asked again with the same client_id gets the recorded result.

    def register_owner(prefix: str, company: str, slot: str, word: str, read_list, read_one, decide):
        admin_dep = admin_of(company, "approve_refunds")

        @app.get(prefix)
        def list_rows(status: str = "pending", _: dict = Depends(admin_dep)):
            data_ready(company)
            if status not in ("pending", "decided"):
                raise ApiError(400, "bad_status", "status must be pending or decided")
            rows = read_list(status)
            return {"company": company, "status": status, "items": rows, "count": len(rows),
                    "server_time": datetime.now().isoformat(timespec="seconds")}

        @app.post(f"{prefix}/{{row_id}}/decision", dependencies=[Depends(csrf_checked)])
        def decide_row(row_id: int, body: DecisionIn, who: dict = Depends(admin_dep)):
            """Approve / refuse one pending row. The admin's username comes from the account, never the browser."""
            data_ready(company)
            reason = body.reason.strip()
            if len(reason) > 1000:
                raise ApiError(400, "reason_too_long", "A reason may have at most 1000 characters.")
            kind, recorded = decisions.recorded(slot, who["username"], row_id, body.client_id, body.approve, reason)
            if kind == "mismatch":
                raise ApiError(409, "client_id_reused")
            if kind == "same":
                return {**recorded, "recorded": True}
            current = read_one(row_id)
            if current is None:
                raise ApiError(404, "not_found", f"{word.capitalize()} {row_id} does not exist.")
            if current["status"] != "pending":
                raise ApiError(409, "already_decided", f"{word.capitalize()} {row_id} is already {current['status']} "
                               f"(by {current.get('decided_by') or '—'} on {current.get('decided_at') or '—'}).")
            if not body.approve and not reason:
                raise ApiError(400, "reason_required")
            if not decisions.begin(slot, row_id, {"admin": who["username"], "client_id": body.client_id,
                                                  "approve": body.approve, "reason": reason}):
                raise ApiError(409, "decision_in_progress", f"A decision on this {word} is already being processed.")
            try:
                out = decide(who["username"], row_id, body.approve, reason)
                if "error" in out:   # the core refused: by its contract nothing was written
                    status, code = owner.classify(out)
                    raise ApiError(status, code, str(out["error"]))
                result = {"item": read_one(row_id) or out}
                decisions.record(slot, who["username"], row_id, body.client_id, body.approve, reason, result)
                return result
            finally:
                decisions.end(slot, row_id)

    register_owner("/api/admin/promotions", companies.DEFAULT, owner.PROMOTION_SLOT, "promotion",
                   owner.promotions, owner.one_promotion, lambda *a: owner.decide_promotion(*a))
    register_owner("/api/atlas/admin/deals", ATLAS, owner.DEAL_SLOT, "deal",
                   owner.deals, owner.one_deal, lambda *a: owner.decide_deal(*a))

    def register_scan(path: str, company: str):
        @app.post(path, dependencies=[Depends(csrf_checked)])
        def check_now(_: dict = Depends(admin_of(company, "approve_refunds"))):
            """Agent D's scan once (the Streamlit "Check now" button): counts of what it found and proposed."""
            data_ready(company)
            if not scans.begin(company):
                raise ApiError(409, "scan_in_progress")
            try:
                try:
                    counts = owner.run_scan(company)
                except Exception as e:   # noqa: BLE001 — shown as an error state on the dashboard
                    raise ApiError(500, "scan_failed", f"The check could not run ({type(e).__name__}: {e})"[:300])
                return {"company": company, "counts": counts, "read_at": datetime.now().isoformat(timespec="seconds")}
            finally:
                scans.end(company)

    register_scan("/api/admin/stock-check", companies.DEFAULT)
    register_scan("/api/atlas/admin/room-check", ATLAS)

    # ---------- ShopNova admin: Manage (products, orders, clients, refunds, admin log) ----------
    # Thin wrappers around callverse.data.admin_reads / writes (webui/api/manage.py): the same functions and
    # the same per-table permission as the Streamlit Manage page. Nothing is deleted: a product is deactivated,
    # an order is cancelled (only unpaid, not shipped). Refunds are never written here.

    SHOP = companies.DEFAULT

    def manage_write(kind: str, who: dict, client_id: str | None, payload: tuple, call):
        '''One core write, once per request id; the core's refusal becomes 4xx with the field it names.'''
        data_ready(SHOP)
        try:
            return manage.run(kind, who["username"], client_id, payload, call)
        except manage.Refused as e:
            raise ApiError(e.status, e.code, e.message, {"field": e.field} if e.field else None) from None
        except manage.Duplicate as e:
            raise ApiError(409, e.code, e.message) from None

    def given(body: BaseModel) -> dict:
        '''The fields the browser sent (None = not changed), without the request id.'''
        return {k: v for k, v in body.model_dump().items() if k != "client_id" and v is not None}

    @app.get("/api/admin/manage/options")
    def manage_options(_: dict = Depends(admin_of(SHOP, "view_dashboard"))):
        data_ready(SHOP)
        return manage.options()

    @app.get("/api/admin/manage/{table}")
    def manage_table(table: str, request: Request, search: str = "", page: int = 1):
        if table not in manage.TABLE_PERMISSION:
            raise ApiError(404, "not_found", f"No table '{table}'.")
        admin_of(SHOP, manage.TABLE_PERMISSION[table])(request)   # the table's own permission
        data_ready(SHOP)
        return manage.log() if table == "log" else manage.page(table, search, page)

    @app.post("/api/admin/manage/products", dependencies=[Depends(csrf_checked)])
    def manage_create_product(body: ProductIn, who: dict = Depends(admin_of(SHOP, "edit_catalogue"))):
        fields = given(body)
        return manage_write("create_product", who, body.client_id, tuple(sorted(fields.items())),
                            lambda: writes.create_product(who["username"], body.name, body.category, body.price, body.stock))

    @app.post("/api/admin/manage/products/{product_id}", dependencies=[Depends(csrf_checked)])
    def manage_update_product(product_id: int, body: ProductPatch, who: dict = Depends(admin_of(SHOP, "edit_catalogue"))):
        fields = given(body)
        return manage_write("update_product", who, body.client_id, (product_id, tuple(sorted(fields.items()))),
                            lambda: writes.update_product(who["username"], product_id, **fields))

    @app.post("/api/admin/manage/products/{product_id}/deactivate", dependencies=[Depends(csrf_checked)])
    def manage_deactivate_product(product_id: int, body: ClientIdIn, who: dict = Depends(admin_of(SHOP, "edit_catalogue"))):
        return manage_write("deactivate_product", who, body.client_id, (product_id,),
                            lambda: writes.deactivate_product(who["username"], product_id))

    @app.post("/api/admin/manage/products/{product_id}/reactivate", dependencies=[Depends(csrf_checked)])
    def manage_reactivate_product(product_id: int, body: ClientIdIn, who: dict = Depends(admin_of(SHOP, "edit_catalogue"))):
        return manage_write("reactivate_product", who, body.client_id, (product_id,),
                            lambda: writes.reactivate_product(who["username"], product_id))

    @app.post("/api/admin/manage/orders/{order_id}/status", dependencies=[Depends(csrf_checked)])
    def manage_order_status(order_id: int, body: StatusIn, who: dict = Depends(admin_of(SHOP, "edit_orders"))):
        return manage_write("admin_set_order_status", who, body.client_id, (order_id, body.status),
                            lambda: writes.admin_set_order_status(who["username"], order_id, body.status))

    @app.post("/api/admin/manage/users", dependencies=[Depends(csrf_checked)])
    def manage_create_user(body: UserIn, who: dict = Depends(admin_of(SHOP, "edit_users"))):
        fields = given(body)
        return manage_write("create_user", who, body.client_id, tuple(sorted(fields.items())),
                            lambda: writes.create_user(who["username"], body.name, body.email, body.phone, body.city))

    @app.post("/api/admin/manage/users/{user_id}", dependencies=[Depends(csrf_checked)])
    def manage_update_user(user_id: int, body: UserPatch, who: dict = Depends(admin_of(SHOP, "edit_users"))):
        fields = given(body)
        return manage_write("update_user", who, body.client_id, (user_id, tuple(sorted(fields.items()))),
                            lambda: writes.update_user(who["username"], user_id, **fields))

    # ---------- Atlas admin: Records (read only, permission view_dashboard; step 5) ----------

    @app.get("/api/atlas/admin/records/{table}")
    def atlas_records(table: str, search: str = "", page: int = 1,
                      _: dict = Depends(admin_of(ATLAS, "view_dashboard"))):
        """One page of one Atlas table (atlas_app_reads: hotels, flights, users, refunds, compensations) or the
        admin log, exactly as the Streamlit Records page reads them."""
        data_ready(ATLAS)
        from callverse.data.atlas import atlas_app_reads
        readers = {"hotels": atlas_app_reads.hotel_bookings_page, "flights": atlas_app_reads.flight_bookings_page,
                   "users": atlas_app_reads.users_page, "refunds": atlas_app_reads.refunds_page,
                   "compensations": atlas_app_reads.compensations_page}
        if table == "log":
            rows = atlas_app_reads.admin_log(50)
            return {"table": table, "items": rows, "total": len(rows), "page": 1, "pages": 1, "page_size": 50}
        if table not in readers:
            raise ApiError(404, "not_found", f"No table '{table}'.")
        found = readers[table](search or "", max(1, int(page)))
        return {"table": table, **found, "page_size": atlas_app_reads.PAGE_SIZE}

    @app.get("/api/health")
    def health():
        return {"ok": True, "tickets_db": str(store.db_path().relative_to(PROJECT_ROOT))
                if store.db_path().is_relative_to(PROJECT_ROOT) else str(store.db_path())}

    return app


def apply_env_overrides() -> None:
    """Point the account store / databases at the files named by the CALLVERSE_WEBUI_* variables (demo, tests)."""
    if settings.ACCOUNTS_FILE:
        accounts.use_accounts(settings.ACCOUNTS_FILE)
    if settings.TICKETS_DB:
        store.use_db(settings.TICKETS_DB)
    if settings.SHOPNOVA_DB:
        from callverse.data import db as shopnova_db
        shopnova_db.use_db(settings.SHOPNOVA_DB)
    if settings.ATLAS_DB:
        from callverse.data.atlas import db as atlas_db
        atlas_db.use_db(settings.ATLAS_DB)
    if settings.FAKE_CHAT:
        from webui.api.dev_fixture import fake_send, fake_slm
        chat.use_send_fn(fake_send)
        admin.use_slm_fn(fake_slm)
        print("CHAT IS FAKE (CALLVERSE_WEBUI_FAKE_CHAT=1): replies are test data, no model runs.")
