"""Choose the reason threshold by leave-one-out on the EXAMPLES (never on the test set).

Usage:
    python -m scripts.choose_threshold

Prints, for each threshold, how many examples get their own reason (exact), a wrong reason (wrong),
or no reason at all (needs_llm -> would cost an M2 call).

Rule used to pick: the highest (exact - wrong). Lowering the threshold turns some "needs_llm" into
answers, some right and some wrong. A wrong reason sends the client to the wrong agent, so it counts
as much against as a right one counts for; a "needs_llm" only costs an M2 call.
On a tie: the fewest wrong. Copy the chosen value into config.yaml (intake.reason_threshold).
"""

import numpy as np

from callverse.intake.reasons import leave_one_out


def main() -> None:
    thresholds = [float(t) for t in np.arange(0.55, 0.851, 0.01)]
    results = leave_one_out(thresholds)

    print(f"{'threshold':>9} {'exact':>6} {'wrong':>6} {'needs_llm':>9} {'exact-wrong':>12}")
    for r in results:
        print(f"{r['threshold']:>9.2f} {r['exact']:>6} {r['wrong']:>6} {r['needs_llm']:>9} "
              f"{r['exact'] - r['wrong']:>12}")

    best = max(results, key=lambda r: (r["exact"] - r["wrong"], -r["wrong"]))
    print(f"\nChosen threshold: {best['threshold']:.2f} -> exact {best['exact']}/{best['total']}, "
          f"wrong {best['wrong']}, needs_llm {best['needs_llm']}")


if __name__ == "__main__":
    main()
