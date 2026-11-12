#!/bin/zsh
# Live progress of the FongAI build:  zsh finetune/progress.sh   (Ctrl+C to quit; the build keeps running)
cd "$(dirname "$0")"
LOG=build.log
bar() { local n=$1 t=$2 w=30; local f=$(( t>0 ? n*w/t : 0 )); printf '[%s%s] %d/%d (%d%%)' "${(l:$f::#:)}" "${(l:$((w-f))::.:)}" $n $t $(( t>0 ? n*100/t : 0 )); }
while true; do
  clear
  echo "FongAI build  —  $(date +%H:%M:%S)\n"
  data=$(grep -oE '^\[[0-9]+/[0-9]+\]' $LOG 2>/dev/null | tail -1 | tr -d '[]')
  iter=$(sed $'s/\e\\[[0-9;]*m//g' $LOG | grep -E '^ *[0-9]+ +([0-9.]+|nan) [▼▲]' 2>/dev/null | tail -1 | awk '{print $1, $2}')
  val=$(sed $'s/\e\\[[0-9;]*m//g' $LOG | grep -E '^ *[0-9]+ +val ' 2>/dev/null | tail -1 | awk '{print $1, $3}')
  s1="…"; s2=" "; s3=" "; s4=" "
  if [[ -n $data ]]; then echo -n "1. Making training data   "; bar ${data%/*} ${data#*/}; echo; fi
  if grep -q '^identity=' $LOG 2>/dev/null; then echo "   $(grep '^identity=' $LOG)"; fi
  if [[ -n $iter ]]; then
    n=${iter%% *}
    echo -n "2. LoRA training          "; bar $n 400; echo
    [[ ${iter##* } == nan ]] && echo "   !! train loss is nan: training is broken, stop it with Ctrl+C in its window or: pkill -f 'mlx_lm lora'"
    echo "   last train loss: ${iter##* }   ${val:+last val loss: ${val##* }}"
  fi
  [[ -d fused ]] && echo "3. Fusing adapter into model … $(du -sh fused 2>/dev/null | cut -f1)"
  grep -q 'Done: ollama run fongai' $LOG 2>/dev/null && echo "4. Imported into Ollama ✔  →  ollama run fongai"
  pgrep -f 'finetune/run.sh' >/dev/null && echo "\nstatus: RUNNING" || echo "\nstatus: STOPPED (see last lines below)"
  echo "RAM swap: $(sysctl -n vm.swapusage | awk '{print $6}')"
  echo "\n--- last log lines ---"; tail -4 $LOG
  pgrep -f 'finetune/run.sh' >/dev/null || break
  sleep 5
done
