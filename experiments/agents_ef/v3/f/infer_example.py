"""Minimal Agent F inference example: load the SELECTED checkpoint and score 3 dummy support dialogues (EN + FR).

    python v3/f/infer_example.py                      # checkpoint path read from v3/f/checkpoints_manifest.json
    python v3/f/infer_example.py --ckpt <folder> [--int8]
The dialogues below are invented for this demo (no customer data). The score is the predicted satisfaction 1-5
an annotator would give AFTER the dialogue ended. Output is advice only: Agent F never acts.
Caveat: the USS model was trained on English + Chinese dialogues; French is NOT in its training data, so the
French score relies only on the multilingual encoder (NOT VALIDATED on French dialogues).
"""
import argparse
import json
import sys
from pathlib import Path

import torch

H = Path(__file__).resolve().parent
sys.path.insert(0, str(H))
from f_predictor import SatisfactionPredictor  # noqa: E402

DIALOGUES = {
    "EN resolved": "Customer: Hi, my order hasn't arrived yet.\nAgent: Sorry about that. I checked: it was delayed "
                   "at the depot and will arrive tomorrow. I added free shipping on your next order.\n"
                   "Customer: Great, thank you so much for the quick help!\nAgent: You're welcome, have a nice day.",
    "EN unresolved": "Customer: I was charged twice for the same order.\nAgent: Please check your bank statement.\n"
                     "Customer: I already did, it is charged twice. This is the third time I ask.\n"
                     "Agent: I cannot see it on my side.\nCustomer: Unbelievable. Forget it.",
    "FR polite but unresolved": "Customer: Bonjour, le colis est arrivé abîmé.\nAgent: Je suis désolé. Le retour "
                                "n'est pas possible après 14 jours.\nCustomer: D'accord... merci quand même.",
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ckpt", default=None)
    ap.add_argument("--int8", action="store_true", help="dynamic int8 quantized model (smaller, faster on CPU)")
    a = ap.parse_args()
    torch.set_num_threads(2)
    ck = a.ckpt or json.loads((H / "checkpoints_manifest.json").read_text())["selected"]["path"]
    f = SatisfactionPredictor.load(ck, int8=a.int8)
    for (name, text), out in zip(DIALOGUES.items(), f.predict(list(DIALOGUES.values()))):
        print(f"{name:26s} -> satisfaction {out['score']:.2f} ({out['label']})")


if __name__ == "__main__":
    main()
