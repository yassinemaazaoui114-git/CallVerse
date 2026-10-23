"""SIMULATED dataset for Agent F (Quality & Knowledge, model M7): predict customer satisfaction (CSAT 1-5).

Why simulated: CallVerse has NO real satisfaction labels yet (no survey data, no rated conversations). Real
messages exist only as Intake build/test sets without CSAT, so they cannot train or test F. Every row here is
synthetic and tagged "source": "simulated"; results on it are NOT real customer-satisfaction results.

How a row is made:
1. Simulated days (Agent E simulator, seeds NOT used by E's splits) with a mix of heuristic policies; every
   served or abandoned request is logged with the queue state at that moment (same 6 features E observes).
2. Latent satisfaction = SIM-CSAT (wait, fallback) + resolution effect (unresolved -1.5) + customer temperament
   noise; label = round + clip to 1..5. Abandoned requests are 1 (sometimes 2).
3. Text = customer opening (by queue) + agent closing (by resolved / fallback) + optional customer last message
   whose tone follows the label with noise (30% of customers write no last message).
   Template pools are SPLIT by phrasing between train / val / test, so test text uses unseen wordings.

Run: python -m agent_f.make_dataset --out results/agent_f_data   (deterministic: same files every time)
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from baselines.heuristics import BASELINES  # noqa: E402
from env.callcenter_env import N_Q, CallCenterEnv  # noqa: E402

SPLIT_SEEDS = {"train": (50_000, 220), "val": (55_000, 40), "test": (60_000, 60)}   # (first seed, number of days)
SCENARIOS = ["normal", "high", "spike", "drift", "slowdown", "failure"]
ROWS_PER_DAY = 45

OPENINGS = {   # per queue: 12 phrasings -> 8 train, 2 val, 2 test
    0: ["Where is my order {o}?", "Can you track order {o} for me?", "Hi, any news about my parcel {o}?",
        "What's the status of order {o}?", "Has order {o} shipped yet?", "I'd like an update on order {o}.",
        "My package {o} hasn't moved in days, where is it?", "Could you check the delivery of {o}?",
        "When will order {o} arrive?", "Tracking for {o} shows nothing, help?",
        "Is my order {o} on its way?", "Need the delivery date for order {o}."],
    1: ["I want a refund for order {o}.", "Please give me my money back for {o}.", "How do I get reimbursed for {o}?",
        "I was charged twice for order {o}.", "Cancel order {o} and refund me please.",
        "Where is the refund for {o} you promised?", "I need my payment back for order {o}.",
        "The refund for {o} never arrived on my card.", "Can I get money back for order {o}?",
        "I'm owed a refund on {o}.", "Refund status for order {o}?", "Please reimburse order {o} today."],
    2: ["URGENT: my order {o} arrived broken and it's a medical device!", "Emergency, order {o} is leaking!",
        "I need help right now with order {o}, it's dangerous.", "Critical problem with order {o}, please hurry.",
        "The charger from {o} is sparking, what do I do?", "Order {o} was delivered to the wrong person, urgent!",
        "My account was used to place order {o}, I didn't do it!", "Order {o} is overheating, urgent help.",
        "Someone stole package {o} from my door, urgent.", "Fraud on order {o}, please block it now!",
        "Order {o} contains the wrong medicine dosage!", "Help, order {o} has a safety problem!"],
    3: ["Do you have the earbuds from {o} back in stock?", "Is the speaker in order {o} available again?",
        "When will you restock the item from order {o}?", "Can I still buy the watch like in order {o}?",
        "Is there another color for the item in {o}?", "Are the backpacks like {o} available in Sfax?",
        "Will the charger from order {o} come back?", "How many of the item in {o} are left?",
        "Can you reserve the product from {o} for me?", "Any stock of the phone case from order {o}?",
        "Is the product in {o} discontinued?", "Do you sell spare parts for order {o}?"],
}
AGENT_CLOSING = {   # (resolved, fallback) -> phrasings (split 4/1/1)
    (True, False): ["I've checked and resolved this for you.", "This is now sorted, you'll see the update shortly.",
                    "All done, the issue is fixed on our side.", "I've taken care of it, everything is in order.",
                    "Resolved: the details are now updated.", "Good news, this has been handled."],
    (True, True): ["Your request was processed automatically.", "Here is the standard answer for this case.",
                   "Automated update: your request has been completed.", "This was handled by our quick assistant.",
                   "Quick reply: done.", "Processed by the fast lane service."],
    (False, False): ["I'm sorry, I couldn't solve this yet; it is escalated.", "Unfortunately this is still open.",
                     "I can't fix this right now, a colleague will follow up.", "We need more time to resolve this.",
                     "This could not be completed today.", "Sorry, the problem is not solved yet."],
    (False, True): ["Automated reply: please check our help page.", "Standard answer: see the FAQ.",
                    "We could not process this automatically.", "Quick lane could not handle this request.",
                    "Please contact us again later.", "Automatic answer: request not completed."],
}
LAST_MESSAGE = {   # tone level 1..5 -> phrasings (split 6/2/2)
    1: ["This is useless.", "Worst service ever.", "I'm done with this shop.", "Unacceptable, I waited forever.",
        "Terrible, nobody helps.", "I'll never order again.", "What a waste of my time.", "Completely disappointed.",
        "Awful experience.", "You people are hopeless."],
    2: ["Not great.", "That took way too long.", "Still not happy.", "I expected better.", "Meh, disappointing.",
        "Could have been faster.", "Not really solved.", "Pretty frustrating.", "Not impressed.", "So slow."],
    3: ["Okay.", "Fine, I guess.", "Alright.", "Noted.", "It's acceptable.", "Hmm, okay then.", "Sure.",
        "Average service.", "That will do.", "Understood."],
    4: ["Thanks.", "Good, thank you.", "Thanks for the help.", "Nice, appreciated.", "Great, thanks.",
        "That works for me.", "Helpful, thanks.", "Good service.", "Thank you, sorted.", "Cheers, that helps."],
    5: ["Excellent, thank you so much!", "Perfect, super fast!", "Amazing service!", "Wonderful, really helpful!",
        "Brilliant, thanks a lot!", "Fantastic support!", "Best service, thank you!", "Wow, so quick, thanks!",
        "Superb, very happy!", "Outstanding help, thanks!"],
}
RESOLVE_P = np.array([0.92, 0.78, 0.82, 0.9])


def split_pool(pool, split):
    n = len(pool)
    a, b = int(round(n * 4 / 6)), int(round(n * 5 / 6))
    return {"train": pool[:a], "val": pool[a:b], "test": pool[b:]}[split]


def make_split(split: str) -> list[dict]:
    first, n_days = SPLIT_SEEDS[split]
    rng = np.random.default_rng(first + 7)
    policies = [P() for P in BASELINES.values()]
    env = CallCenterEnv(log_tickets=True)
    rows = []
    for d in range(n_days):
        seed, sc = first + d, SCENARIOS[d % len(SCENARIOS)]
        pol = policies[d % len(policies)]
        obs, info = env.reset(seed=seed, scenario=sc)
        done = False
        while not done:
            mask = info["action_mask"]
            a = int(rng.choice(np.flatnonzero(mask))) if rng.random() < 0.15 else pol.act(env, obs, mask)
            obs, _, done, _, info = env.step(a)
        tickets = env.tickets
        for i in rng.choice(len(tickets), size=min(ROWS_PER_DAY, len(tickets)), replace=False):
            tk = tickets[int(i)]
            q, order_id = tk["queue"], int(rng.integers(4500, 5121))
            if tk["abandoned"]:
                resolved, label = False, 1 if rng.random() < 0.85 else 2
                agent = "[the customer left before an answer]"
            else:
                p = RESOLVE_P[q] - (0.15 if tk["fallback"] else 0.0)
                resolved = bool(rng.random() < p)
                latent = tk["csat_sim"] + (0.0 if resolved else -1.5) + rng.normal(0, 0.4)
                label = int(np.clip(np.round(latent), 1, 5))
                agent = str(rng.choice(split_pool(AGENT_CLOSING[(resolved, tk["fallback"])], split)))
            parts = [str(rng.choice(split_pool(OPENINGS[q], split))).format(o=order_id), agent]
            if rng.random() > 0.3:
                tone = int(np.clip(label + rng.choice([-1, 0, 0, 0, 1]), 1, 5))
                parts.append(str(rng.choice(split_pool(LAST_MESSAGE[tone], split))))
            rows.append({"split": split, "source": "simulated", "day_seed": seed, "scenario": sc,
                         "queue": q, "wait_min": round(tk["wait"], 2), "sla_min": float(env.sla[q]),
                         "fallback": tk["fallback"], "abandoned": tk["abandoned"], "resolved": resolved,
                         "state": [round(x, 4) for x in tk["state"]], "text": " || ".join(parts), "csat": label})
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="results/agent_f_data")
    out = Path(ap.parse_args().out)
    out.mkdir(parents=True, exist_ok=True)
    stats = {}
    for split in SPLIT_SEEDS:
        rows = make_split(split)
        with open(out / f"{split}.jsonl", "w") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")
        labels = np.array([r["csat"] for r in rows])
        stats[split] = {"rows": len(rows), "label_counts": {int(k): int((labels == k).sum()) for k in range(1, 6)},
                        "queues": {int(q): int(sum(r["queue"] == q for r in rows)) for q in range(N_Q)}}
    (out / "stats.json").write_text(json.dumps(stats, indent=2))
    print(json.dumps(stats))


if __name__ == "__main__":
    main()
