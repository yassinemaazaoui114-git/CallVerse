# T34 progress — integrate agent F extras, new login, simulator, vision

Branch `feat/t34-integrate` (from main d1c5909). Started 2026-11-02.

| Step | Source | State |
|---|---|---|
| 0 | progress file, NEXT IN PROGRESS | done |
| 1 | `feature/agent-f-rlhf-e2e` | done: docs + results only, code left out (old style names); 1879 pass |
| 2 | `new-login` | done: 3 conflicts solved (both sides kept); suite 1907, vitest 77, build OK |
| 3 | `feature/client-simulator-with-real-data` | folder copied (d3e8073), adapter `scripts/run_client_simulator.py`; needs `requirements-simulator.txt` (onnxruntime, pyspellchecker); 3 runs todo |
| 4 | `claude/magical-albattani-ktcgao` (vision) | merge in progress (conflicts solved, uncommitted). Yassine OK'd swapping .venv torch to the CUDA build (cu130) for the 4-bit check; old list `out/t34_pip_freeze_before.txt`. Photos: `out/t34_photos/` cv001 cv025 cv057 (sha256 = manifest) |
| 5 | regression | todo |
| 6 | docs + report | todo |
