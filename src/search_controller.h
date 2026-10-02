/*
  FayE Brain - CPU-only adaptive search controller experiment.
  Derived from Stockfish and distributed under GPL-3.0-or-later.
*/

#ifndef FAYE_SEARCH_CONTROLLER_H_INCLUDED
#define FAYE_SEARCH_CONTROLLER_H_INCLUDED

#include <algorithm>
#include <cstdlib>

#include "types.h"

namespace Stockfish::Search {

// Lightweight state carried by each search worker.  It deliberately uses only
// signals that the alpha-beta search already computes, so the runtime path does
// not allocate memory and does not require a second neural network or a GPU.
struct AdaptiveSearchState {
    int   rootVolatility = 0;  // EMA, nominal range [0, 256]
    int   rootChurn      = 0;  // EMA of root best-move changes [0, 256]
    Value previousScore  = VALUE_NONE;
    Move  previousMove   = Move::none();

    void reset() {
        rootVolatility = 0;
        rootChurn      = 0;
        previousScore  = VALUE_NONE;
        previousMove   = Move::none();
    }

    void observe_root_iteration(Move bestMove, Value score) {
        if (!bestMove.is_ok() || !is_valid(score) || is_decisive(score))
        {
            previousMove  = bestMove;
            previousScore = score;
            return;
        }

        int scoreDelta = 0;
        if (is_valid(previousScore) && !is_decisive(previousScore))
            scoreDelta = std::min(192, std::abs(int(score) - int(previousScore)));

        const bool changed = previousMove.is_ok() && previousMove != bestMove;
        const int  sample  = std::clamp(scoreDelta + 96 * int(changed), 0, 256);

        // 3/4 memory gives a stable signal while still reacting within a few ID iterations.
        rootVolatility = (3 * rootVolatility + sample) / 4;
        rootChurn      = (3 * rootChurn + 256 * int(changed)) / 4;
        previousMove   = bestMove;
        previousScore  = score;
    }
};

// All search selectivity adjustments are expressed through one typed output.
// Positive LMR delta means more reduction. Positive margins/threshold deltas
// make forward pruning more conservative.
struct SearchControl {
    int uncertainty            = 0;  // [0, 256]
    int lmrDelta               = 0;  // reduction units, where ~1024 ~= one ply
    int futilityMarginDelta    = 0;  // centipawn-like Value units
    int nullMoveThresholdDelta = 0;  // raises/lowers the NMP gate
    int razorMarginDelta       = 0;  // raises/lowers the razoring margin
};

[[nodiscard]] inline SearchControl make_search_control(const AdaptiveSearchState& state,
                                                       Value                      staticEval,
                                                       Value                      effectiveEval,
                                                       Value                      ttValue,
                                                       int                        correctionValue,
                                                       Depth                      depth,
                                                       bool                       improving,
                                                       bool                       opponentWorsening,
                                                       bool                       ttHit,
                                                       bool                       ttPv) {
    int uncertainty = state.rootVolatility / 2 + state.rootChurn / 4;

    // Disagreement between the corrected static estimate and a usable searched/TT
    // estimate is treated as local evidence that aggressive pruning is risky.
    if (is_valid(staticEval) && !is_decisive(staticEval) && is_valid(effectiveEval)
        && !is_decisive(effectiveEval))
        uncertainty += std::min(72, std::abs(int(effectiveEval) - int(staticEval)) / 2);

    if (ttHit && is_valid(ttValue) && !is_decisive(ttValue) && is_valid(staticEval)
        && !is_decisive(staticEval))
        uncertainty += std::min(64, std::abs(int(ttValue) - int(staticEval)) / 3);

    // A large correction-history adjustment is another cheap disagreement signal.
    uncertainty += std::min(48, std::abs(correctionValue) / 32768);

    if (!improving)
        uncertainty += 12;
    if (!opponentWorsening)
        uncertainty += 12;
    if (ttPv)
        uncertainty -= 12;
    if (depth <= 3)
        uncertainty = 3 * uncertainty / 4;

    uncertainty = std::clamp(uncertainty, 0, 256);

    SearchControl out;
    out.uncertainty = uncertainty;

    if (uncertainty >= 176)
    {
        const int excess          = uncertainty - 176;
        out.lmrDelta              = -512 - 4 * excess;
        out.futilityMarginDelta   = 24 + excess / 2;
        out.nullMoveThresholdDelta = 20 + excess / 2;
        out.razorMarginDelta      = 18 + excess / 2;
    }
    else if (uncertainty <= 72)
    {
        const int confidence       = 72 - uncertainty;
        out.lmrDelta               = 192 + 2 * confidence;
        out.futilityMarginDelta    = -12 - confidence / 4;
        out.nullMoveThresholdDelta = -10 - confidence / 5;
        out.razorMarginDelta       = -10 - confidence / 5;
    }

    return out;
}

}  // namespace Stockfish::Search

#endif  // FAYE_SEARCH_CONTROLLER_H_INCLUDED
