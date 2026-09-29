#!/usr/bin/env python3
"""Generate FayE uncertainty labels from shallow-vs-deep teacher search."""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

import chess
import chess.engine

from features import extract_features


def epd_to_board(line: str, chess960: bool) -> chess.Board | None:
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    fields = line.split()
    if len(fields) < 4:
        return None
    fen = " ".join(fields[:4]) + " 0 1"
    try:
        return chess.Board(fen, chess960=chess960)
    except ValueError:
        return None


def score_cp(info: dict, turn: chess.Color) -> int:
    score = info["score"].pov(turn).score(mate_score=100_000)
    return int(score if score is not None else 0)


def first_move_uci(info: dict) -> str | None:
    pv = info.get("pv") or []
    return pv[0].uci() if pv else None


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--engine", required=True, type=Path)
    p.add_argument("--epd", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--positions", type=int, default=1000)
    p.add_argument("--shallow-nodes", type=int, default=5_000)
    p.add_argument("--deep-nodes", type=int, default=50_000)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--threads", type=int, default=1)
    p.add_argument("--hash-mb", type=int, default=64)
    p.add_argument("--chess960", action="store_true")
    args = p.parse_args()

    if args.deep_nodes <= args.shallow_nodes:
        p.error("--deep-nodes must be greater than --shallow-nodes")

    boards = []
    with args.epd.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            board = epd_to_board(line, args.chess960)
            if board is not None and not board.is_game_over():
                boards.append(board)

    if not boards:
        raise SystemExit("No legal positions found in EPD")

    rng = random.Random(args.seed)
    rng.shuffle(boards)
    boards = boards[: min(args.positions, len(boards))]

    args.output.parent.mkdir(parents=True, exist_ok=True)
    engine = chess.engine.SimpleEngine.popen_uci(str(args.engine))
    engine.configure({"Threads": args.threads, "Hash": args.hash_mb})
    if args.chess960:
        engine.configure({"UCI_Chess960": True})

    written = 0
    try:
        with args.output.open("w", encoding="utf-8") as out:
            for idx, board in enumerate(boards, 1):
                shallow = engine.analyse(
                    board,
                    chess.engine.Limit(nodes=args.shallow_nodes),
                    info=chess.engine.INFO_ALL,
                )
                deep = engine.analyse(
                    board,
                    chess.engine.Limit(nodes=args.deep_nodes),
                    info=chess.engine.INFO_ALL,
                )

                s_cp = score_cp(shallow, board.turn)
                d_cp = score_cp(deep, board.turn)
                s_move = first_move_uci(shallow)
                d_move = first_move_uci(deep)
                eval_swing = min(abs(d_cp - s_cp) / 400.0, 1.0)
                move_changed = 1.0 if s_move and d_move and s_move != d_move else 0.0
                uncertainty = min(1.0, 0.70 * eval_swing + 0.30 * move_changed)

                record = {
                    "fen": board.fen(),
                    "features": extract_features(board),
                    "shallow_cp": s_cp,
                    "deep_cp": d_cp,
                    "shallow_move": s_move,
                    "deep_move": d_move,
                    "shallow_depth": shallow.get("depth"),
                    "deep_depth": deep.get("depth"),
                    "shallow_nodes": shallow.get("nodes"),
                    "deep_nodes": deep.get("nodes"),
                    "eval_swing_cp": abs(d_cp - s_cp),
                    "bestmove_changed": bool(move_changed),
                    "uncertainty_target": uncertainty,
                }
                out.write(json.dumps(record, separators=(",", ":")) + "\n")
                written += 1
                if idx % 50 == 0:
                    print(f"labeled {idx}/{len(boards)} positions", flush=True)
    finally:
        engine.quit()

    print(f"wrote {written} examples to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
