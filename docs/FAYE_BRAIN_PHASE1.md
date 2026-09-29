# FayE Brain — Phase 1

## Baseline

FayE Brain starts from the official Stockfish master baseline pinned at:

- upstream: `official-stockfish/Stockfish`
- baseline commit: `0a215d6c9e48856ef630013b8ab8312941a59057`
- baseline date: 2026-09-22

The goal is to develop new CPU-efficient evaluation/search signals while preserving Stockfish's core strengths: incremental NNUE updates, SIMD-friendly inference, and alpha-beta search.

## Important audit result

The current Stockfish NNUE is already more relational than older NNUE descriptions suggest. In particular, the baseline already contains:

- `FullThreats` features for attacker/target relations;
- `PP_3Wide` pawn-pair features;
- `HalfKAv2_hm` positional features;
- a 1024-dimensional transformed representation feeding small 32-unit hidden layers.

Therefore FayE Brain should not simply duplicate attack/defend or pawn-pair features. Any new relational component must demonstrate useful information per unit of compute beyond what these existing feature sets already provide.

## Phase 1 objective: observability before intervention

The first FayE-specific code adds a lightweight **complexity proxy** to the `eval` trace. It measures disagreement between:

1. a cheap material-only view; and
2. the raw NNUE evaluation.

Both signals are normalized to `[-1024, 1024]`, and the absolute disagreement is reported on `[0, 2048]`.

This is **not** a learned uncertainty estimate and is **not** used by search yet. It is diagnostic instrumentation only.

Rationale: before adding a trainable uncertainty head or changing pruning/reduction rules, collect evidence that a cheap disagreement signal correlates with positions where deeper search is valuable.

## Planned experiments

### P1-A — Diagnostic validation

Collect the FayE complexity proxy together with:

- NNUE value;
- search depth;
- node count;
- best-move stability across iterative deepening;
- evaluation swing after deeper search;
- tactical/quiet position labels when available.

A useful signal should correlate with search instability or large deeper-search corrections while remaining extremely cheap to compute.

### P1-B — Search-neutral benchmark

Confirm that adding diagnostic reporting does not change normal search results or benchmark signature when the `eval` command is not used.

The repository includes a FayE-specific GitHub Actions workflow that compiles the engine, runs a UCI smoke test, and executes the built-in benchmark for changes targeting `main`.

### P2 — Learned uncertainty head

Only if Phase 1 shows useful correlation, train a very small quantized head that estimates search uncertainty/instability from existing NNUE activations.

Target properties:

- integer inference;
- tiny parameter count;
- no GPU requirement at runtime;
- negligible NPS loss;
- output suitable for search control, not replacement of NNUE value.

### P3 — Uncertainty-guided search

Test conservative use of uncertainty for search decisions, for example:

- slightly reducing LMR in high-uncertainty nodes;
- allowing stronger reductions in very stable low-uncertainty nodes;
- selectively extending tactically unstable positions.

Every search change must be A/B tested independently.

### P4 — Policy / move-ordering signal

Investigate whether a tiny move-prior head can improve move ordering enough to offset its inference cost. The target is not MCTS-style policy search; the target is better alpha-beta ordering with minimal overhead.

### P5 — Additional relational residuals

Only after profiling existing `FullThreats` and `PP_3Wide`, investigate relations not already encoded efficiently, such as selected x-ray, pin, overloaded-defender, king-zone, or low-rank piece-interaction residuals.

These should be incremental and sparse rather than a full graph neural network recomputed at every node.

## Testing rule

FayE Brain follows a one-change-at-a-time policy:

1. establish a clean baseline;
2. measure compile/bench correctness;
3. measure NPS cost;
4. run paired engine matches;
5. retain only changes with reproducible benefit.

No architectural idea is assumed stronger until testing demonstrates it.

## Licensing

FayE Brain remains a derivative of Stockfish and therefore remains under GPLv3-compatible distribution requirements. Stockfish attribution and source availability must be preserved.
