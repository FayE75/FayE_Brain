#!/usr/bin/env bash
set -euo pipefail

: "${ENGINE_A:?Set ENGINE_A}"
: "${ENGINE_B:?Set ENGINE_B}"
: "${FASTCHESS:?Set FASTCHESS}"
: "${BOOK_FILE:?Set BOOK_FILE}"

ENGINE_A_NAME="${ENGINE_A_NAME:-FayE-candidate}"
ENGINE_B_NAME="${ENGINE_B_NAME:-FayE-parent}"
ENGINE_A_OPTIONS="${ENGINE_A_OPTIONS:-}"
ENGINE_B_OPTIONS="${ENGINE_B_OPTIONS:-}"
VARIANT="${VARIANT:-standard}"
TC="${TC:-10+0.1}"
ROUNDS="${ROUNDS:-100}"
CONCURRENCY="${CONCURRENCY:-2}"
THREADS="${THREADS:-1}"
HASH_MB="${HASH_MB:-64}"
SEED="${SEED:-1}"
MODE="${MODE:-fixed}"
SPRT_ELO0="${SPRT_ELO0:-0}"
SPRT_ELO1="${SPRT_ELO1:-2}"
OUTPUT_DIR="${OUTPUT_DIR:-results}"

case "$VARIANT" in
  standard) FC_VARIANT=standard ;;
  fischerandom|frc|chess960) FC_VARIANT=fischerandom ;;
  *) echo "Unsupported VARIANT=$VARIANT" >&2; exit 2 ;;
esac
case "$MODE" in
  fixed|sprt) ;;
  *) echo "Unsupported MODE=$MODE" >&2; exit 2 ;;
esac

mkdir -p "$OUTPUT_DIR"
PGN="$OUTPUT_DIR/ab-match.pgn"
LOG="$OUTPUT_DIR/fastchess.log"
rm -f "$PGN" "$LOG"

engine_a=( -engine "cmd=$ENGINE_A" "name=$ENGINE_A_NAME" )
engine_b=( -engine "cmd=$ENGINE_B" "name=$ENGINE_B_NAME" )

IFS=';' read -ra opts_a <<< "$ENGINE_A_OPTIONS"
for opt in "${opts_a[@]}"; do
  [[ -z "$opt" ]] || engine_a+=("option.$opt")
done
IFS=';' read -ra opts_b <<< "$ENGINE_B_OPTIONS"
for opt in "${opts_b[@]}"; do
  [[ -z "$opt" ]] || engine_b+=("option.$opt")
done

cmd=(
  "$FASTCHESS"
  "${engine_a[@]}"
  "${engine_b[@]}"
  -each "tc=$TC" "option.Threads=$THREADS" "option.Hash=$HASH_MB"
  -variant "$FC_VARIANT"
  -openings "file=$BOOK_FILE" "format=epd" "order=random"
  -srand "$SEED"
  -rounds "$ROUNDS"
  -repeat
  -concurrency "$CONCURRENCY"
  -resign "movecount=3" "score=600"
  -draw "movenumber=34" "movecount=8" "score=20"
  -pgnout "file=$PGN" "notation=san" "append=false" "nodes=true" "seldepth=true" "nps=true" "timeleft=true"
  -report "penta=true"
  -ratinginterval 20
  -event "$ENGINE_A_NAME vs $ENGINE_B_NAME"
  -site "FayE_Brain"
  -testEnv
  -recover
)

if [[ "$MODE" == sprt ]]; then
  cmd+=(
    -sprt
    "elo0=$SPRT_ELO0"
    "elo1=$SPRT_ELO1"
    "alpha=0.05"
    "beta=0.05"
    "model=normalized"
  )
fi

printf 'Command:'
printf ' %q' "${cmd[@]}"
printf '\n'
set -o pipefail
"${cmd[@]}" 2>&1 | tee "$LOG"
