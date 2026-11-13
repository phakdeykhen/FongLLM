#!/bin/zsh
# FongAI Code = Prism ML Ternary-Bonsai-2-27B (Q2_0, Apache-2.0), loaded into Ollama as "fong-code".
# Q2_0 is the only Bonsai packing stock runtimes understand (PTQ1_0 / PQ2_0 need Prism's llama.cpp fork).
set -e
cd "${0:A:h}"
GGUF=Ternary-Bonsai-2-27B-Q2_0.gguf
BASE=https://huggingface.co/prism-ml/Ternary-Bonsai-2-27B-gguf/resolve/main
[ -s $GGUF ] || curl -L -C - --fail -o $GGUF $BASE/$GGUF
cat > Modelfile <<EOF
FROM ./$GGUF
# Prism's recommended sampling for Bonsai 2
PARAMETER temperature 1.0
PARAMETER top_p 0.95
PARAMETER top_k 20
PARAMETER min_p 0.05
# 16K context: 262K would not fit next to the weights on a 16GB Mac
PARAMETER num_ctx 16384
EOF
ollama create fong-code -f Modelfile
echo "Done. Pick 'FongAI Code' in the app, or: ollama run fong-code"
