"""
A deterministic order-email reader: the rule route.

`order_agent.extract_order` sends the email to a language model. That is one API
call per email, against a free tier of twenty a day, which is why the order agent
has only ever been scored on 50 cases spread over five days -- and why the README's
claim that "every agent runs with `--no-llm` and no API call at all" has never been
true of this one. Reading the email *is* the model's job there.

This module is the other route: the same decision, computed. It exists for three
reasons, in ascending order of importance.

1. **It makes a 200-case evaluation free.** WP-02 asks for n >= 150 per agent with
   confidence intervals. At one call per case that is ten days of quota; here it is
   a second.
2. **It is the baseline the model has to beat.** Every other claim in this project
   is stated against a trivial policy -- the corridor median, "alert on every leg",
   "dispute everything". The order agent has never had one, so "50 of 50" has been
   reported with nothing to compare it against.
3. **It turns the agent's design position into something testable.** D-041 says the
   agents decide with arithmetic and the model only writes the sentence. For order
   entry that was not so. With both routes present, how much the model is actually
   worth on this task becomes a measurement rather than an assumption (WP-07).

What it does not do
-------------------
It does not try to be a language model. It reads the shapes this domain actually
uses -- centre codes, weights, piece counts, service levels -- and **asks whenever
it is unsure**, which is the same policy `order_entry/v1.md` gives the model. Where
it cannot parse something it does not guess; a wrong order filed confidently is the
failure mode both routes are built to avoid.

It will be worse than the model somewhere, and that is the point of running both.
"""

from __future__ import annotations

import re

from src.common import config

# ── the shapes this domain uses ──────────────────────────────────────────────

CENTRE_CODE_RE = re.compile(r"\bIND\d{6}[A-Z]{3}\b")

#: Words that mark the text around them as being about where a load starts or ends.
#: Assignment is by nearest preceding cue rather than by order of appearance: the
#: judge's `prose_reversed` template names the destination first, so "first code is
#: the origin" is wrong on a tenth of the set.
ORIGIN_CUES = (
    "pickup", "pick up", "pick-up", "collect", "collection", "collected",
    "origin", "source", "from", "ex ", "premises", "warehouse", "loading",
    "despatch", "dispatch",
)
DEST_CUES = (
    "delivery", "deliver", "destination", "dest", "to ", "reach", "receiver",
    "consignee", "depot", "unloading", "drop",
)

_NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}

PIECE_NOUNS = (
    "pieces", "piece", "pcs", "packages", "package", "cartons", "carton",
    "crates", "crate", "boxes", "box", "pallets", "pallet", "bags", "bag",
    "units", "unit", "cases", "case",
)

#: Anything that turns a number into an estimate. The prompt's rule 5 says an
#: estimate is ambiguous and must be asked about, so these are detected rather
#: than stripped.
HEDGES = (
    "about", "around", "roughly", "approx", "approximately", "circa", "~",
    "somewhere between", "between", "or so", "give or take", "estimated",
    "est.", "maybe", "upto", "up to", "at least", "no more than", "under",
    "over", "max", "min",
)

_TONNE_RE = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(?:tonnes?|tons?|\bmt\b|\bt\b)(?![a-z])", re.I
)
_KG_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:kgs?|kilograms?|kilos?)\b", re.I)
_RANGE_RE = re.compile(
    r"\b(\d+(?:\.\d+)?)\s*(?:-|–|—|to|and)\s*(\d+(?:\.\d+)?)\s*"
    r"(kgs?|kilograms?|tonnes?|tons?|pieces?|cartons?|boxes?|crates?|pcs)\b",
    re.I,
)


def _num(text: str) -> float:
    return float(text.replace(",", ""))


def _positive_or_vague(value: int) -> tuple[int | None, bool]:
    """A piece count at or below zero is stated-but-unusable, not missing."""
    return (value, False) if value >= 1 else (None, True)


def _in_quoted_block(text: str, pos: int) -> bool:
    """Is this position inside quoted history rather than the live request?

    A mail thread repeats old figures under `>` or beneath a forwarded header,
    and those are superseded rather than contradictory. Without this distinction
    the contradiction check would fire on every reply anyone ever sends.
    """
    line_start = text.rfind("\n", 0, pos) + 1
    if text[line_start:pos].lstrip().startswith(">"):
        return True
    before = text[:pos].lower()
    for marker in ("---------- forwarded", "--- forwarded", "wrote:", "original message"):
        if marker in before:
            return True
    return False


def _counts_consignments(text: str) -> int:
    """How many separate shipments this email appears to be asking for.

    An email listing two loads is not a harder single order, it is two orders,
    and filing either one is a guess about which the customer meant. Detected by
    the enumeration people actually use -- "1)" and "2)" on their own lines, or
    an explicit "two loads/shipments/consignments".
    """
    lowered = text.lower()
    if re.search(r"\b(two|three|both)\s+(loads|shipments|consignments|bookings|orders)\b", lowered):
        return 2
    enumerated = re.findall(r"^\s*([1-9])[).]\s+\S", text, re.M)
    return len({n for n in enumerated}) if len(set(enumerated)) > 1 else 1


# ── field readers ────────────────────────────────────────────────────────────
#
# Each returns (value, ambiguous). `ambiguous` is not the same as `value is None`:
# a field nobody mentioned is missing, a field mentioned as "2 to 3 tonnes" is
# stated and unusable. Both end in a question, but only the second one means the
# customer thinks they have already told us.


def read_weight_kg(text: str) -> tuple[float | None, bool]:
    """Weight in kilograms, converting tonnes, refusing ranges and estimates."""
    lowered = text.lower()

    # A range is stated-but-unusable, whatever unit it is in.
    for m in _RANGE_RE.finditer(text):
        if m.group(3).lower().startswith(("kg", "kilo", "tonne", "ton")):
            return None, True

    # "somewhere between 2 and 3 tonnes" survives the range regex only sometimes,
    # because "and" also joins ordinary clauses. A hedge sitting within a few
    # words of a weight is treated as making it an estimate.
    for hedge in ("somewhere between", "between"):
        idx = lowered.find(hedge)
        if idx != -1:
            window = lowered[idx : idx + 80]
            if _TONNE_RE.search(window) or _KG_RE.search(window):
                return None, True

    candidates: list[tuple[int, float]] = []
    for m in _KG_RE.finditer(text):
        candidates.append((m.start(), _num(m.group(1))))
    for m in _TONNE_RE.finditer(text):
        candidates.append((m.start(), _num(m.group(1)) * 1000))

    if not candidates:
        return None, False

    # A correction ("the weight is X kg, not Y kg") states the right answer first
    # and the superseded one second. Drop anything introduced by "not".
    kept = [
        (pos, value)
        for pos, value in candidates
        if not re.search(r"\bnot\s*$", text[max(0, pos - 12) : pos], re.I)
    ]
    if not kept:
        return None, False

    # Two different weights that nothing in the email reconciles.
    #
    # This is not the same as a correction, where the email says which figure is
    # superseded and a reader can resolve it. Here both are asserted, and picking
    # one -- the first, the larger, the nearest to a keyword -- is the guess the
    # whole policy exists to prevent. The 200-case evaluation caught this filing
    # 10 of 10 contradictions with an invented weight.
    #
    # Quoted history is excluded: a thread where an older figure sits under a "> "
    # is not a contradiction, it is a supersession, and the live request wins.
    distinct = {
        round(value, 1)
        for pos, value in kept
        if not _in_quoted_block(text, pos)
    }
    if len(distinct) > 1:
        return None, True

    # A hedge immediately before the number makes it an estimate.
    pos, value = kept[0]
    before = lowered[max(0, pos - 24) : pos]
    if any(h in before for h in ("about", "around", "roughly", "approx", "circa", "~")):
        return None, True

    if value <= 0:
        return None, True

    return round(value, 3), False


def read_pieces(text: str) -> tuple[int | None, bool]:
    """A whole number of packages, refusing ranges and estimates."""
    lowered = text.lower()

    for m in _RANGE_RE.finditer(text):
        if m.group(3).lower().startswith(("piece", "carton", "box", "crate", "pcs")):
            return None, True

    # "roughly 10-12 boxes" — the hedge and the range both point the same way, but
    # the range regex needs the noun adjacent and the template does not always
    # oblige, so the hedge is checked on its own too.
    if re.search(
        r"(about|around|roughly|approx\w*|~)\s*(\d+)\s*(?:-|–|to)\s*(\d+)", lowered
    ):
        return None, True

    noun_group = "|".join(PIECE_NOUNS)

    # "12 cartons", "No. of packages: 12"
    adjacent = re.search(rf"(\d+)\s*(?:{noun_group})\b", lowered)
    if adjacent:
        pos = adjacent.start()
        before = lowered[max(0, pos - 20) : pos]
        if any(h in before for h in ("about", "around", "roughly", "approx", "~")):
            return None, True
        # "0 cartons" is stated, parseable and impossible. `validate_order`
        # already rejects a count below 1, so filing it here only moves the
        # rejection to a 422 from the TMS three layers away -- the two halves of
        # one agent disagreeing about the same rule.
        return _positive_or_vague(int(adjacent.group(1)))

    trailing = re.search(rf"(?:{noun_group})\D{{0,12}}?(\d+)", lowered)
    if trailing:
        return _positive_or_vague(int(trailing.group(1)))

    # "twelve cartons"
    words = "|".join(_NUMBER_WORDS)
    spelled = re.search(rf"\b({words})(?:-({words}))?\s*(?:{noun_group})\b", lowered)
    if spelled:
        value = _NUMBER_WORDS[spelled.group(1)]
        if spelled.group(2):
            value += _NUMBER_WORDS[spelled.group(2)]
        return value, False

    return None, False


def read_route_type(text: str) -> tuple[str | None, bool]:
    """`FTL` or `Carting`, never inferred from the weight (prompt rule 4)."""
    lowered = text.lower()
    ftl = bool(re.search(r"\bftl\b|full truck", lowered))
    carting = bool(re.search(r"\bcarting\b|part load|part-load", lowered))
    if ftl and carting:
        return None, True
    if ftl:
        return "FTL", False
    if carting:
        return "Carting", False
    return None, False


def read_centres(text: str) -> tuple[str | None, str | None]:
    """(origin, destination) by nearest preceding cue word.

    Codes repeat in a forwarded quote, so the *first* assignment of each end wins:
    a correction mail restates the same pair and the second copy adds nothing.
    """
    lowered = text.lower()
    origin = dest = None

    for m in CENTRE_CODE_RE.finditer(text):
        code = m.group(0)
        window = lowered[max(0, m.start() - 90) : m.start()]

        origin_at = max((window.rfind(c) for c in ORIGIN_CUES), default=-1)
        dest_at = max((window.rfind(c) for c in DEST_CUES), default=-1)

        if origin_at > dest_at and origin is None:
            origin = code
        elif dest_at > origin_at and dest is None:
            dest = code

    # No cue resolved either end: fall back to order of appearance, which is right
    # far more often than not, but only when nothing better was available.
    if origin is None or dest is None:
        codes: list[str] = []
        for m in CENTRE_CODE_RE.finditer(text):
            if m.group(0) not in codes:
                codes.append(m.group(0))
        remaining = [c for c in codes if c not in (origin, dest)]
        if origin is None and remaining:
            origin = remaining.pop(0)
        if dest is None and remaining:
            dest = remaining.pop(0)

    return origin, dest


_ROLE_WORDS = {
    "consignor", "consignee", "shipper", "logistics", "logistics desk",
    "operations", "ops", "supply chain", "dispatch", "despatch",
}


def read_customer_name(text: str) -> str | None:
    """The sending **company**, not the person signing off (prompt rule 6)."""
    lines = [ln.strip() for ln in text.splitlines()]
    for i, line in enumerate(lines):
        if not re.match(r"^(best\s+)?(regards|thanks|thank you|sincerely|cheers)\b[,.]?$", line, re.I):
            continue

        tail = [ln for ln in lines[i + 1 : i + 5] if ln]
        if not tail:
            continue

        # "Logistics desk, Acme Traders" — the company is after the comma.
        for ln in tail:
            m = re.match(r"^[\w\s]*(?:desk|department|team|division)\s*,\s*(.+)$", ln, re.I)
            if m:
                return m.group(1).strip()

        # Otherwise the first line that is not a bare role word is the company,
        # which is how the development corpus signs off.
        for ln in tail:
            if ln.lower().strip(" ,.") not in _ROLE_WORDS:
                return ln.strip(" ,.")

    return None


# ── the decision ─────────────────────────────────────────────────────────────

#: Which gap to ask about when several exist. Prompt rule 2: the thing that blocks
#: the booking hardest, and weight and pieces come before service level. The
#: judge's `missing_two` case depends on this exact ordering.
#
# `consignment` comes first because it dominates every other gap: you cannot
# sensibly ask which weight applies until you know which shipment is being
# booked. It is not a TMS field, which is the point -- the 200-case evaluation
# showed the agent had no way to say "this email is two orders", so it answered
# the question it *could* express and asked about a weight instead.
ASK_ORDER = (
    "consignment", "weight_kg", "pieces", "origin_centre", "dest_centre",
    "route_type", "customer_name",
)

#: The fields that are actually part of an order. `consignment` is in ASK_ORDER
#: for its priority and is deliberately not here -- it is a question about the
#: email, not a column in the TMS.
REQUIRED_ORDER_FIELDS = tuple(f for f in ASK_ORDER if f != "consignment")

QUESTIONS = {
    "consignment": "This mail lists more than one shipment. Which one should we book first, "
                   "or should we raise them as separate orders?",
    "weight_kg": "Could you confirm the total gross weight in kilograms for this consignment?",
    "pieces": "How many pieces should we book for this consignment?",
    "origin_centre": "Which centre code should we collect from? A city can have several.",
    "dest_centre": "Which centre code should we deliver to? A city can have several.",
    "route_type": "Should this move as FTL (full truck) or Carting (part load)?",
    "customer_name": "Which company should we raise this booking against?",
}


def extract_order_rules(subject: str, body: str) -> dict:
    """The same contract `extract_order` returns, computed rather than generated.

    Returns `{"action": "file"|"clarify", "order": {...}, ...}` so the two routes
    are interchangeable everywhere downstream -- the agent, the evaluation and the
    trace log all see one shape.
    """
    text = f"{subject}\n{body}"

    weight, weight_vague = read_weight_kg(text)
    pieces, pieces_vague = read_pieces(text)
    route_type, route_vague = read_route_type(text)
    origin, dest = read_centres(text)
    customer = read_customer_name(text)

    order = {
        "customer_name": customer,
        "origin_centre": origin,
        "dest_centre": dest,
        "route_type": route_type,
        "pieces": pieces,
        "weight_kg": weight,
        "notes": None,
    }

    # A tonne conversion is recorded, because the prompt asks the model to say so
    # and a reader comparing the two routes should see the same note.
    if weight is not None and _TONNE_RE.search(text) and not _KG_RE.search(text):
        order["notes"] = "weight converted from tonnes"

    vague = {
        "weight_kg": weight_vague,
        "pieces": pieces_vague,
        "route_type": route_vague,
    }
    # Only the real order fields are checked for presence here. `consignment` is
    # in ASK_ORDER for its priority, not because it is a field -- including it in
    # this loop made `order.get("consignment")` None on every email, so every one
    # of the 200 cases reported it missing and the score fell from 95% to 5%.
    missing = [
        name
        for name in ASK_ORDER
        if name in order and (order.get(name) in (None, "") or vague.get(name, False))
    ]

    # The same self-consistency checks `validate_order` applies, hoisted so the
    # rule route asks rather than files something the TMS would reject anyway.
    if origin and dest and origin == dest:
        missing.append("dest_centre")
    # Two shipments in one mail: the fields parse, but they are not one order.
    if _counts_consignments(text) > 1:
        missing.append("consignment")
    if route_type is not None and route_type not in config.ROUTE_TYPES:
        order["route_type"] = None
        missing.append("route_type")

    if missing:
        first = next(name for name in ASK_ORDER if name in missing)
        return {
            "action": "clarify",
            "missing_field": first,
            "question": QUESTIONS[first],
            "order": {k: v for k, v in order.items() if v is not None},
        }

    return {"action": "file", "order": order}
