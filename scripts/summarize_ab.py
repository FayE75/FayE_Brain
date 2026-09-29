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
            m = HEADER_RE.match(line)
            if m:
                key, value = m.groups()
                if key == "Event" and headers:
                    if "Result" in headers:
                        yield headers
                    headers = {}
                headers[key] = value
            elif not line.strip() and "Result" in headers and (
                "White" in headers or "Black" in headers
            ):
                yield headers
                headers = {}
    if "Result" in headers:
        yield headers


def score_for(game: dict[str, str], name: str) -> float | None:
    white, black, result = game.get("White"), game.get("Black"), game.get("Result")
    if name not in {white, black}:
        return None
    if result == "1/2-1/2":
        return 0.5
    if result == "1-0":
        return 1.0 if white == name else 0.0
    if result == "0-1":
        return 1.0 if black == name else 0.0
    return None


def logistic_elo(score: float) -> float | None:
    if not 0.0 < score < 1.0:
        return None
    return 400.0 * math.log10(score / (1.0 - score))


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("pgn", type=Path)
    p.add_argument("--candidate-name", default="FayE-candidate")
    p.add_argument("--parent-name", default="FayE-parent")
    p.add_argument("--json-out", type=Path)
    p.add_argument("--markdown-out", type=Path)
    args = p.parse_args()

    wins = draws = losses = 0
    white_games = black_games = 0
    for game in iter_games(args.pgn):
        s = score_for(game, args.candidate_name)
        if s is None:
            continue
        if game.get("White") == args.candidate_name:
            white_games += 1
        else:
            black_games += 1
        if s == 1.0:
            wins += 1
        elif s == 0.5:
            draws += 1
        else:
            losses += 1

    games = wins + draws + losses
    score = (wins + 0.5 * draws) / games if games else None
    elo = logistic_elo(score) if score is not None else None
    summary = {
        "candidate": args.candidate_name,
        "parent": args.parent_name,
        "games": games,
        "wins": wins,
        "draws": draws,
        "losses": losses,
        "candidate_score": score,
        "descriptive_logistic_elo": elo,
        "candidate_white_games": white_games,
        "candidate_black_games": black_games,
        "decision_note": (
            "Use Fastchess paired pentanomial/SPRT output for accept/reject decisions; "
            "this Elo is descriptive only."
        ),
    }
    text = json.dumps(summary, indent=2)
    print(text)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(text + "\n", encoding="utf-8")
    if args.markdown_out:
        score_text = "n/a" if score is None else f"{100 * score:.2f}%"
        elo_text = "n/a" if elo is None else f"{elo:+.2f} Elo"
        md = (
            "## Candidate vs parent\n\n"
            f"- Candidate: **{args.candidate_name}**\n"
            f"- Parent: **{args.parent_name}**\n"
            f"- Games: **{games}**\n"
            f"- Candidate W/D/L: **{wins} / {draws} / {losses}**\n"
            f"- Candidate score: **{score_text}**\n"
            f"- Descriptive logistic Elo: **{elo_text}**\n\n"
            "> Merge/reject decisions should use the paired Fastchess pentanomial/SPRT result, not the point estimate alone.\n"
        )
        args.markdown_out.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_out.write_text(md, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
