#!/bin/zsh
# Build FongAI end to end:  zsh finetune/run.sh
# 1 data -> 2 LoRA training -> 3 fuse into one model -> 4 import into Ollama as "fongai".
set -e
cd "$(dirname "$0")/.."
PY=.venv/bin/python
curl -s localhost:11434/api/generate -d '{"model":"mistral","keep_alive":0}' >/dev/null || true   # free RAM for training
$PY finetune/build_data.py
$PY -m mlx_lm lora -c finetune/lora_config.yaml
rm -rf finetune/fused
$PY -m mlx_lm fuse --model finetune/base-qwen2.5-7b-4bit --adapter-path finetune/adapters --save-path finetune/fused --dequantize
cp finetune/LICENSE-Qwen finetune/fused/ 2>/dev/null || true
# Ollama 0.40+ can't import Qwen2 safetensors, so go through GGUF (needs: brew install llama.cpp,
# git clone --depth 1 https://github.com/ggml-org/llama.cpp finetune/llama.cpp-src)
PYTHONPATH=finetune/llama.cpp-src/gguf-py $PY finetune/llama.cpp-src/convert_hf_to_gguf.py finetune/fused --outtype f16 --outfile finetune/fongai-f16.gguf
llama-quantize finetune/fongai-f16.gguf finetune/fongai-q4_K_M.gguf Q4_K_M
rm -f finetune/fongai-f16.gguf
cd finetune && ollama create fongai -f Modelfile
echo "Done: ollama run fongai"
