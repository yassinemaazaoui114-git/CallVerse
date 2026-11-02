"""RL5: where the style policy's reward comes from. Every reward is scaled to 0..1 (1 = best) and has a SOURCE label:

    real       the team's star ratings (from_ratings): the only reward that is real learning
    predicted  agent F's predicted satisfaction (from_agent_f)
    synthetic  a made-up world for tests and demos (synthetic): NEVER present it as real learning

Important about agent F (from_agent_f): today's agent F (callverse/quality/satisfaction.py) scores the CLIENT's message
and the delay, not the reply's style (the style-aware model, stacker.pkl, is not promoted). So its reward is the same
for short, warm and warm_next_step: there is nothing for the policy to learn from it. The offline loop checks this
(constant_across_styles) and warns "reward constant across styles -> nothing to learn".
"""

import csv
import json
import random
import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from callverse.learning.style_policy import STYLES, emotion_class

SOURCES = ("predicted", "real", "synthetic")
STARS = (1, 5)   # the sheet's 1..5 stars -> reward (stars - 1) / 4


# --- (a) agent F ----------------------------------------------------------------------------------------------

def from_agent_f(record: dict, evaluate=None) -> float | None:
    """Agent F's reward for one conversation record, in 0..1, or None (agent F cannot judge it).

    record = agent F's conversation record (company, messages, situation, style, decision, reply).
    A FAIL on correctness gives 0. Otherwise the predicted satisfaction 1..5 is scaled to 0..1.
    NOTE: this does not depend on the style today (see the module text)."""
    if evaluate is None:
        from callverse.quality.reward import evaluate_response
        evaluate = evaluate_response
    result = evaluate(record)
    if result["correctness"] == "FAIL":
        return 0.0
    score = result.get("satisfaction")
    if score is None:
        return None
    return round((float(score) - 1.0) / 4.0, 4)


def constant_across_styles(rows: list[dict]) -> bool:
    """True when, for every situation with at least 2 styles rated, all its styles got the same reward.
    rows: {"situation_id", "style", "reward"}. Then the policy has nothing to learn."""
    by_sit: dict[str, dict[str, list[float]]] = {}
    for r in rows:
        if r.get("reward") is None:
            continue
        by_sit.setdefault(str(r["situation_id"]), {}).setdefault(r["style"], []).append(float(r["reward"]))
    compared = 0
    for styles in by_sit.values():
        if len(styles) < 2:
            continue
        compared += 1
        means = [sum(v) / len(v) for v in styles.values()]
        if max(means) - min(means) > 1e-9:
            return False
    return compared > 0


# --- (b) the team's ratings ---------------------------------------------------------------------------------

class RatingSheetError(ValueError):
    """The returned rating file cannot be used (identical tabs, one value everywhere, wrong format)."""


NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
NS_R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
LETTER_COLUMNS = {"A": "F", "B": "H", "C": "J"}   # Stars A / B / C columns of a rater tab (make_rl1_rating_sheet)


def _cell_col(ref: str) -> str:
    return re.match(r"[A-Z]+", ref).group(0)


def read_xlsx(path: str | Path) -> dict[str, list[dict[str, str]]]:
    """{tab name: [ {column letter: text}, ... one per row ]} with the standard library only (no new package).
    Enough for the rating sheet: plain text and numbers, shared strings and inline strings."""
    with zipfile.ZipFile(path) as z:
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", NS):
                shared.append("".join(t.text or "" for t in si.iter(f"{{{NS['m']}}}t")))
        rels = {r.get("Id"): r.get("Target") for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))}
        tabs = {}
        for sheet in ET.fromstring(z.read("xl/workbook.xml")).find("m:sheets", NS):
            target = rels[sheet.get(NS_R)].lstrip("/")
            target = target if target.startswith("xl/") else f"xl/{target}"
            rows = []
            for row in ET.fromstring(z.read(target)).iter(f"{{{NS['m']}}}row"):
                cells = {}
                for c in row.findall("m:c", NS):
                    v, kind = c.find("m:v", NS), c.get("t")
                    if v is not None:
                        cells[_cell_col(c.get("r"))] = shared[int(v.text)] if kind == "s" else (v.text or "")
                    elif (inline := c.find("m:is", NS)) is not None:
                        cells[_cell_col(c.get("r"))] = "".join(t.text or "" for t in inline.iter(f"{{{NS['m']}}}t"))
                rows.append(cells)
            tabs[sheet.get("name")] = rows
    return tabs


def _stars(text) -> float | None:
    try:
        value = float(str(text).strip().replace(",", "."))
    except (TypeError, ValueError):
        return None
    return value if STARS[0] <= value <= STARS[1] else None


def rater_tabs(tabs: dict[str, list[dict]]) -> dict[str, dict[tuple[str, str], float]]:
    """{rater: {(situation_id, letter): stars}} for every tab with a "Stars A" header (the README tab is skipped)."""
    out = {}
    for name, rows in tabs.items():
        header = next((i for i, r in enumerate(rows) if r.get("F", "").strip().lower() == "stars a"), None)
        if header is None:
            continue
        ratings = {}
        for r in rows[header + 1:]:
            sid = (r.get("A") or "").strip()
            if not sid:
                continue
            for letter, col in LETTER_COLUMNS.items():
                stars = _stars(r.get(col))
                if stars is not None:
                    ratings[(sid, letter)] = stars
        out[name] = ratings
    return out


def check_ratings(raters: dict[str, dict]) -> None:
    """Reject a file that cannot teach anything. Raises RatingSheetError with a clear message."""
    filled = {name: r for name, r in raters.items() if r}
    if not filled:
        raise RatingSheetError("no ratings found: no rater tab has stars in the Stars A / B / C columns")
    if len(filled) >= 2 and len({tuple(sorted(r.items())) for r in filled.values()}) == 1:
        raise RatingSheetError(f"all {len(filled)} rater tabs are identical ({', '.join(filled)}): the same tab was "
                               "copied, so these are not independent ratings. Ask each rater to fill their own tab.")
    values = {v for r in filled.values() for v in r.values()}
    if len(values) == 1:
        raise RatingSheetError(f"every rating has the same value ({values.pop():g} stars): nothing to learn from.")


def from_ratings(sheet: str | Path, key: str | Path) -> list[dict]:
    """The returned rating file -> one row per (rater, situation, style): {"rater", "situation_id", "style", "stars",
    "reward"} with reward = (stars - 1) / 4. sheet = the team's .xlsx (or a .csv with the same Stars columns, one
    rater); key = out/rl1_rating_key.json (which letter is which style). A letter shown for 2 styles (identical
    replies) counts for both. Raises RatingSheetError for an unusable file."""
    key_map = json.loads(Path(key).read_text(encoding="utf-8"))
    sheet = Path(sheet)
    if sheet.suffix.lower() == ".csv":
        with sheet.open(encoding="utf-8-sig", newline="") as f:
            rows = list(csv.reader(f))
        letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        tabs = {sheet.stem: [{letters[i]: v for i, v in enumerate(r)} for r in rows]}
    else:
        tabs = read_xlsx(sheet)
    raters = rater_tabs(tabs)
    check_ratings(raters)
    out = []
    for rater, ratings in raters.items():
        for (sid, letter), stars in sorted(ratings.items()):
            for style in key_map.get(sid, {}).get(letter, []):
                if style in STYLES:
                    out.append({"rater": rater, "situation_id": sid, "style": style, "stars": stars,
                                "reward": round((stars - STARS[0]) / (STARS[1] - STARS[0]), 4)})
    if not out:
        raise RatingSheetError("no rating matches the key file: check that the sheet and the key come from the same run")
    return out


# --- (c) synthetic world (tests and demos only) ---------------------------------------------------------------

# Mean reward per (emotion class, style). Made up on purpose: warm is best for angry clients, short for calm ones.
SYNTHETIC_MEANS = {
    "angry": {"short": 0.30, "warm": 0.80, "warm_next_step": 0.65},
    "other": {"short": 0.80, "warm": 0.50, "warm_next_step": 0.60},
}
# A world where every style is equally good: the policy must not break on it.
FLAT_MEANS = {"angry": {s: 0.6 for s in STYLES}, "other": {s: 0.6 for s in STYLES}}


def synthetic_mean(situation: dict, style: str, means: dict | None = None) -> float:
    return (means or SYNTHETIC_MEANS)[emotion_class(situation)][style]


def synthetic(situation: dict, style: str, rng: random.Random, means: dict | None = None) -> float:
    """A SYNTHETIC reward: 1 with probability synthetic_mean, else 0. Label it "synthetic" wherever it is shown."""
    return 1.0 if rng.random() < synthetic_mean(situation, style, means) else 0.0
