# Client Simulator (M1) with real data

The Client Simulator plays ShopNova (and Atlas) customers so the CallVerse agents can be tested without real
clients. It writes the customer's messages turn by turn and, at the end of a conversation, gives a 1-5
satisfaction score with a one-line comment. Every design choice was tested against **real** customer data:
real customer messages (D5) and real satisfaction scores (D6).

This folder is self-contained (its own code, scripts, tests and requirements). It does not change anything in
`callverse/`; plugging it into the pipeline (`callverse/simulator/`) is a separate step.

## Final setup

| Part | What | Where it runs |
|---|---|---|
| Writer (plays the customer) | `gemma3:1b` in Ollama, prompted with the role card + 5 real example messages | GPU, **0.83 GB** (828 MiB) |
| Scorer (1-5 satisfaction) | fine-tuned MiniLM (`all-MiniLM-L12-v2`), ONNX int8, **quantile setting** | CPU, about 10 ms per score |

- Speed: 0.47 s per customer message (Ollama with KV cache q8_0 + flash attention, `num_ctx` 1024).
- Score quality on 1,000 real Flipkart CSAT test rows: MAE 0.80, QWK 0.40; the score distribution matches real
  customers (distance 0.06). The quantile setting is the default because agent E needs realistic scores across many
  customers; `scorer.calibration: dev` gives the plain setting (QWK 0.43, distance 0.55).
- Previous setup (still available, `score_mode: llm`): `phi4-mini:3.8b` as writer and LLM scorer, 2.5 GB GPU.

Full numbers: `SIMULATOR_README.md` (kit), `SCORE_CALIBRATION.md` (score tests), `S2_simulator_llm.md` (model choice).

## Folder map

| Path | What |
|---|---|
| `simulator/` | the kit: `core.py` (turns + scoring), `prompts.py`, `scorer.py`, `config.yaml`, role cards, calibration maps, real example messages (anonymised) |
| `simulator/tests/` | unit tests (mocked Ollama, no GPU) + an optional live test |
| `scripts/` | every script that produced a number in the reports (`p1` ... `p9`) |
| `kaggle/` | the two Kaggle training jobs (scorer, writer LoRA) |
| `results/`, `reports/figures/` | result files and charts behind every number |
| `D5_simulator_realism.md` | D5: real customer messages, realism profile |
| `D6_satisfaction.md` | D6: real satisfaction scores, statistics, baselines |
| `S2_simulator_llm.md`, `SCORE_CALIBRATION.md`, `FINETUNING.md` | model choice, score calibration, fine-tuning |
| `DATA_SOURCES.md` | every dataset, real or generated, and its licence |
| `SHARE_WITH_YASSINE.md` | one-page handover |
| `BLOCKERS.md`, `JUDGE_SPOTCHECK*.md` | open items, human re-check sheets |

`models/scorer/` holds the scorer weights (`scorer_int8.onnx` + `tokenizer.json`, about 34 MB), included in git.
Not in git (see `.gitignore`): `data/` (downloads, LLM cache, processed sets), other model files, logs.

## How to run (from this folder, Windows)

```powershell
py -3.11 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m pytest simulator/tests -q          # mocked Ollama, no GPU, no weights needed
```

To run the simulator for real:

1. Install Ollama, then `ollama pull gemma3:1b`. Start Ollama with `OLLAMA_KV_CACHE_TYPE=q8_0` and
   `OLLAMA_FLASH_ATTENTION=1`. The kit calls `http://127.0.0.1:11434` (not `localhost`: on Windows that adds about
   2 s per request).
2. The scorer is already in `models/scorer/` (included in git; nothing to download). `pip install onnxruntime tokenizers`
   is covered by `requirements.txt`.
3. Use it from Python (run from this folder):

```python
from simulator import load_role_card, simulate_turn, score_conversation
card = load_role_card("simulator/role_cards/shopnova/SN-01.yaml")
```

Optional live test: `$env:CALLVERSE_LIVE="1"; python -m pytest simulator/tests/test_live.py -q`.

## Rebuild the data

The processed datasets are not in git (third-party data, over 200 MB). The scripts rebuild them from
the original sources into `data/`:

1. Download the raw datasets into `data/raw/` (Kaggle CLI with your own `~/.kaggle/kaggle.json`; Git Bash;
   `DATA_SOURCES.md` lists every dataset and its licence):

```sh
K=.venv/Scripts/kaggle
$K datasets download -d ddosad/ecommerce-customer-service-satisfaction -p data/raw/ecommerce-customer-service-satisfaction --unzip
$K datasets download -d thoughtvector/customer-support-on-twitter -p data/raw/customer-support-on-twitter      # keep the zip; p2 reads it
$K datasets download -d crowdflower/twitter-airline-sentiment -p data/raw/twitter-airline-sentiment --unzip
$K datasets download -d olistbr/brazilian-ecommerce -p data/raw/brazilian-ecommerce --unzip
$K datasets download -d andrewmvd/trip-advisor-hotel-reviews -p data/raw/trip-advisor-hotel-reviews --unzip
$K datasets download -d juhibhojani/airline-reviews -p data/raw/airline-reviews --unzip
$K datasets download -d satvicoder/call-center-data -p data/raw/call-center-data --unzip
$K datasets download -d suraj520/customer-support-ticket-dataset -p data/raw/support-tickets --unzip
mkdir -p data/raw/uss && for f in MWOZ SGD; do curl -sL -o data/raw/uss/$f.txt https://raw.githubusercontent.com/sunnweiwei/user-satisfaction-simulation/master/dataset/$f.txt; done
mkdir -p data/raw/medical_callcenter && curl -sL -o data/raw/medical_callcenter/all.zip "https://data.chhs.ca.gov/dataset/176e1bec-f1cc-41db-994c-ce5d460bbb68/resource/67d2fe1c-5c0e-488b-8064-01a0ba9e36ea/download/county-medi-cal-call-center-data-wwimo8q1.zip"
```

   The Medi-Cal ZIP holds the CSVs; the scripts expect `abandon.csv`, `volume.csv`, `wait.csv` (renamed from
   `average-call-abandonment-rate.csv`, `total-call-volume.csv`, `average-call-wait-time-*.csv`).
2. From `scripts/`: `python p1_build_real_scores.py` (D6 scores), `python p2_build_real_messages.py` (D5 messages),
   `python p8_data.py` (writer + scorer training data, train + dev rows only).

## Rebuild the scorer (optional)

The scorer weights are included in `models/scorer/`. To rebuild them from the data:

1. `python scripts/p8_data.py` writes the scorer training file (`kaggle_upload/data/scorer_traindev.jsonl`,
   train + dev rows only; test rows are never uploaded).
2. Upload it as a **private** Kaggle dataset, set its name in `kaggle/scorer/kernel-metadata.json`
   (`id` and `dataset_sources`), then `kaggle kernels push -p kaggle/scorer` (free T4 GPU).
3. When the job is done: `kaggle kernels output <kaggle-user>/callverse-scorer-ft -p kaggle_out/scorer`,
   then copy `scorer_int8.onnx` and `tokenizer.json` from `kaggle_out/scorer/onnx/` into `models/scorer/`.
4. The calibration maps are already in git (`simulator/scorer_calibration.json`); `python scripts/p8_final.py scorer`
   re-fits and re-checks them.

## Data use

The team approved using every dataset in `DATA_SOURCES.md` for this project (2026-10-26), including the Flipkart
eCommerce CSAT data (Kaggle `ddosad`, licence "other") and the USS dialogues (GitHub `sunnweiwei`, no licence file),
which the scorer was trained on. `DATA_SOURCES.md` keeps each source's real/generated label and stated licence.
