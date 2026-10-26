#!/bin/sh
# Safe push of the research branch ONLY (user-approved 2026-10-26). Refuses unless every check passes.
#   sh experiments/agents_ef/v5/d/safe_push.sh          (from the repository root)
# Checks: on the right branch; remote is an ancestor (fast-forward, never force); no weights/binaries/.env;
# no file > 2 MB; no secret-like strings in added lines; no USS/Amazon dataset split files.
set -e
BR=research/agents-e-f-tiny-models
[ "$(git rev-parse --abbrev-ref HEAD)" = "$BR" ] || { echo "REFUSED: not on $BR"; exit 1; }
git fetch -q origin "$BR"
R=$(git rev-parse "origin/$BR")
git merge-base --is-ancestor "$R" HEAD || { echo "REFUSED: not a fast-forward"; exit 1; }
N=$(git rev-list --count "$R..HEAD"); [ "$N" -gt 0 ] || { echo "nothing to push"; exit 0; }
BAD=$(git diff --name-only "$R..HEAD" | grep -iE '\.(pt|pth|bin|safetensors|joblib|pkl|pickle|npz|npy|db|sqlite|onnx|h5|parquet|zip|gz|bundle)$|(^|/)\.env|id_rsa|\.pem$' || true)
[ -z "$BAD" ] || { echo "REFUSED: weights/binaries/secrets files:"; echo "$BAD"; exit 1; }
BIG=$(git diff --name-only --diff-filter=AM "$R..HEAD" | while read f; do [ -f "$f" ] && [ "$(stat -c%s "$f")" -gt 2000000 ] && echo "$f"; done || true)
[ -z "$BIG" ] || { echo "REFUSED: files > 2 MB:"; echo "$BIG"; exit 1; }
SEC=$(git diff "$R..HEAD" -U0 -- . ':(exclude)experiments/agents_ef/v5/d/safe_push.sh' | grep '^+' | grep -cE '(gsk_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{30,}|github_pat_|xox[bap]-|AIza[0-9A-Za-z_-]{30,}|hf_[A-Za-z0-9]{30,}|BEGIN [A-Z ]*PRIVATE KEY)' || true)
[ "$SEC" = "0" ] || { echo "REFUSED: $SEC secret-like lines"; exit 1; }
DATA=$(git diff --name-only "$R..HEAD" | grep -iE '(^|/)data_uss/|(^|/)(train|val|test)\.jsonl$' || true)
[ -z "$DATA" ] || { echo "REFUSED: dataset split files:"; echo "$DATA"; exit 1; }
echo "checks OK: $N commits, $R -> $(git rev-parse --short HEAD) (fast-forward)"
git push origin "$BR"
[ "$(git ls-remote origin "refs/heads/$BR" | cut -f1)" = "$(git rev-parse HEAD)" ] && echo "VERIFIED remote = $(git rev-parse --short HEAD)"
