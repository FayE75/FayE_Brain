# FayE Brain — Engine Strength Testing

FayE Brain uses a Fishtest-inspired A/B match harness to compare a FayE candidate against the latest official Stockfish `master` available when a test starts.

## What is deliberately copied from the Fishtest methodology

- games are driven by **Fastchess**;
- opening positions come from `official-stockfish/books`;
- every opening is played as a **paired match**, once with each engine on each color (`-repeat`);
- both engines use the same time control, Threads, Hash, compile architecture, and opening position;
- the match uses the standard Fishtest-style resignation/draw adjudication values used in Fastchess examples:
  - resign after 3 consecutive moves at 600 cp;
  - draw checks after move 34, with 8 consecutive moves inside 20 cp;
- Fastchess pentanomial reporting is enabled;
- optional SPRT uses normalized Elo (`nElo`).

This is a small project harness, not the distributed Fishtest server. It does not claim to reproduce Fishtest's worker calibration, distributed scheduling, or server-side statistics.

## Opponent

The workflow clones:

```text
https://github.com/official-stockfish/Stockfish.git
```

with `--depth 1` at job start, then records the exact upstream SHA in the test artifact. This means `Stockfish-latest` is not a fixed historical binary: every new match compares against the current upstream master available when that job begins.

## Opening profiles

The workflow downloads a book archive directly from:

```text
https://github.com/official-stockfish/books
```

Profiles:

- `auto`
  - Standard: `UHO_Lichess_4852_v1.epd.zip`
  - Chess960/FRC: `3moves_FRC.epd.zip`
- `fishtest-standard`: `UHO_Lichess_4852_v1.epd.zip`
- `light-standard`: `UHO_4060_v4.epd.zip`
- `frc-3moves`: `3moves_FRC.epd.zip`
- `frc-starts`: `FRC_openings.epd.zip`

The official books repository currently lists `UHO_Lichess_4852_v1.epd` with 2,632,036 positions, `UHO_4060_v4.epd` with 241,670 positions, `3moves_FRC.epd` with 126,113 FRC positions at 6 ply, and `FRC_openings.epd` with all 960 starting positions.

## Match modes

### Fixed

Use a fixed even number of games. The workflow converts total games to paired rounds:

```text
200 total games = 100 opening positions × 2 colors
```

This is useful for smoke tests and quick comparisons.

### SPRT

Fastchess runs an SPRT with:

```text
H0 = user-selected nElo (default 0)
H1 = user-selected nElo (default 2)
alpha = 0.05
beta = 0.05
model = normalized
```

`max_games` is still a hard cap. If the SPRT boundary is not reached by then, the run simply ends without a pass/fail conclusion.

## Time controls

Suggested presets:

```text
10+0.1   quick/STC-style development test
60+0.6   LTC test
```

The time control is a clock per side, not a fixed time per move. Both engines receive exactly the same control.

## Running on GitHub Actions

After the workflow exists on the default branch:

1. open **Actions**;
2. choose **FayE vs Stockfish (Fishtest-style)**;
3. choose **Run workflow**;
4. select the FayE branch to test;
5. choose variant, book profile, mode, TC, game cap, and concurrency.

The job builds both engines from source with the same `x86-64-avx2` target, builds the Fastchess revision pinned by the current Fishtest worker, downloads the selected official opening book, checks UCI compliance, and starts paired games.

## Outputs

Every run uploads an artifact containing:

- `faye-vs-stockfish.pgn` with nodes, seldepth, NPS, and time-left fields;
- `fastchess.log` including pentanomial/SPRT output;
- `summary.json` and `summary.md`;
- `metadata.json` with FayE SHA, Stockfish SHA, Fastchess SHA, book, TC, and match settings.

The workflow summary shows FayE W/D/L, score percentage, and a descriptive logistic Elo point estimate. The point estimate alone is not used to accept a patch; paired pentanomial/SPRT evidence is the strength-testing signal.

## Recommended development gate

For each search/evaluation change:

1. compile + bench CI must pass;
2. run a short paired Standard match;
3. if the feature targets Chess960, also run a paired FRC match;
4. only promising changes move to larger STC/SPRT testing;
5. survivors are retested at `60+0.6` LTC before being treated as candidates for `main`.
