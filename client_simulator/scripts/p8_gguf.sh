#!/bin/sh
# Convert the merged fine-tuned writer (Kaggle job A) to GGUF Q4_K_M and import it into Ollama as callverse-sim-writer.
# Temporary tools (llama.cpp clone, venv, binaries, f16 GGUF) are deleted at the end.
set -e
cd "$(dirname "$0")/.."
T=models/tmp
mkdir -p $T
M=kaggle_out/writer/merged
curl -sL -o $M/tokenizer.model https://huggingface.co/unsloth/gemma-3-1b-it/resolve/main/tokenizer.model
[ -d $T/llama.cpp ] || git clone -q --depth 1 https://github.com/ggml-org/llama.cpp $T/llama.cpp
[ -d $T/venv ] || py -3.11 -m venv $T/venv
$T/venv/Scripts/python -c "import torch" 2>/dev/null || $T/venv/Scripts/pip install -q torch --index-url https://download.pytorch.org/whl/cpu
$T/venv/Scripts/pip install -q numpy sentencepiece safetensors transformers protobuf pyyaml
$T/venv/Scripts/python $T/llama.cpp/convert_hf_to_gguf.py $M --outtype f16 --outfile $T/writer-f16.gguf
URL=$(curl -s https://api.github.com/repos/ggml-org/llama.cpp/releases/latest | $T/venv/Scripts/python -c "import sys,json;print([a['browser_download_url'] for a in json.load(sys.stdin)['assets'] if 'bin-win-cpu-x64' in a['name']][0])")
curl -sL -o $T/llama-bin.zip "$URL"
mkdir -p $T/bin && unzip -oq $T/llama-bin.zip -d $T/bin
Q=$(find $T/bin -name "llama-quantize.exe" | head -1)
"$Q" $T/writer-f16.gguf models/writer/callverse-sim-writer-Q4_K_M.gguf Q4_K_M > $T/quantize.log 2>&1
printf 'FROM ./callverse-sim-writer-Q4_K_M.gguf\nPARAMETER stop "<end_of_turn>"\n' > models/writer/Modelfile
(cd models/writer && ollama create callverse-sim-writer -f Modelfile)
ollama list | grep callverse
rm -rf $T kaggle_out/writer/merged
echo GGUF_DONE
