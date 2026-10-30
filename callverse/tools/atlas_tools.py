"""Atlas Travel's tools (T21): what an agent may use when the ticket is Atlas's.

Same idea as shopnova_tools.py: READ tools only here, each one a plain function that returns a dict (or {"error": ...},
so the model can tell the client instead of guessing). The facts come from callverse/data/atlas/reads.py, which already
hides the fields an agent must not see.

SCHEMAS describes each tool for the LLM. Being listed here does NOT give an agent access: the allow-lists in
registry.py decide that, per company and agent.

Why separate tools, and not ShopNova's with a company argument? The argument would be one more thing the model could
get wrong. Here an Atlas agent simply has no way to reach ShopNova's data, and the other way round.
"""

import json

from callverse import companies
from callverse.data.atlas import reads
from callverse.kb import search

COMPANY = "atlas"


def get_company_profile() -> dict:
    """Return the Atlas Travel profile: what it sells, hotels, airlines, currency, payment, support."""
    try:
        return json.loads(companies.path(COMPANY, "profile_file").read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:  # missing or broken file: tell the caller, never raise
        return {"error": f"company profile not available: {type(e).__name__}"}


def search_policy(query: str) -> dict:
    """Find Atlas's rules by meaning, in Atlas's own index (never in another company's)."""
    return search.company_search_tool(COMPANY, query)


# Name -> Python function, used by the registry to actually run a tool.
FUNCTIONS = {
    "get_user": reads.get_user,
    "get_hotel_booking": reads.get_hotel_booking,
    "get_flight_booking": reads.get_flight_booking,
    "get_flight": reads.get_flight,
    "get_refunds": reads.get_refunds,
    "get_company_profile": get_company_profile,
    "search_policy": search_policy,
}

BOOKING_ID = {"type": "integer", "description": "Booking number, e.g. 7005"}

# JSON schemas for tool calling (OpenAI "tools" format). Short on purpose: they are re-sent with every model call.
SCHEMAS = {
    "get_user": {
        "type": "function",
        "function": {
            "name": "get_user",
            "description": "Find an Atlas Travel client by email, phone or user id. Give exactly one of them.",
            "parameters": {
                "type": "object",
                "properties": {"email": {"type": "string"}, "phone": {"type": "string"},
                               "user_id": {"type": "integer"}},
            },
        },
    },
    "get_hotel_booking": {
        "type": "function",
        "function": {
            "name": "get_hotel_booking",
            "description": "Get a hotel booking: hotel, dates, deposit type, room booked and given, total, paid, "
                           "status, room_changed, days_before_arrival, refunded_total.",
            "parameters": {"type": "object", "properties": {"booking_id": BOOKING_ID}, "required": ["booking_id"]},
        },
    },
    "get_flight_booking": {
        "type": "function",
        "function": {
            "name": "get_flight_booking",
            "description": "Get a flight booking with its flight: route, distance, schedule, delays in minutes, "
                           "cancelled, recorded cause, notice_days, paid, refunded_total.",
            "parameters": {"type": "object", "properties": {"booking_id": BOOKING_ID}, "required": ["booking_id"]},
        },
    },
    "get_flight": {
        "type": "function",
        "function": {
            "name": "get_flight",
            "description": "Get one flight by its flight id: route, schedule, delays, cancellation and cause.",
            "parameters": {"type": "object", "properties": {"flight_id": {"type": "integer"}},
                           "required": ["flight_id"]},
        },
    },
    "get_refunds": {
        "type": "function",
        "function": {
            "name": "get_refunds",
            "description": "List the refunds of a booking and refunded_total (TND). Empty list = no refund yet.",
            "parameters": {
                "type": "object",
                "properties": {"booking_type": {"type": "string", "enum": ["hotel", "flight"]},
                               "booking_id": BOOKING_ID},
                "required": ["booking_type", "booking_id"],
            },
        },
    },
    "get_company_profile": {
        "type": "function",
        "function": {
            "name": "get_company_profile",
            "description": "Get the Atlas Travel profile: what it sells, hotels, airlines, currency, payment methods, "
                           "support channels and languages.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    "search_policy": {
        "type": "function",
        "function": {
            "name": "search_policy",
            "description": "Find the Atlas Travel rules that match a request, by meaning.",
            "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
        },
    },
}
