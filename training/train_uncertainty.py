#!/usr/bin/env python3
"""Train a tiny FayE uncertainty head from teacher-search labels."""
from __future__ import annotations

import argparse
import json
import math
import random
from pathlib import Path

import torch
from torch import nn
from torch.utils.data import DataLoader, TensorDataset


class TinyUncertaintyHead(nn.Module):
    def __init__(self, input_dim: int, hidden: int):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(input_dim, hidden),
            nn.ReLU(),
            nn.Linear(hidden, 1),
            nn.Sigmoid(),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x).squeeze(-1)


def load_jsonl(path: Path) -> tuple[torch.Tensor, torch.Tensor]:
    xs, ys = [], []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            row = json.loads(line)
            xs.append(row["features"])
            ys.append(float(row["uncertainty_target"]))
    if not xs:
        raise ValueError("dataset is empty")
    return torch.tensor(xs, dtype=torch.float32), torch.tensor(ys, dtype=torch.float32)


def quantized_state_dict(model: nn.Module) -> dict:
    out = {}
    for name, tensor in model.state_dict().items():
        t = tensor.detach().cpu().float()
        max_abs = float(t.abs().max()) if t.numel() else 0.0
        scale = max(max_abs / 127.0, 1e-12)
        q = torch.clamp(torch.round(t / scale), -127, 127).to(torch.int8)
        out[name] = {
            "shape": list(q.shape),
            "scale": scale,
            "values": q.flatten().tolist(),
        }
    return out


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dataset", required=True, type=Path)
    p.add_argument("--output-dir", required=True, type=Path)
    p.add_argument("--hidden", type=int, default=16)
    p.add_argument("--epochs", type=int, default=25)
    p.add_argument("--batch-size", type=int, default=256)
    p.add_argument("--learning-rate", type=float, default=1e-3)
    p.add_argument("--weight-decay", type=float, default=1e-5)
    p.add_argument("--val-fraction", type=float, default=0.2)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--device", default="auto", choices=("auto", "cpu", "cuda"))
    args = p.parse_args()

    random.seed(args.seed)
    torch.manual_seed(args.seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(args.seed)

    x, y = load_jsonl(args.dataset)
    n = len(x)
    if n < 20:
        raise SystemExit("Need at least 20 labeled positions")

    perm = torch.randperm(n, generator=torch.Generator().manual_seed(args.seed))
    val_n = max(1, int(n * args.val_fraction))
    val_idx, train_idx = perm[:val_n], perm[val_n:]
    x_train, y_train = x[train_idx], y[train_idx]
    x_val, y_val = x[val_idx], y[val_idx]

    device = "cuda" if args.device == "auto" and torch.cuda.is_available() else args.device
    if device == "auto":
        device = "cpu"
    dev = torch.device(device)

    model = TinyUncertaintyHead(x.shape[1], args.hidden).to(dev)
    optimizer = torch.optim.AdamW(
        model.parameters(), lr=args.learning_rate, weight_decay=args.weight_decay
    )
    loss_fn = nn.MSELoss()
    loader = DataLoader(
        TensorDataset(x_train, y_train), batch_size=args.batch_size, shuffle=True
    )

    best_val = math.inf
    best_state = None
    history = []
    for epoch in range(1, args.epochs + 1):
        model.train()
        total, count = 0.0, 0
        for bx, by in loader:
            bx, by = bx.to(dev), by.to(dev)
            optimizer.zero_grad(set_to_none=True)
            pred = model(bx)
            loss = loss_fn(pred, by)
            loss.backward()
            optimizer.step()
            total += float(loss) * len(bx)
            count += len(bx)

        model.eval()
        with torch.no_grad():
            pred = model(x_val.to(dev))
            val_mse = float(loss_fn(pred, y_val.to(dev)))
            val_mae = float(torch.mean(torch.abs(pred - y_val.to(dev))))
        train_mse = total / max(count, 1)
        history.append(
            {
                "epoch": epoch,
                "train_mse": train_mse,
                "val_mse": val_mse,
                "val_mae": val_mae,
            }
        )
        print(
            f"epoch={epoch:03d} train_mse={train_mse:.6f} "
            f"val_mse={val_mse:.6f} val_mae={val_mae:.6f}"
        )
        if val_mse < best_val:
            best_val = val_mse
            best_state = {
                k: v.detach().cpu().clone() for k, v in model.state_dict().items()
            }

    assert best_state is not None
    model.load_state_dict(best_state)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    torch.save(
        {"state_dict": best_state, "input_dim": x.shape[1], "hidden": args.hidden},
        args.output_dir / "faye_uncertainty.pt",
    )

    export = {
        "format": "faye-tiny-uncertainty-int8-v1",
        "input_dim": int(x.shape[1]),
        "hidden": args.hidden,
        "weights": quantized_state_dict(model),
    }
    (args.output_dir / "faye_uncertainty_int8.json").write_text(
        json.dumps(export, indent=2) + "\n", encoding="utf-8"
    )

    metrics = {
        "examples": n,
        "train_examples": len(train_idx),
        "val_examples": len(val_idx),
        "best_val_mse": best_val,
        "hyperparameters": {
            "hidden": args.hidden,
            "epochs": args.epochs,
            "batch_size": args.batch_size,
            "learning_rate": args.learning_rate,
            "weight_decay": args.weight_decay,
            "val_fraction": args.val_fraction,
            "seed": args.seed,
            "device": str(dev),
        },
        "history": history,
    }
    (args.output_dir / "metrics.json").write_text(
        json.dumps(metrics, indent=2, default=str) + "\n", encoding="utf-8"
    )
    print(f"best_val_mse={best_val:.6f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
