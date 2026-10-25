# Source me: environment used for every Agent F v4 run (CPU, offline HF cache, <= 2 threads).
export PY=/tmp/claude-0/-home-user-CallVerse/1a5e3645-531b-5493-9c5e-b45226413d98/scratchpad/venv/bin/python
export FV3=/tmp/claude-0/-home-user/1a5e3645-531b-5493-9c5e-b45226413d98/scratchpad/f_v3
export M7C=/tmp/claude-0/-home-user/1a5e3645-531b-5493-9c5e-b45226413d98/scratchpad/m7_corpus
export HF_HOME=/tmp/claude-0/-home-user-CallVerse/1a5e3645-531b-5493-9c5e-b45226413d98/scratchpad/models/hf
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false
export OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 MKL_NUM_THREADS=2
