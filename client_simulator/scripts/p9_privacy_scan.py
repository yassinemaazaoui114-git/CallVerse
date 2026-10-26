"""Privacy scan of every file tracked in git + the simulator kit: emails, phone numbers, @handles, first names.
python p9_privacy_scan.py [--fix FILE...]   --fix re-masks the text of data-derived files (csv/json/jsonl/md)
Writes results/p9_privacy_scan.json (counts + up to 5 examples per file and type)."""
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ROOT, _first_names, mask_person_names, save_json  # noqa: E402

EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[a-z]{2,}", re.I)
PHONE = re.compile(r"(?<![\w.<])(\+\d{1,3}[\s.-]?)?\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}(?![\w.])")
HANDLE = re.compile(r"(?<![\w.@<`/])@[A-Za-z_]\w{2,}")
SKIP_HANDLE_IN = (".py",)          # decorators like @pytest.fixture
OK_HANDLES = {"@example", "@anthropic"}
OK_EMAILS = {"noreply@anthropic.com"}


def files():
    tracked = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True).stdout.split("\n")
    kit = [str(p.relative_to(ROOT)).replace("\\", "/") for p in (ROOT / "simulator").rglob("*") if p.is_file()]
    return sorted({f for f in tracked + kit if f and not f.endswith((".png", ".onnx", ".pkl"))})


def scan_text(t, fname):
    hits = {"email": [m for m in EMAIL.findall(t) if m.lower() not in OK_EMAILS and not m.lower().endswith("@example.com")],
            "phone": [m.group(0) for m in PHONE.finditer(t)],
            "handle": [] if fname.endswith(SKIP_HANDLE_IN) else [h for h in HANDLE.findall(t) if h.lower() not in OK_HANDLES],
            "name": []}
    if not fname.endswith(".py"):
        masked = mask_person_names(t)
        if masked != t:  # recover which words were masked
            hits["name"] = [w for w in re.findall(r"\b[A-Z][a-z]{1,15}\b", t) if w in _first_names()["safe"]][:50]
            for m in re.finditer(r"\b(?i:hi|hello|hey|dear|thanks|sorry)[,!.]?\s+([A-Z][a-z]{1,15})", t):
                hits["name"].append(m.group(1))
    return hits


def main():
    out = {}
    for f in files():
        try:
            t = (ROOT / f).read_text(encoding="utf-8")
        except Exception:
            continue
        h = scan_text(t, f)
        h = {k: v for k, v in h.items() if v}
        if h:
            out[f] = {k: {"count": len(v), "examples": sorted(set(v))[:6]} for k, v in h.items()}
    save_json(out, ROOT / "results" / "p9_privacy_scan.json")
    for f, h in out.items():
        print(f, {k: (v["count"], v["examples"][:4]) for k, v in h.items()})


def fix(paths):
    """Re-mask person names in data-derived text files (keeps everything else unchanged)."""
    for p in paths:
        fp = ROOT / p
        t = fp.read_text(encoding="utf-8")
        new = mask_person_names(t)
        if new != t:
            fp.write_text(new, encoding="utf-8")
            print("re-masked", p)


if __name__ == "__main__":
    fix(sys.argv[2:]) if len(sys.argv) > 1 and sys.argv[1] == "--fix" else main()
