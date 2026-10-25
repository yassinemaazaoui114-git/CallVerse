# Agent E v4 — lab notebook (Worker E, overnight session 2026-10-25/26)

Rules I follow: V3 is frozen (read-only). V3 TEST (seeds 900000+) was already inspected → never used for tuning or as
the new final test; reading its rows for *descriptive* diagnosis is labelled "V3-TEST (descriptive)". Selection and
refinement use V3 VAL (diagnosis) and the NEW DEV manifest. The NEW TEST4 manifest is evaluated once, after
pre-registration. Every number below comes from a file under v4/e/results/ (or the cited v3 file).

## 0. Setup (23:05)
- DEV manifest: `configs/dev_manifest.json`, seeds 700000 + 1000*family_index + i, 13 families x 8 days = 104 days,
  SHA256 d54493d254ce10b3526d8ffbb4527b382c8d9040a88a671a627ec16d190d639c.
  Note: DEV contains the 5 held-out families. They stay UNSEEN IN TRAINING (training only draws TRAIN families), but
  they are visible to DEV selection. Declared here, before any DEV result.
- Sanity: EnvV4 (bookkeeping wrapper) reproduces V3 exactly: MPC k=0.5 on the first 4 VAL days -126.055 in v4 vs
  -126.055 in v3/e/results/eval_val/rule__mpc__0.5.csv.

## Pre-declared DEV design target (written BEFORE any DEV result)
- A new candidate is "safe enough" on DEV if: queue-C SLA >= MPC(k=0.5) queue-C SLA - 1.0 pp, HIGH SLA >= MPC HIGH
  SLA - 0.2 pp, 0 HIGH tickets on fallback, 0 invalid proposals reaching execution, budget always respected.
- Among safe candidates, rank by DEV equal-weight return (the unchanged v3 reward).
- The confirmatory margin on TEST4 is wider (declared in the pre-registration), because DEV is small.
