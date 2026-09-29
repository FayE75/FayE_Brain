#!/usr/bin/env python3
"""Small local SPSA-style tuner for FayE UCI search parameters.

This is intentionally a transparent, resumable lab tuner, not a claim of being
bit-for-bit identical to the Stockfish fishtest SPSA implementation. Each
iteration plays a paired plus/minus match, then moves the center parameters
according to the score signal.
"""
from __future__ import annotations

import argparse
import json
import random
import subprocess
from pathlib import Path


def load_spec(path: Path) -> dict:
    spec = json.loads(path.read_text(encoding="utf-8"))
    if not spec.get("parameters"):
        raise ValueError("parameter spec has no parameters")
    return spec


def clip_round(value: float, p: dict) -> int:
    return int(round(max(float(p["min"]), min(float(p["max"]), value))))


def parse_score(pgn: Path, plus_name: str) -> tuple[float, int]:
    white = black = result = None
    plus_points = 0.0
    games = 0
    for raw in pgn.read_text(encoding="utf-8", errors="replace").splitlines():
        if raw.startswith('[White "'):
            white = raw.split('"', 2)[1]
        elif raw.startswith('[Black "'):
            black = raw.split('"', 2)[1]
        elif raw.startswith('[Result "'):
            result = raw.split('"', 2)[1]
        elif not raw.strip() and white and black and result:
            if plus_name in {white, black} and result in {"1-0", "0-1", "1/2-1/2"}:
                if result == "1/2-1/2":
                    plus_points += 0.5
                elif (result == "1-0" and white == plus_name) or (
                    result == "0-1" and black == plus_name
                ):
                    plus_points += 1.0
                games += 1
            white = black = result = None
    if white and black and result and plus_name in {white, black}:
        if result == "1/2-1/2":
            plus_points += 0.5
        elif (result == "1-0" and white == plus_name) or (
            result == "0-1" and black == plus_name
        ):
            plus_points += 1.0
        if result in {"1-0", "0-1", "1/2-1/2"}:
            games += 1
    return plus_points, games


def run_iteration(
    args,
    params_plus: dict[str, int],
    params_minus: dict[str, int],
    iteration: int,
    seed: int,
) -> tuple[float, int]:
    out = args.output_dir / f"iter-{iteration:04d}"
    out.mkdir(parents=True, exist_ok=True)
    pgn = out / "games.pgn"
    log = out / "fastchess.log"
    rounds = args.games_per_iteration // 2

    cmd = [
        str(args.fastchess),
        "-engine",
        f"cmd={args.engine}",
        "name=FayE-plus",
    ]
    for name, value in params_plus.items():
        cmd.append(f"option.{name}={value}")
    cmd += ["-engine", f"cmd={args.engine}", "name=FayE-minus"]
    for name, value in params_minus.items():
        cmd.append(f"option.{name}={value}")
    cmd += [
        "-each",
        f"tc={args.tc}",
        f"option.Threads={args.threads}",
        f"option.Hash={args.hash_mb}",
        "-variant",
        args.variant,
        "-openings",
        f"file={args.book}",
        "format=epd",
        "order=random",
        "-srand",
        str(seed),
        "-rounds",
        str(rounds),
        "-repeat",
        "-concurrency",
        str(args.concurrency),
        "-resign",
        "movecount=3",
        "score=600",
        "-draw",
        "movenumber=34",
        "movecount=8",
        "score=20",
        "-pgnout",
        f"file={pgn}",
        "notation=san",
        "append=false",
        "-report",
        "penta=true",
        "-ratinginterval",
        "0",
        "-testEnv",
    ]
    with log.open("w", encoding="utf-8") as fh:
        proc = subprocess.run(cmd, stdout=fh, stderr=subprocess.STDOUT, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"Fastchess failed in iteration {iteration}; see {log}")
    points, games = parse_score(pgn, "FayE-plus")
    signal = 0.0 if games == 0 else 2.0 * (points / games - 0.5)
    return signal, games


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", required=True, type=Path)
    ap.add_argument("--fastchess", required=True, type=Path)
    ap.add_argument("--book", required=True, type=Path)
    ap.add_argument("--spec", required=True, type=Path)
    ap.add_argument("--output-dir", required=True, type=Path)
    ap.add_argument("--iterations", type=int, default=8)
    ap.add_argument("--games-per-iteration", type=int, default=40)
    ap.add_argument("--tc", default="10+0.1")
    ap.add_argument("--variant", default="standard", choices=("standard", "fischerandom"))
    ap.add_argument("--threads", type=int, default=1)
    ap.add_argument("--hash-mb", type=int, default=64)
    ap.add_argument("--concurrency", type=int, default=2)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--resume", action="store_true")
    args = ap.parse_args()
    if args.games_per_iteration < 2 or args.games_per_iteration % 2:
        ap.error("--games-per-iteration must be an even integer >= 2")

    spec = load_spec(args.spec)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    state_path = args.output_dir / "spsa_state.json"
    rng = random.Random(args.seed)

    if args.resume and state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        theta = {k: float(v) for k, v in state["theta"].items()}
        start = int(state["iteration"]) + 1
        history = state.get("history", [])
    else:
        theta = {p["name"]: float(p["initial"]) for p in spec["parameters"]}
        start = 1
        history = []

    by_name = {p["name"]: p for p in spec["parameters"]}
    alpha = float(spec.get("alpha", 0.602))
    gamma = float(spec.get("gamma", 0.101))
    a_offset = float(spec.get("a_offset", 10.0))

    for k in range(start, args.iterations + 1):
        delta = {name: rng.choice((-1, 1)) for name in theta}
        plus, minus = {}, {}
        for name, center in theta.items():
            p = by_name[name]
            ck = float(p["perturb"]) / (k**gamma)
            plus[name] = clip_round(center + ck * delta[name], p)
            minus[name] = clip_round(center - ck * delta[name], p)

        signal, games = run_iteration(args, plus, minus, k, args.seed + k)
        for name in theta:
            p = by_name[name]
            ak = float(p["learning_rate"]) / ((k + a_offset) ** alpha)
            theta[name] = float(
                clip_round(theta[name] + ak * signal * delta[name], p)
            )

        item = {
            "iteration": k,
            "plus": plus,
            "minus": minus,
            "score_signal": signal,
            "games": games,
            "theta_after": dict(theta),
        }
        history.append(item)
        state = {"iteration": k, "theta": theta, "history": history, "spec": spec}
        state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(item), flush=True)

    best = {name: int(round(value)) for name, value in theta.items()}
    (args.output_dir / "best_params.json").write_text(
        json.dumps(best, indent=2) + "\n", encoding="utf-8"
    )
    print("best_params", json.dumps(best, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
