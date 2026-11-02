"""Agent C's tools at Atlas Travel (P20): one READ tool and two PROPOSAL tools (they only propose).

    find_alternative_flights(booking_id)   flights on the same route that leave later, are not cancelled and are still
                                           to come (status "scheduled"): what C may offer after a cancellation (AT-FLT-01)
    propose_rebooking(...)                 move a cancelled booking to one of those flights (rule AT-FLT-01)
    propose_assistance(...)                special assistance, e.g. a wheelchair (rule AT-AST-01); mobility needs are
                                           sensitive: the client's explicit yes is required (atlas_special.py)
The Coordinator (callverse/coordinator/atlas_special.py) re-reads everything and writes only after the client's yes.
"""

from contextlib import closing

from callverse import trace
from callverse.data.atlas import reads
from callverse.data.atlas.db import connect

ASSISTANCE_KINDS = ("wheelchair",)   # the kind the Atlas data has (assistance_requests.kind)
MAX_ALTERNATIVES = 5


def alternatives(booking: dict) -> list[dict]:
    """Later, not cancelled, scheduled flights on the booking's route (soonest first)."""
    with closing(connect()) as con:
        rows = con.execute("SELECT id, carrier_name, flight_number, origin, destination, scheduled_departure"
                           " FROM flights WHERE origin = ? AND destination = ? AND scheduled_departure > ?"
                           " AND cancelled = 0 AND status = 'scheduled' ORDER BY scheduled_departure LIMIT ?",
                           (booking["origin"], booking["destination"], booking["scheduled_departure"],
                            MAX_ALTERNATIVES)).fetchall()
    return [dict(r) for r in rows]


def find_alternative_flights(booking_id=None) -> dict:
    """TOOL: the flights C may offer instead of a cancelled one. Read only."""
    if isinstance(booking_id, bool) or not isinstance(booking_id, int):
        return {"error": "booking_id must be an integer"}
    booking = reads.get_flight_booking(booking_id)
    if "error" in booking:
        return booking
    found = alternatives(booking)
    return {"booking_id": booking_id, "route": f"{booking['origin']}-{booking['destination']}",
            "original_departure": booking["scheduled_departure"], "flights": found,
            # T29 (F6): with no flight, C makes no offer; the pipeline hands the case to a colleague by code.
            "note": "" if found else "no later flight on this route in the schedule: make no offer, a colleague "
                                     "takes the case"}


def _problems(fields: dict) -> list[str]:
    problems = []
    for name in ("booking_id", "new_flight_id"):
        if name in fields and (isinstance(fields[name], bool) or not isinstance(fields[name], int)):
            problems.append(f"{name} must be an integer")
    if "kind" in fields and fields["kind"] not in ASSISTANCE_KINDS:
        problems.append(f"kind must be one of {list(ASSISTANCE_KINDS)}")
    if not isinstance(fields.get("user_confirmed"), bool):
        problems.append("user_confirmed must be true or false (true only if the client said yes)")
    if not isinstance(fields.get("user_quote"), str) or not fields["user_quote"].strip():
        problems.append("user_quote must quote the client's own words")
    return problems


def _propose(action: str, fields: dict) -> dict:
    problems = _problems(fields)
    if problems:
        trace.log("proposal_refused", "atlas_c_tools", {"action": action, "fields": fields, "problems": problems})
        return {"error": "proposal refused: " + "; ".join(problems)}
    trace.log("proposal", "atlas_c_tools", {"action": action, **fields})
    return {"status": "submitted to Coordinator"}


def propose_rebooking(booking_id=None, new_flight_id=None, user_confirmed=None, user_quote=None) -> dict:
    """Propose moving a cancelled flight booking to a later flight (AT-FLT-01). Changes nothing.
    T29 (F6): refused by code when the route has NO later flight, so C cannot offer a flight it invented."""
    fields = {"booking_id": booking_id, "new_flight_id": new_flight_id, "user_confirmed": user_confirmed,
              "user_quote": user_quote}
    if isinstance(booking_id, int) and not isinstance(booking_id, bool):
        booking = reads.get_flight_booking(booking_id)
        if "error" not in booking and not alternatives(booking):
            trace.log("proposal_refused", "atlas_c_tools", {"action": "rebook", "fields": fields,
                                                            "problems": [NO_LATER_FLIGHT]})
            return {"error": f"proposal refused: {NO_LATER_FLIGHT}; make no offer, a colleague takes the case"}
    return _propose("rebook", fields)


# T29 (F6): the reason C's case goes to a colleague when find_alternative_flights finds nothing.
NO_LATER_FLIGHT = "no later flight on this route"


def no_later_flight(tool_calls: list[dict]) -> bool:
    """True when, in this agent turn, find_alternative_flights answered with an empty list (and no error)."""
    return any(c["tool"] == "find_alternative_flights" and isinstance(c["result"], dict)
               and "error" not in c["result"] and c["result"].get("flights") == [] for c in tool_calls)


def propose_assistance(booking_id=None, kind="wheelchair", user_confirmed=None, user_quote=None) -> dict:
    """Propose a special assistance request for a flight booking (AT-AST-01). Changes nothing."""
    return _propose("assistance", {"booking_id": booking_id, "kind": kind, "user_confirmed": user_confirmed,
                                   "user_quote": user_quote})


RULES = {"rebook": "AT-FLT-01", "assistance": "AT-AST-01"}
ACTIONS = {"propose_rebooking": "rebook", "propose_assistance": "assistance"}


def proposal(agent: str, tool: str, args: dict) -> dict:
    """The proposal in the Atlas shape, from one of the tools above and its accepted arguments."""
    action = ACTIONS[tool]
    params = {"booking_type": "flight", "booking_id": args["booking_id"]}
    params.update({"new_flight_id": args.get("new_flight_id")} if action == "rebook"
                  else {"kind": args.get("kind", "wheelchair")})
    return {"agent": agent, "action": action, "params": params, "rule_id": RULES[action], "facts_used": {},
            "user_confirmed": args["user_confirmed"], "user_quote": args["user_quote"]}


_YES = {"type": "boolean", "description": "true only if the client already said yes to this"}
FUNCTIONS = {"find_alternative_flights": find_alternative_flights, "propose_rebooking": propose_rebooking,
             "propose_assistance": propose_assistance}
SCHEMAS = {
    "find_alternative_flights": {"type": "function", "function": {
        "name": "find_alternative_flights",
        "description": "Later flights on the same route as a booking (for a cancelled flight). Read only.",
        "parameters": {"type": "object", "properties": {"booking_id": {"type": "integer"}}, "required": ["booking_id"]}}},
    "propose_rebooking": {"type": "function", "function": {
        "name": "propose_rebooking",
        "description": "Propose moving a cancelled flight booking to a later flight (rule AT-FLT-01). Changes nothing.",
        "parameters": {"type": "object", "properties": {
            "booking_id": {"type": "integer"}, "new_flight_id": {"type": "integer"}, "user_confirmed": _YES,
            "user_quote": {"type": "string"}}, "required": ["booking_id", "new_flight_id", "user_confirmed", "user_quote"]}}},
    "propose_assistance": {"type": "function", "function": {
        "name": "propose_assistance",
        "description": "Propose special assistance (a wheelchair) for a flight booking (rule AT-AST-01).",
        "parameters": {"type": "object", "properties": {
            "booking_id": {"type": "integer"}, "kind": {"type": "string", "enum": list(ASSISTANCE_KINDS)},
            "user_confirmed": _YES, "user_quote": {"type": "string"}},
            "required": ["booking_id", "user_confirmed", "user_quote"]}}},
}
