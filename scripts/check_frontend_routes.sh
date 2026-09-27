#!/usr/bin/env bash
# Headless render check for every hash route.
cd "$LOCALAPPDATA/Temp" || exit 1
CHROME="/c/Program Files/Google/Chrome/Application/chrome.exe"
for r in benchmarks pipeline tokens latency costs projects memory agents models history settings; do
  "$CHROME" --headless=new --disable-gpu --no-sandbox --no-first-run \
    --user-data-dir="$LOCALAPPDATA/Temp/cprof" --virtual-time-budget=12000 \
    --enable-logging=stderr --v=0 --dump-dom "http://127.0.0.1:8012/#/$r" > "d_$r.html" 2> "l_$r.log"
  B=$(wc -c < "d_$r.html")
  M=$(grep -o 'class="metric"' "d_$r.html" | wc -l)
  P=$(grep -o 'class="panel"' "d_$r.html" | wc -l)
  S=$(grep -o '<svg' "d_$r.html" | wc -l)
  T=$(grep -o 'class="data"' "d_$r.html" | wc -l)
  K=$(grep -o 'class="skel' "d_$r.html" | wc -l)
  E=$(grep -icE "uncaught|is not a function|is not defined|cannot read propert" "l_$r.log")
  printf "%-11s bytes=%-6s metrics=%-3s panels=%-3s svg=%-2s tables=%-3s skel=%-3s JSERR=%s\n" \
    "$r" "$B" "$M" "$P" "$S" "$T" "$K" "$E"
done
