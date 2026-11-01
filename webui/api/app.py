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

Protection: every route except login reads the session cookie; the Console routes need the supervisor role
(checked on the server through callverse.auth.accounts, never trusted from the browser). POST routes need the
X-Requested-With header (see settings.py). The Console reads use read-only SQLite connections (reads.py) and no
model is loaded: this process imports no agent, no LLM layer and no pipeline.

Run with: python -m webui.api.run  (127.0.0.1:8610). Tests: pytest webui/api/tests.
"""

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from callverse import companies
from callverse.auth import accounts
from callverse.config import PROJECT_ROOT
from callverse.tickets import store
from callverse.tools.shopnova_tools import get_company_profile   # the function behind the platform's GET /company

from webui.api import auth, console_reads, settings, shop_reads

ERRORS = {
    "not_logged_in": "Please log in to see this page.",
    "forbidden": "This page is for the CallVerse supervisor only.",
    "customer_only": "This page is for ShopNova customers only.",
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


def create_app(sessions: auth.SessionStore | None = None) -> FastAPI:
    """Build the app. The tests give their own SessionStore so each test starts logged out."""
    sessions = sessions or auth.SessionStore()
    app = FastAPI(title="CallVerse web API", docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.state.sessions = sessions

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
