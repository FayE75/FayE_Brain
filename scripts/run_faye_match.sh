#!/usr/bin/env bash
set -euo pipefail

: "${FAYE_ENGINE:?Set FAYE_ENGINE to the FayE binary}"
: "${STOCKFISH_ENGINE:?Set STOCKFISH_ENGINE to the Stockfish binary}"
: "${FASTCHESS:?Set FASTCHESS to the fastchess binary}"
: "${BOOK_FILE:?Set BOOK_FILE to an extracted EPD opening book}"

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
SPRT_ALPHA="${SPRT_ALPHA:-0.05}"
SPRT_BETA="${SPRT_BETA:-0.05}"
OUTPUT_DIR="${OUTPUT_DIR:-results}"

if [[ ! "$ROUNDS" =~ ^[1-9][0-9]*$ ]]; then
  echo "ROUNDS must be a positive integer" >&2
  exit 2
fi
if [[ ! "$CONCURRENCY" =~ ^[1-9][0-9]*$ ]]; then
  echo "CONCURRENCY must be a positive integer" >&2
  exit 2
fi
if [[ ! "$THREADS" =~ ^[1-9][0-9]*$ ]]; then
  echo "THREADS must be a positive integer" >&2
  exit 2
fi
if [[ ! "$HASH_MB" =~ ^[1-9][0-9]*$ ]]; then
  echo "HASH_MB must be a positive integer" >&2
  exit 2
fi

case "$VARIANT" in
  standard)
    FC_VARIANT="standard"
    ;;
  fischerandom|frc|chess960)
    FC_VARIANT="fischerandom"
    ;;
  *)
    echo "Unsupported VARIANT=$VARIANT (use standard or fischerandom)" >&2
    exit 2
    ;;
esac

case "$MODE" in
  fixed|sprt) ;;
  *)
    echo "Unsupported MODE=$MODE (use fixed or sprt)" >&2
    exit 2
    ;;
esac

for path in "$FAYE_ENGINE" "$STOCKFISH_ENGINE" "$FASTCHESS" "$BOOK_FILE"; do
  if [[ ! -e "$path" ]]; then
    echo "Required path not found: $path" >&2
    exit 2
  fi
done

mkdir -p "$OUTPUT_DIR"
PGN="$OUTPUT_DIR/faye-vs-stockfish.pgn"
LOG="$OUTPUT_DIR/fastchess.log"
rm -f "$PGN" "$LOG"

TOTAL_GAMES=$((ROUNDS * 2))

echo "FayE engine      : $FAYE_ENGINE"
echo "Stockfish engine : $STOCKFISH_ENGINE"
echo "Fastchess        : $FASTCHESS"
echo "Variant          : $FC_VARIANT"
echo "Opening book     : $BOOK_FILE"
echo "Time control     : $TC"
echo "Threads/engine   : $THREADS"
echo "Hash/engine      : ${HASH_MB} MB"
echo "Concurrency      : $CONCURRENCY"
echo "Paired rounds    : $ROUNDS"
echo "Maximum games    : $TOTAL_GAMES"
echo "Mode             : $MODE"
echo "Random seed      : $SEED"

cmd=(
  "$FASTCHESS"
  -engine "cmd=$FAYE_ENGINE" "name=FayE"
  -engine "cmd=$STOCKFISH_ENGINE" "name=Stockfish-latest"
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
  -event "FayE Brain vs latest Stockfish"
  -site "FayE_Brain"
  -testEnv
  -recover
)

if [[ "$MODE" == "sprt" ]]; then
  cmd+=(
    -sprt
    "elo0=$SPRT_ELO0"
    "elo1=$SPRT_ELO1"
    "alpha=$SPRT_ALPHA"
    "beta=$SPRT_BETA"
    "model=normalized"
  )
  echo "SPRT             : H0=${SPRT_ELO0} nElo, H1=${SPRT_ELO1} nElo, alpha=${SPRT_ALPHA}, beta=${SPRT_BETA}"
fi

printf 'Command:'
printf ' %q' "${cmd[@]}"
printf '\n'

set -o pipefail
"${cmd[@]}" 2>&1 | tee "$LOG"
