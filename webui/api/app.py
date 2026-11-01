"""The CallVerse web API (step 1): login/session, GET /api/company, and the supervisor's Console reads.

Routes (all under /api, JSON):
- POST /api/auth/login      {username, password} -> the session (sets the HttpOnly cookie)
- POST /api/auth/logout     deletes the session and clears the cookie
- GET  /api/auth/session    the logged-in account, or 401
- GET  /api/company         the company profile (shopnova by default, ?company=atlas), the same function as the
                            platform server's GET /company
- GET  /api/console/tickets          the Live tickets table (filters: company, status, priority, agent)  [supervisor]
- GET  /api/console/tickets/filters  the values of the four filters                                       [supervisor]
- GET  /api/console/tickets/{id}     one ticket with its conversation and the steps per message          [supervisor]
- GET  /api/shop/orders              the logged-in ShopNova customer's own orders (step 2)                 [shopnova user]
- GET  /api/shop/orders/{id}         one owned order with tracking and refunds; missing or another user's
                                     order: the same 404                                                   [shopnova user]
- GET  /api/shop/chat?ticket=        the chat: the current (or the named, owned) ticket, its messages, the
                                     unread-reply notices and the customer's running / last job (step 3)   [shopnova user]
- POST /api/shop/chat/send           {text, ticket_id?, about_order?, client_id?} -> an SSE stream of the
                                     channel's live steps, then the saved result (chat.py)                 [shopnova user]
- GET  /api/shop/chat/job            the customer's running / last job (recovery after a disconnect)      [shopnova user]
- GET  /api/shop/chat/job/stream     re-attach to the running job's SSE stream (replays the steps so far) [shopnova user]
- POST /api/shop/chat/tickets/{id}/read   the customer opened this ticket's new reply (owned ticket only) [shopnova user]

Protection: every route except login reads the session cookie; the Console routes need the supervisor role
(checked on the server through callverse.auth.accounts, never trusted from the browser). POST routes need the
X-Requested-With header (see settings.py). The Console reads use read-only SQLite connections (reads.py) and no
model is loaded: this process imports no agent, no LLM layer and no pipeline.

Run with: python -m webui.api.run  (127.0.0.1:8610). Tests: pytest webui/api/tests.
"""

from datetime import datetime

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from callverse import companies
from callverse.auth import accounts
from callverse.config import PROJECT_ROOT
from callverse.tickets import store
from callverse.tools.shopnova_tools import get_company_profile   # the function behind the platform's GET /company

from webui.api import auth, chat, console_reads, settings, shop_reads

ERRORS = {
    "not_logged_in": "Please log in to see this page.",
    "forbidden": "This page is for the CallVerse supervisor only.",
    "customer_only": "This page is for ShopNova customers only.",
    "busy_user": "Your previous message is still being processed. Please wait for the reply.",
    "client_id_reused": "This request id was already used for a different message. Send the new message with a new id.",
    "empty_text": "Please type a message.",
    "text_too_long": f"A message may have at most {chat.MAX_TEXT} characters.",
    "no_job": "No message is being processed.",
    "setup_required": "ShopNova's data is not set up on this PC yet (shopnova.db is missing). Run the seed "
                      "command from docs/DEMO_RUNBOOK.md, then try again.",
    "bad_login": "Wrong username or password.",
    "no_accounts": accounts.NO_ACCOUNTS_MESSAGE,
    "csrf": f"Missing {settings.CSRF_HEADER} header.",
    "not_found": "Not found.",
}


def _error(status: int, code: str, message: str | None = None) -> JSONResponse:
    """Every error answer has the same shape: {error: code, message: words}. The browser keys on `error`."""
    return JSONResponse({"error": code, "message": message or ERRORS.get(code, code)}, status_code=status)


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str | None = None):
        self.status, self.code, self.message = status, code, message


class LoginIn(BaseModel):
    username: str
    password: str


class ChatIn(BaseModel):
    text: str
    ticket_id: str | None = None
    about_order: int | None = None
    client_id: str | None = None   # the browser's id for this send: a retry with the same id is not run twice


def create_app(sessions: auth.SessionStore | None = None, jobs: chat.Registry | None = None) -> FastAPI:
    """Build the app. The tests give their own SessionStore / job Registry so each test starts clean."""
    sessions = sessions or auth.SessionStore()
    jobs = jobs or chat.Registry()
    app = FastAPI(title="CallVerse web API", docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.state.sessions = sessions
    app.state.jobs = jobs

    @app.exception_handler(ApiError)
    async def api_error(request: Request, exc: ApiError):
        return _error(exc.status, exc.code, exc.message)

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

    def shopnova_customer(request: Request) -> dict:
        """The logged-in ShopNova CUSTOMER (role user, company shopnova, linked to a user id), or 401 / 403.
        accounts.check_role refuses an Atlas account even with the same numeric user id, and any admin or
        supervisor. The user id then comes from the accounts file, never from the request."""
        username = current_username(request)
        if username is None:
            raise ApiError(401, "not_logged_in")
        found = accounts.check_role({"authentication_status": True, "username": username}, "user",
                                    companies.DEFAULT)
        if found is None:
            raise ApiError(403, "customer_only")
        return found

    def shop_data_ready() -> None:
        """503 when ShopNova's database file is missing. Checked BEFORE any read function runs, because
        callverse.data.db.connect() would create and seed a missing file: a read must never create data.
        The Console does not need this: its reads open files read-only and never create them."""
        from callverse.data import db as shopnova_db
        if not shopnova_db.db_path().exists():
            raise ApiError(503, "setup_required")

    def csrf_checked(request: Request) -> None:
        if request.headers.get(settings.CSRF_HEADER) != settings.CSRF_VALUE:
            raise ApiError(403, "csrf")

    # ---------- auth ----------

    @app.post("/api/auth/login", dependencies=[Depends(csrf_checked)])
    def login(body: LoginIn, response: Response):
        if accounts.load_accounts() is None:
            raise ApiError(503, "no_accounts")
        username = body.username.strip()
        if not auth.verify_password(username, body.password):
            raise ApiError(401, "bad_login")
        info = auth.session_info(username)
        if info is None:
            raise ApiError(401, "bad_login")
        token = sessions.create(username)
        response.set_cookie(settings.COOKIE_NAME, token, httponly=True, samesite="strict", secure=False,
                            max_age=int(settings.SESSION_HOURS * 3600), path="/api")
        return {"session": info}

    @app.post("/api/auth/logout", dependencies=[Depends(csrf_checked)])
    def logout(request: Request, response: Response):
        sessions.delete(request.cookies.get(settings.COOKIE_NAME))
        response.delete_cookie(settings.COOKIE_NAME, path="/api")
        return {"ok": True}

    @app.get("/api/auth/session")
    def session(info: dict = Depends(logged_in)):
        return {"session": info}

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

    # ---------- ShopNova customer (own orders only, read only) ----------

    @app.get("/api/shop/orders")
    def shop_orders(customer: dict = Depends(shopnova_customer)):
        shop_data_ready()   # after the role check (a non-customer learns nothing about the files)
        return shop_reads.orders(customer["user_id"])

    @app.get("/api/shop/orders/{order_id}")
    def shop_order(order_id: int, customer: dict = Depends(shopnova_customer)):
        shop_data_ready()
        found = shop_reads.order(customer["user_id"], order_id)
        if found is None:   # missing or not this customer's: the same answer on purpose
            raise ApiError(404, "not_found", f"Order {order_id} is not one of your orders.")
        return found

    # ---------- ShopNova customer chat (step 3): the channel, in a worker thread, streamed as SSE ----------

    def owned_ticket(customer: dict, ticket_id: str | None) -> dict | None:
        """The ticket if it is this customer's AND ShopNova's, else 404 (the same for a missing id)."""
        if not ticket_id:
            return None
        ticket = store.get_ticket(ticket_id)
        if ticket is None or ticket["company"] != companies.DEFAULT or ticket["user_id"] != customer["user_id"]:
            raise ApiError(404, "not_found", f"Ticket {ticket_id} is not one of your conversations.")
        return ticket

    def owned_order(customer: dict, order_id: int | None) -> None:
        """404 unless the order is one of this customer's (checked BEFORE the channel is called)."""
        if order_id is None:
            return
        if shop_reads.order_summary(customer["user_id"], order_id) is None:
            raise ApiError(404, "not_found", f"Order {order_id} is not one of your orders.")

    def job_view(customer: dict) -> dict | None:
        job = jobs.current(companies.DEFAULT, customer["user_id"])
        return job.view() if job else None

    @app.get("/api/shop/chat")
    def shop_chat(ticket: str | None = None, customer: dict = Depends(shopnova_customer)):
        """The conversation to show: the named owned ticket, or the customer's current ticket (the latest one a
        new message may still go on, as the Streamlit page does after a reload), or none (new conversation)."""
        shop_data_ready()
        found = owned_ticket(customer, ticket) if ticket else store.current_ticket(companies.DEFAULT, customer["user_id"])
        return {
            "ticket": found,
            "messages": store.messages(found["id"]) if found else [],
            "unread": [{"id": t["id"], "status": t["status"], "updated_real": t.get("updated_real")}
                       for t in store.unread_tickets(companies.DEFAULT, customer["user_id"])],
            "job": job_view(customer),
            "server_time": datetime.now().isoformat(timespec="seconds"),
        }

    @app.post("/api/shop/chat/send", dependencies=[Depends(csrf_checked)])
    def shop_chat_send(body: ChatIn, customer: dict = Depends(shopnova_customer)):
        """Validate everything first (role, data, text, ticket and order ownership), then start the job and
        return its SSE stream. A second click with the same client_id gets the same job's stream."""
        shop_data_ready()
        text = body.text.strip()
        if not text:
            raise ApiError(400, "empty_text")
        if len(text) > chat.MAX_TEXT:
            raise ApiError(400, "text_too_long")
        owned_ticket(customer, body.ticket_id)
        owned_order(customer, body.about_order)
        try:
            job, _created = jobs.start(customer["user_id"], companies.DEFAULT, text, body.ticket_id, body.about_order,
                                       body.client_id, chat.run_job)
        except ValueError as e:
            raise ApiError(409, str(e))   # busy_user or client_id_reused (both are in ERRORS)
        return StreamingResponse(chat.stream(job), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.get("/api/shop/chat/job")
    def shop_chat_job(customer: dict = Depends(shopnova_customer)):
        return {"job": job_view(customer)}

    @app.get("/api/shop/chat/job/stream")
    def shop_chat_job_stream(customer: dict = Depends(shopnova_customer)):
        job = jobs.current(companies.DEFAULT, customer["user_id"])
        if job is None:
            raise ApiError(404, "no_job")
        return StreamingResponse(chat.stream(job), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.post("/api/shop/chat/tickets/{ticket_id}/read", dependencies=[Depends(csrf_checked)])
    def shop_chat_read(ticket_id: str, customer: dict = Depends(shopnova_customer)):
        """The customer opened this ticket's new reply: clear the notice (store.set_unread), owned ticket only."""
        owned_ticket(customer, ticket_id)
        store.set_unread(ticket_id, False)
        return {"ok": True}

    @app.get("/api/health")
    def health():
        return {"ok": True, "tickets_db": str(store.db_path().relative_to(PROJECT_ROOT))
                if store.db_path().is_relative_to(PROJECT_ROOT) else str(store.db_path())}

    return app


def apply_env_overrides() -> None:
    """Point the account store / tickets DB at the files named by the CALLVERSE_WEBUI_* variables (demo, tests)."""
    if settings.ACCOUNTS_FILE:
        accounts.use_accounts(settings.ACCOUNTS_FILE)
    if settings.TICKETS_DB:
        store.use_db(settings.TICKETS_DB)
    if settings.SHOPNOVA_DB:
        from callverse.data import db as shopnova_db
        shopnova_db.use_db(settings.SHOPNOVA_DB)
    if settings.FAKE_CHAT:
        from webui.api.dev_fixture import fake_send
        chat.use_send_fn(fake_send)
        print("CHAT IS FAKE (CALLVERSE_WEBUI_FAKE_CHAT=1): replies are test data, no model runs.")
