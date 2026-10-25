"""Re-score the VALIDATED v2 Agent F checkpoint (e5-small vocab-trimmed, Amazon EN/FR stars) with the v3 metrics
(QWK, exact / within-1 accuracy, per-class, confusion) and measure fp32 vs dynamic-int8 on the same TEST set.
No training, nothing chosen on TEST.

    python v3/f/amazon_rescore.py --ckpt <checkpoints/f_v2_enfr/e5small_trim_ft_s0> \
        --data <data_amazon/subset_enfr> --out v3/f/results/amazon_rescore_e5small_trim_ft.json
"""
import argparse
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import quantize_f  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--ckpt", required=True)
ap.add_argument("--data", required=True)
ap.add_argument("--out", required=True)
a = ap.parse_args()
sha = hashlib.sha256((Path(a.ckpt) / "model.pt").read_bytes()).hexdigest()
print("checkpoint sha256", sha)
quantize_f.main(["--ckpt", a.ckpt, "--data", a.data, "--out", a.out])     # int8 is NOT saved (read-only ckpt)
import json  # noqa: E402
r = json.loads(Path(a.out).read_text())
r["ckpt_sha256"] = sha
r["label"] = "Amazon EN/FR product-review stars (AUXILIARY)"
Path(a.out).write_text(json.dumps(r, indent=1))
