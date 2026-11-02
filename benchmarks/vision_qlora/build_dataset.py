"""Build the CallVerse vision dataset (150 real photos) from its public sources.

Why a builder and not a zip in git? The repository is public and some sources do not allow redistribution
(see DATASET_PROVENANCE.md). So git keeps only the MANIFEST (where each photo comes from + its sha256 + the
labels), and this script downloads the photos again from the pinned source revisions. The same code runs on a
PC and inside the Kaggle notebook.

Steps (each one is a check from the task):
  1. download each source once (pinned revision) into a cache folder
  2. take the exact photo, check its sha256 against the manifest (integrity: same bytes as reviewed)
  3. normalise it: EXIF rotation, RGB, longest side <= 1024 px, JPEG quality 92
  4. quality checks: decodable, size, blur, brightness -> doubtful photos go to the review queue
  5. exact duplicates (sha256) and near duplicates (64-bit difference hash) -> merged into one group
  6. label checks (allowed values, damage flag consistent with the issue type, reason allowed for the company)
  7. stratified GROUP split 70/15/15 (seed 42): photos of the same suitcase / box / hotel / room stay together
  8. write dataset.jsonl, dataset_summary.json, review_queue.csv

Usage:  python build_dataset.py --manifest manifest.jsonl --out callverse_vision_dataset [--cache cache]
Only standard library + Pillow + numpy (+ pyarrow for the two parquet sources).
"""
import argparse, collections, csv, hashlib, io, json, os, random, sys, urllib.request, zipfile

from PIL import Image, ImageOps

# Visual evidence classes (what can be SEEN). Customer intent is NOT a visual class.
DAMAGE_TYPES = ["cracked_screen", "screen_display_defect", "damaged_packaging", "damaged_luggage",
                "dirty_or_messy_room", "damaged_room_fixture"]
ISSUE_TYPES = DAMAGE_TYPES + ["no_visible_issue", "unclear"]
CONFIDENCE = ["high", "medium", "low"]
# Contact reasons per company (verified on main, config.yaml companies: on 2026-11-01).
REASONS = {
    "shopnova": ["order_status", "late_delivery", "refund_request", "cancel_order", "return_item", "damaged_item", "other"],
    "atlas": ["booking_status", "delay_disruption", "cancellation", "refund_request", "compensation_request",
              "rebooking", "special_assistance", "other"],
}
MAX_SIDE = 1024
SEED = 42
SPLIT_SHARES = {"test": 0.15, "val": 0.15}   # the rest is train (~70 %)


def target_for(row):
    """The structured answer the model must learn. Every field is visible in the photo (or says it is not)."""
    issue = row["issue_type"]
    visible = True if issue in DAMAGE_TYPES else (False if issue == "no_visible_issue" else None)
    return {
        "visible_damage": visible,                 # None = the photo does not allow a decision
        "object": row["object"],
        "issue_type": issue,
        "description": row["description"],
        "confidence_level": row["confidence_level"],
        # A human (or the Coordinator's rules) must look at any damage claim or any doubtful photo.
        "requires_review": visible is not False or row["confidence_level"] != "high",
    }


# ---------- 1. download sources ----------
def _get(url, dest):
    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        return dest
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    tmp = dest + ".part"
    req = urllib.request.Request(url, headers={"User-Agent": "callverse-dataset-builder"})
    with urllib.request.urlopen(req, timeout=600) as r, open(tmp, "wb") as f:
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
    os.replace(tmp, dest)
    return dest


def hf_url(repo, rev, path):
    return f"https://huggingface.co/datasets/{repo}/resolve/{rev}/{urllib.request.quote(path)}"


class Sources:
    """Gives the original bytes of one manifest row, downloading (and caching) what is needed."""

    def __init__(self, cache):
        self.cache = cache
        self._parquet = {}
        self._zip = {}

    def _cached(self, *parts):
        return os.path.join(self.cache, *[p.replace("/", "__") for p in parts])

    def raw_bytes(self, row):
        kind, repo, rev, ref = row["source_kind"], row["source_repo"], row["source_revision"], row["source_ref"]
        if kind == "hf":
            return open(_get(hf_url(repo, rev, ref["path"]), self._cached(repo, rev, ref["path"])), "rb").read()
        if kind == "github":
            url = f"https://raw.githubusercontent.com/{repo}/{rev}/{urllib.request.quote(ref['path'])}"
            return open(_get(url, self._cached(repo, rev, ref["path"])), "rb").read()
        if kind == "hf_parquet":
            import pyarrow.parquet as pq
            key = (repo, ref["parquet"])
            if key not in self._parquet:
                local = _get(hf_url(repo, rev, ref["parquet"]), self._cached(repo, rev, ref["parquet"]))
                self._parquet[key] = pq.ParquetFile(local)
            pf = self._parquet[key]
            if "row" in ref:
                # read only the row group that holds this row (the files are ~500 MB)
                start = 0
                for g in range(pf.num_row_groups):
                    n = pf.metadata.row_group(g).num_rows
                    if ref["row"] < start + n:
                        col = pf.read_row_group(g, columns=["image"]).column("image")
                        return col[ref["row"] - start].as_py()["bytes"]
                    start += n
                raise KeyError(f"row {ref['row']} not in {ref['parquet']}")
            cache_key = key + (ref["key_column"],)
            if cache_key not in self._parquet:
                t = pf.read(columns=[ref["key_column"]]).column(0).to_pylist()
                self._parquet[cache_key] = {k: i for i, k in enumerate(t)}
            i = self._parquet[cache_key][ref["key"]]
            return pf.read(columns=["image"]).column("image")[i].as_py()["bytes"]
        if kind == "hf_zip":
            key = (repo, ref["zip"])
            if key not in self._zip:
                local = _get(hf_url(repo, rev, ref["zip"]), self._cached(repo, rev, ref["zip"]))
                self._zip[key] = zipfile.ZipFile(local)
            return self._zip[key].read(ref["member"])
        raise ValueError(f"unknown source kind {kind}")


# ---------- 3-5. image checks ----------
def normalise(raw):
    with Image.open(io.BytesIO(raw)) as im:
        im.load()
        im = ImageOps.exif_transpose(im).convert("RGB")
    im.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=92)
    return im, buf.getvalue()


def quality(im):
    """Return (blur score, brightness 0-255). Blur = variance of a Laplacian on a 256-px grey copy."""
    import numpy as np
    g = im.convert("L").copy()
    g.thumbnail((256, 256))
    a = np.asarray(g, dtype=np.float32)
    lap = a[1:-1, :-2] + a[1:-1, 2:] + a[:-2, 1:-1] + a[2:, 1:-1] - 4 * a[1:-1, 1:-1]
    return float(lap.var()), float(a.mean())


def dhash(im, size=8):
    """64-bit difference hash: tiny grey image, compare each pixel with its right neighbour."""
    g = im.convert("L").resize((size + 1, size), Image.LANCZOS)
    px = list(g.getdata())
    bits = 0
    for y in range(size):
        for x in range(size):
            bits = (bits << 1) | (px[y * (size + 1) + x] > px[y * (size + 1) + x + 1])
    return bits


def hamming(a, b):
    return bin(a ^ b).count("1")


# ---------- 6. labels ----------
def check_labels(rows):
    problems = []
    for r in rows:
        if r["issue_type"] not in ISSUE_TYPES:
            problems.append((r["id"], f"unknown issue_type {r['issue_type']}"))
        if r["confidence_level"] not in CONFIDENCE:
            problems.append((r["id"], f"unknown confidence {r['confidence_level']}"))
        if r["issue_type"] == "unclear" and r["confidence_level"] != "low":
            problems.append((r["id"], "unclear photos must have low confidence"))
        if r["company_reason"] is not None and r["company_reason"] not in REASONS[r["domain"]]:
            problems.append((r["id"], f"reason {r['company_reason']} not allowed for {r['domain']}"))
        if (r["company_reason"] is None) != (r["customer_message"] is None):
            problems.append((r["id"], "reason and message must both be set or both be empty"))
        if not r["description"].strip() or not r["object"].strip():
            problems.append((r["id"], "empty description or object"))
    return problems


# ---------- 7. split ----------
def group_split(rows, seed=SEED):
    """Stratified group split. Groups are visited class by class (rarest class first) and placed in test,
    then val, until each split holds its share of that class; the rest goes to train. Deterministic."""
    groups = collections.defaultdict(list)
    for r in rows:
        groups[r["group"]].append(r)
    cls_total = collections.Counter(r["issue_type"] for r in rows)
    have = {s: collections.Counter() for s in ("test", "val", "train")}
    assigned = {}
    rng = random.Random(seed)
    for cls in sorted(cls_total, key=lambda c: (cls_total[c], c)):
        gids = sorted({r["group"] for r in rows if r["issue_type"] == cls} - set(assigned))
        rng.shuffle(gids)
        for g in gids:
            n_cls = sum(r["issue_type"] == cls for r in groups[g])
            for s in ("test", "val"):
                want = max(1, round(cls_total[cls] * SPLIT_SHARES[s]))
                if have[s][cls] + n_cls <= want or (have[s][cls] == 0 and cls_total[cls] >= 3):
                    break
            else:
                s = "train"
            assigned[g] = s
            for r in groups[g]:
                have[s][r["issue_type"]] += 1
    for r in rows:
        r["split"] = assigned[r["group"]]
    return have


def build(manifest, out, cache, log=print):
    rows = [json.loads(l) for l in open(manifest, encoding="utf-8") if l.strip()]
    os.makedirs(os.path.join(out, "images"), exist_ok=True)
    src = Sources(cache)
    review, hashes = [], {}
    for i, r in enumerate(rows, 1):
        raw = src.raw_bytes(r)
        got = hashlib.sha256(raw).hexdigest()
        if got != r["sha256_source"]:
            raise RuntimeError(f"{r['id']}: source bytes changed (sha256 {got[:12]} != {r['sha256_source'][:12]})")
        im, jpg = normalise(raw)
        r["image"] = f"images/{r['id']}.jpg"
        with open(os.path.join(out, r["image"]), "wb") as f:
            f.write(jpg)
        blur, bright = quality(im)
        r["_q"] = dict(width=im.width, height=im.height, blur=round(blur, 1), brightness=round(bright, 1))
        if min(im.size) < 256:
            review.append((r["id"], "short side under 256 px"))
        if blur < 60:
            review.append((r["id"], f"low sharpness (blur score {blur:.0f})"))
        if bright < 45 or bright > 235:
            review.append((r["id"], f"very dark or very bright (mean {bright:.0f})"))
        if r["confidence_level"] == "low":
            review.append((r["id"], "label is 'unclear' / low confidence by design"))
        r["_dh"] = dhash(im)
        h = hashlib.sha256(jpg).hexdigest()
        if h in hashes:
            raise RuntimeError(f"exact duplicate: {r['id']} == {hashes[h]}")
        hashes[h] = r["id"]
        if i % 25 == 0:
            log(f"  {i}/{len(rows)} photos ready")
    # near duplicates -> same group (union-find), so they can never sit on both sides of a split
    parent = {r["group"]: r["group"] for r in rows}

    def find(g):
        while parent[g] != g:
            parent[g] = parent[parent[g]]
            g = parent[g]
        return g

    near = []
    for a in range(len(rows)):
        for b in range(a + 1, len(rows)):
            d = hamming(rows[a]["_dh"], rows[b]["_dh"])
            if d <= 6:
                near.append((rows[a]["id"], rows[b]["id"], d))
                parent[find(rows[a]["group"])] = find(rows[b]["group"])
    for r in rows:
        r["group"] = find(r["group"])
    for a, b, d in near:
        review.append((a, f"near duplicate of {b} (dHash distance {d}); kept in the same group"))
    problems = check_labels(rows)
    if problems:
        raise RuntimeError(f"label problems: {problems}")
    have = group_split(rows)
    # leakage check: no group in two splits
    seen = collections.defaultdict(set)
    for r in rows:
        seen[r["group"]].add(r["split"])
    leaks = [g for g, s in seen.items() if len(s) > 1]
    if leaks:
        raise RuntimeError(f"leakage: groups in several splits: {leaks}")
    with open(os.path.join(out, "dataset.jsonl"), "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps({"id": r["id"], "image": r["image"], "domain": r["domain"],
                                "customer_message": r["customer_message"], "company_reason": r["company_reason"],
                                "group": r["group"], "split": r["split"], "target": target_for(r)},
                               ensure_ascii=False) + "\n")
    with open(os.path.join(out, "review_queue.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "reason"])
        w.writerows(review)
    summary = {
        "images": len(rows),
        "real_photos": len(rows), "synthetic_images": 0,
        "by_split": dict(collections.Counter(r["split"] for r in rows)),
        "by_issue_type": dict(collections.Counter(r["issue_type"] for r in rows)),
        "by_issue_type_and_split": {s: dict(c) for s, c in have.items()},
        "by_domain": dict(collections.Counter(r["domain"] for r in rows)),
        "by_source": dict(collections.Counter(r["source"] for r in rows)),
        "by_company_reason": dict(collections.Counter(f"{r['domain']}:{r['company_reason'] or 'IMAGE_ONLY'}" for r in rows)),
        "groups": len({r["group"] for r in rows}),
        "near_duplicate_pairs": len(near),
        "review_queue_rows": len(review),
        "label_problems": 0, "leaking_groups": 0,
        "image_size": {"min_short_side": min(min(r["_q"]["width"], r["_q"]["height"]) for r in rows),
                       "max_long_side": max(max(r["_q"]["width"], r["_q"]["height"]) for r in rows)},
        "seed": SEED, "split_shares": {"train": 0.70, **SPLIT_SHARES},
    }
    json.dump(summary, open(os.path.join(out, "dataset_summary.json"), "w"), indent=1)
    return summary


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    here = os.path.dirname(os.path.abspath(__file__))
    ap.add_argument("--manifest", default=os.path.join(here, "manifest.jsonl"))
    ap.add_argument("--out", default="callverse_vision_dataset")
    ap.add_argument("--cache", default="vision_source_cache")
    a = ap.parse_args()
    s = build(a.manifest, a.out, a.cache)
    print(json.dumps(s, indent=1))
