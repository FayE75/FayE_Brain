#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path

HEADER_RE = re.compile(r'^\[([A-Za-z0-9_]+)\s+"(.*)"\]\s*$')


def iter_games(path: Path):
    headers: dict[str, str] = {}
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for raw in handle:
            line = raw.rstrip("\n")
            match = HEADER_RE.match(line)
            if match:
                key, value = match.groups()
                if key == "Event" and headers:
                    if "Result" in headers:
                        yield headers
                    headers = {}
                headers[key] = value
            elif not line.strip() and "Result" in headers and ("White" in headers or "Black" in headers):
                yield headers
                headers = {}
    if "Result" in headers:
        yield headers


def result_for_faye(game: dict[str, str], faye_name: str):
    white = game.get("White", "")
    black = game.get("Black", "")
    result = game.get("Result", "*")

    if faye_name not in {white, black}:
        return None
    if result == "1/2-1/2":
        return "draw"
    if result not in {"1-0", "0-1"}:
        return "unknown"

    white_won = result == "1-0"
    faye_is_white = white == faye_name
    return "win" if white_won == faye_is_white else "loss"


def logistic_elo(score: float):
    if score <= 0.0 or score >= 1.0:
        return None
    return 400.0 * math.log10(score / (1.0 - score))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("pgn", type=Path)
    parser.add_argument("--faye-name", default="FayE")
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--markdown-out", type=Path)
    args = parser.parse_args()

    counts = {"win": 0, "draw": 0, "loss": 0, "unknown": 0}
    by_color = {
        "white": {"win": 0, "draw": 0, "loss": 0, "unknown": 0},
        "black": {"win": 0, "draw": 0, "loss": 0, "unknown": 0},
    }

    for game in iter_games(args.pgn):
        result = result_for_faye(game, args.faye_name)
        if result is None:
            continue
        counts[result] += 1
        color = "white" if game.get("White") == args.faye_name else "black"
        by_color[color][result] += 1

    decided = counts["win"] + counts["draw"] + counts["loss"]
    score = ((counts["win"] + 0.5 * counts["draw"]) / decided) if decided else None
    elo = logistic_elo(score) if score is not None else None

    summary = {
        "games": decided,
        "wins": counts["win"],
        "draws": counts["draw"],
        "losses": counts["loss"],
        "unknown": counts["unknown"],
        "score": score,
        "logistic_elo_point_estimate": elo,
        "by_color": by_color,
        "note": "The Elo value is a descriptive point estimate only; use Fastchess SPRT/pentanomial output for inferential testing.",
    }

    text = json.dumps(summary, indent=2, sort_keys=True)
    print(text)

    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(text + "\n", encoding="utf-8")

    if args.markdown_out:
        score_pct = "n/a" if score is None else f"{100.0 * score:.2f}%"
        elo_text = "n/a" if elo is None else f"{elo:+.2f} Elo"
        md = (
            "## FayE vs latest Stockfish\n\n"
            f"- Games: **{decided}**\n"
            f"- FayE W/D/L: **{counts['win']} / {counts['draw']} / {counts['loss']}**\n"
            f"- FayE score: **{score_pct}**\n"
            f"- Descriptive logistic Elo: **{elo_text}**\n"
            f"- As White W/D/L: **{by_color['white']['win']} / {by_color['white']['draw']} / {by_color['white']['loss']}**\n"
            f"- As Black W/D/L: **{by_color['black']['win']} / {by_color['black']['draw']} / {by_color['black']['loss']}**\n\n"
            "> The Elo number above is only a point estimate. For strength decisions, use paired games and the Fastchess pentanomial/SPRT result.\n"
        )
        args.markdown_out.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_out.write_text(md, encoding="utf-8")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
