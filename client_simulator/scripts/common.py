"""Shared helpers: paths, anonymisation, the team metric set, plot style."""
import json
import re
from pathlib import Path

import numpy as np
from scipy.stats import spearmanr, wasserstein_distance
from sklearn.metrics import cohen_kappa_score, f1_score

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
PROC = ROOT / "data" / "processed"
CACHE = ROOT / "data" / "cache"
RESULTS = ROOT / "results"
FIG = ROOT / "reports" / "figures"
SIM_DIR = ROOT / "simulator"
for p in (PROC, CACHE, RESULTS, FIG):
    p.mkdir(parents=True, exist_ok=True)

SEED = 42
SCORES = [1, 2, 3, 4, 5]

# ---------------------------------------------------------------- anonymise
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_URL = re.compile(r"(https?://\S+|www\.\S+|\b\S+\.(com|net|org|in|co)/\S*)", re.I)
_HANDLE = re.compile(r"@\w+")
_PHONE = re.compile(r"(\+?\d[\d\s().-]{7,}\d)")
_LONGID = re.compile(r"\b(?=[A-Za-z0-9-]*\d)[A-Za-z0-9-]{6,}\b")


def anonymise(text, names=()):
    """Replace emails, URLs, @handles, phone numbers, long IDs and known names."""
    if not isinstance(text, str):
        return text
    t = _EMAIL.sub("<EMAIL>", text)
    t = _URL.sub("<URL>", t)
    t = _HANDLE.sub("<HANDLE>", t)
    t = _PHONE.sub("<PHONE>", t)
    t = _LONGID.sub("<ID>", t)
    if names:
        t = names_regex(names).sub("<NAME>", t)
    return mask_person_names(t)


# ---------------------------------------------------------------- person names (B16)
_GREET = re.compile(r"\b((?i:hi|hello|hey|dear|thanks|thank you|thx|sorry|welcome|morning|afternoon|evening|hiya|cheers|ok|okay|"
                    r"apologies|congrats|congratulations|happy to help|glad to help))([,!.]?\s+)([A-Z][a-z]{1,15})\b")
_TRAIL = re.compile(r"([,]\s*)([A-Z][a-z]{1,15})(\s*[!.?]|\s*$|\s*<)")
_NOT_NAMES = {"there", "team", "all", "everyone", "again", "so", "for", "and", "but", "you", "we", "guys", "folks", "sir", "madam",
              "the", "this", "that", "a", "for", "much", "very", "too", "in", "on", "please", "now", "though", "anyway", "friend",
              "bro", "mate", "lol", "yes", "no", "not", "just", "again", "today", "tomorrow", "everybody", "both", "y", "u",
              "dev", "test", "max", "min", "alexa", "siri", "echo"}
_FIRST = None


def _first_names():
    global _FIRST
    if _FIRST is None:
        import importlib
        names = set()
        for loc in ("en_US", "en_GB", "en_CA", "en_AU", "en_IN", "en_IE", "en_NZ", "en_PH"):
            try:
                p = importlib.import_module(f"faker.providers.person.{loc}").Provider
                names |= set(getattr(p, "first_names", ())) | set(getattr(p, "first_names_male", ())) | set(getattr(p, "first_names_female", ()))
            except Exception:
                pass
        try:
            from spellchecker import SpellChecker
            words = SpellChecker()
        except Exception:
            words = None
        _FIRST = {"all": {n for n in names if len(n) > 2},
                  # names that are not ordinary English words are masked anywhere they appear capitalised
                  "safe": {n for n in names if len(n) > 2 and n.lower() not in _NOT_NAMES and (words is None or n.lower() not in words)}}
    return _FIRST


def _greet_name(w, fn):
    """After a greeting, mask a capitalised word if it is a known first name, or if it is not an English word."""
    if w.lower() in _NOT_NAMES:
        return False
    if w in fn["all"]:
        return True
    try:
        from spellchecker import SpellChecker
        global _SC
        _SC = _SC if "_SC" in globals() else SpellChecker()
        return w.lower() not in _SC
    except Exception:
        return True


def mask_person_names(t):
    """Mask first names: after greetings ('Hi Sarah', 'Thanks, Mike'), at a clause end ('Sorry about that, Sarah!'),
    and any capitalised first name from the Faker name lists that is not also an English word."""
    if not isinstance(t, str) or not t:
        return t
    fn = _first_names()
    t = _GREET.sub(lambda m: m.group(1) + m.group(2) + ("<NAME>" if _greet_name(m.group(3), fn) else m.group(3)), t)
    t = _TRAIL.sub(lambda m: m.group(1) + ("<NAME>" if m.group(2) in fn["all"] else m.group(2)) + m.group(3), t)
    return re.sub(r"\b[A-Z][a-z]{2,15}\b", lambda m: "<NAME>" if m.group(0) in fn["safe"] else m.group(0), t)


_NAME_RX = {}


def names_regex(names):
    key = frozenset(names)
    if key not in _NAME_RX:
        alts = sorted((re.escape(n) for n in names if n and len(n) > 2), key=len, reverse=True)
        _NAME_RX[key] = re.compile(r"\b(" + "|".join(alts) + r")\b", re.I)
    return _NAME_RX[key]


# ---------------------------------------------------------------- metrics
def score_metrics(y_true, y_pred):
    """The team metric set, identical for baselines and LLM runs."""
    yt = np.asarray(y_true, dtype=int)
    yp = np.asarray(y_pred, dtype=int)
    if len(yt) == 0:
        return {}
    sp = spearmanr(yt, yp).correlation if len(set(yp)) > 1 and len(set(yt)) > 1 else float("nan")
    return {
        "n": int(len(yt)),
        "mae": float(np.mean(np.abs(yt - yp))),
        "spearman": None if np.isnan(sp) else float(sp),
        "exact_acc": float(np.mean(yt == yp)),
        "within1_acc": float(np.mean(np.abs(yt - yp) <= 1)),
        "qwk": float(cohen_kappa_score(yt, yp, weights="quadratic", labels=SCORES)),
        "macro_f1": float(f1_score(yt, yp, average="macro", labels=SCORES, zero_division=0)),
        "wasserstein": float(wasserstein_distance(yt, yp)),
        "pred_dist": {s: int((yp == s).sum()) for s in SCORES},
        "true_dist": {s: int((yt == s).sum()) for s in SCORES},
    }


def save_json(obj, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def read_jsonl(path):
    path = Path(path)
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").split("\n") if l.strip()]  # not splitlines(): text may hold U+2028


def write_jsonl(rows, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")


# ---------------------------------------------------------------- plotting
# Reference palette (dataviz skill): slot 1 blue = real data, slot 2 orange = simulated.
REAL = "#2a78d6"
SIM = "#eb6834"
CAL = "#1baf7a"  # slot 3 aqua = simulated after calibration
INK = "#0b0b0b"
INK2 = "#52514e"
SURFACE = "#fcfcfb"


def plot_style():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({
        "figure.facecolor": SURFACE, "axes.facecolor": SURFACE,
        "axes.edgecolor": "#c9c8c3", "axes.labelcolor": INK2, "text.color": INK,
        "xtick.color": INK2, "ytick.color": INK2, "axes.grid": True, "grid.color": "#e7e6e2",
        "grid.linewidth": 0.6, "axes.axisbelow": True, "axes.spines.top": False,
        "axes.spines.right": False, "font.size": 10, "axes.titlesize": 11,
        "axes.titleweight": "bold", "figure.dpi": 120,
    })
    return plt
