#!/usr/bin/env python3
"""Create a reproducible FayE experiment manifest."""
from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], text=True).strip()


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--id", required=True, help="e.g. FAYE-0002")
    p.add_argument("--title", required=True)
    p.add_argument("--feature", required=True)
    p.add_argument("--candidate-ref", default="HEAD")
    p.add_argument("--parent-ref", default="main")
    p.add_argument("--patch", default="none")
    p.add_argument("--training-artifact", default=None)
    p.add_argument("--output-dir", type=Path, default=Path("experiments"))
    args = p.parse_args()

    manifest = {
        "id": args.id,
        "title": args.title,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "status": "planned",
        "feature": args.feature,
        "candidate": {
            "ref": args.candidate_ref,
            "sha": git("rev-parse", args.candidate_ref),
        },
        "parent": {"ref": args.parent_ref, "sha": git("rev-parse", args.parent_ref)},
        "feature_patch": args.patch,
        "training_artifact": args.training_artifact,
        "validation": {
            "offline": None,
            "candidate_vs_parent": None,
            "external_vs_stockfish": None,
        },
        "decision": None,
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    out = args.output_dir / f"{args.id}.json"
    if out.exists():
        raise SystemExit(f"Refusing to overwrite {out}")
    out.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
