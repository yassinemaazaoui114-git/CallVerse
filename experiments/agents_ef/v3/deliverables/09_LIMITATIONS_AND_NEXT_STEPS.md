# 09 — Limitations and next steps

## Limitations

### Agent E

1. **Simulated world.** Every Agent E number is simulated.
   - From real data: the Intake priority formula and queue discipline (prototype code), and the Olist demand shape, volatility and late-delivery shares.
   - **Invented:** queue mix, service times, patience, the emotion–patience link, SLA tiers, fallback speed and failure rate (20%), and the peak shapes.
   - Only reward-weight sensitivity was run. Sensitivity to the other invented parameters was not.
2. **Sample size below target.** 50 days per family (650) instead of 300 per scenario, because of the CPU budget.
   - Effects below about 4 return points are not resolvable.
   - Ablations have only 3 seeds.
3. **Objective.** Equal weights treat all tickets alike, which lets queue C degrade (−9.5 pp for RL). Queue-specific weights were not explored.
4. **No GPU; one CPU budget.** Larger networks, longer training and hyper-parameter search were not explored beyond the 400k / 128×128 ablations. Guarded policies were not scored on VAL (only their RL part was).
5. **E × F.** Only a synthetic SIM-CSAT term was tested (3 seeds, no measurable effect). The simulator has no text, so a real F score cannot be tested inside it.

### Agent F

6. **No genuine customer ratings of support conversations** were reachable.
   - USS = annotator judgements (α 0.20–0.28 EN, 0.52 ZH).
   - Amazon = product stars.
   - DCH-2 needs a user agreement, which I did not accept.
   - ShopNova has no reviews table.
7. **CPU-budget fine-tuning:** 50% of TRAIN, 3 epochs, 128–256 tokens. The full protocol and GPU numbers are NOT VERIFIED.
8. **Domain transfer fails.** Scores are flat on ShopNova-style conversations (SD 0.04–0.07). French support dialogues are unvalidated (French is validated only on product reviews).

### M7

9. **The corpus is scripted.** The agents' LLM is a fake, because there is no API key here; the prototype pipeline itself is real. The detection results check wiring, not real-world prevalence.
   - All replies were SLM templates (the SLM was offline), so the French-reply finding is NOT VERIFIED with the SLM running.

### Blocked

10. **Blocked:**
    - user's Windows PC and local CallVerse datasets;
    - RTX 4050 measurements;
    - QCRI GPU state (not observable);
    - DCH-2;
    - Kaggle (login).

## Next steps (in order of value)

1. **Get real satisfaction labels for support conversations.**
   - Ask for DCH-2 (user agreement), and add a `reviews` table to the ShopNova platform contract.
   - Then fit `ReviewCalibrator` and re-run the M7 gate. This is the only path to a valid F → E reward.
2. **Decide queue-C priority** in Agent E's objective, then re-tune the rules and re-run the TEST comparison under that objective.
3. **Raise the TEST size to 300 days per family** for the top group only (MPC, Forecast, Erlang-C, guarded DDQN): about 4 h of CPU. This tightens the tie band.
4. **Simulator sensitivity runs** on the invented parameters (patience, service time, fallback failure rate).
5. **Agent F on the RTX 4050:** full-protocol fine-tuning of e5-L6 (256–512 tokens, full TRAIN, 5 epochs).
6. **Wrap TF-IDF+Ridge as an M7 scorer.** Run M7 on real prototype traces once the SLM is running.
7. **Prototype fixes for the owner** (from M7): French template replies; a rule for delivered-late orders after the return window; add review metadata to the rules.
