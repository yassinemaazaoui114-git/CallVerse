"""Build ShopNova's Intake benchmark set from ABCD (task T23, step 1).

ABCD = Action-Based Conversations Dataset (ASAPP, NAACL 2021, MIT licence): ~10,000 real-looking customer-service
chats for an online clothing shop, each labelled with the customer's problem ("subflow", e.g. refund_initiate).
benchmarks/m3/data/abcd_mapping.json (written by the Brain) says which subflows mean which ShopNova reason.

For every chat of a split we keep ONE message: the first customer turn with at least 4 words (a "hi" is skipped;
a chat with no such turn is dropped). Its label = the ShopNova reason of the chat's subflow; every subflow not in
the mapping is "other", and "other" is sampled down to 150 messages (seed 2026), so it does not swamp the 5 real
reasons.

    python -m benchmarks.m3.build_data                 # ABCD "dev"  -> benchmarks/m3/data/shopnova_intake_val.json
    python -m benchmarks.m3.build_data --locked-test   # ABCD "test" -> out/t23/shopnova_intake_test.json (git-ignored)

The locked test file is built ONLY in step 7, once, for the chosen model (never used for choosing).
"""

import argparse
import json
import random
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ABCD_PATH = ROOT / "data" / "raw" / "abcd" / "abcd_v1.1.json"
MAPPING_PATH = ROOT / "benchmarks" / "m3" / "data" / "abcd_mapping.json"
VAL_PATH = ROOT / "benchmarks" / "m3" / "data" / "shopnova_intake_val.json"
TEST_PATH = ROOT / "out" / "t23" / "shopnova_intake_test.json"     # out/ is git-ignored

MIN_WORDS = 4


def subflow_to_reason(mapping: dict) -> dict[str, str]:
    """{subflow: reason} from the mapping file (keys starting with "_" and the settings are skipped)."""
    table = {}
    for reason, subflows in mapping.items():
        if isinstance(subflows, list):
            for subflow in subflows:
                table[subflow] = reason
    return table


def first_message(chat: dict) -> str | None:
    """The first customer turn with at least MIN_WORDS words, or None (the chat is then dropped)."""
    for speaker, text in chat["original"]:
        if speaker == "customer" and len(text.split()) >= MIN_WORDS:
            return text.strip()
    return None


def build(chats: list[dict], mapping: dict) -> list[dict]:
    """One labelled message per chat; "other" sampled down to the cap with the mapping's seed."""
    table = subflow_to_reason(mapping)
    rows = []
    for chat in chats:
        text = first_message(chat)
        if text is None:
            continue
        subflow = chat["scenario"]["subflow"]
        rows.append({"id": f"abcd-{chat['convo_id']}", "text": text,
                     "reason": table.get(subflow, "other"), "subflow": subflow})

    others = [r for r in rows if r["reason"] == "other"]
    cap = mapping["other_cap_per_split"]
    if len(others) > cap:
        keep = {r["id"] for r in random.Random(mapping["seed"]).sample(others, cap)}
        rows = [r for r in rows if r["reason"] != "other" or r["id"] in keep]
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--locked-test", action="store_true", help="build the LOCKED test file (step 7 only)")
    args = parser.parse_args()

    split, out_path = ("test", TEST_PATH) if args.locked_test else ("dev", VAL_PATH)
    mapping = json.loads(MAPPING_PATH.read_text(encoding="utf-8"))
    chats = json.loads(ABCD_PATH.read_text(encoding="utf-8"))[split]
    rows = build(chats, mapping)

    note = (f"ShopNova Intake {'LOCKED TEST' if args.locked_test else 'VALIDATION'} set, built by "
            f"benchmarks/m3/build_data.py from ABCD '{split}' (ASAPP, NAACL 2021, MIT licence) with "
            f"benchmarks/m3/data/abcd_mapping.json: first customer turn with >= {MIN_WORDS} words, "
            f"'other' sampled to {mapping['other_cap_per_split']} (seed {mapping['seed']}).")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({"_note": note, "messages": rows}, indent=1, ensure_ascii=False) + "\n",
                        encoding="utf-8")

    print(f"ABCD {split}: {len(chats)} chats -> {len(rows)} messages -> {out_path.relative_to(ROOT)}")
    if not args.locked_test:                 # the locked test's counts are printed in step 7 only
        for reason, n in sorted(Counter(r["reason"] for r in rows).items()):
            print(f"  {reason:15s} {n}")


if __name__ == "__main__":
    main()
