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

// Lightweight state carried by each search worker. It deliberately uses only
// signals already produced by alpha-beta search, so the runtime path performs
// no dynamic allocation and requires no second network or GPU.
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
            scoreDelta = std::min(160, std::abs(int(score) - int(previousScore)));

        const bool changed = previousMove.is_ok() && previousMove != bestMove;
        const int  sample  = std::clamp(scoreDelta + 80 * int(changed), 0, 256);

        // Slightly longer memory than v1: root instability should provide context,
        // not dominate every descendant node.
        rootVolatility = (7 * rootVolatility + sample) / 8;
        rootChurn      = (7 * rootChurn + 256 * int(changed)) / 8;
        previousMove   = bestMove;
        previousScore  = score;
    }
};

// Positive LMR delta means more reduction. Positive futility margin delta makes
// child-node futility pruning more conservative. v2 intentionally leaves NMP
// and razoring at parent behavior so the first ablation is diagnosable.
struct SearchControl {
    int uncertainty            = 0;  // [0, 256]
    int lmrDelta               = 0;  // reduction units, where ~1024 ~= one ply
    int futilityMarginDelta    = 0;  // centipawn-like Value units
    int nullMoveThresholdDelta = 0;  // v2: deliberately disabled
    int razorMarginDelta       = 0;  // v2: deliberately disabled
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
    SearchControl out;

    // Do not perturb very shallow selective-search decisions. At these depths the
    // parent heuristics are already highly tuned and the uncertainty samples are noisy.
    if (depth <= 3)
        return out;

    // v2 reduces the global/root contribution and lets local disagreement dominate.
    int uncertainty = state.rootVolatility / 4 + state.rootChurn / 8;

    if (is_valid(staticEval) && !is_decisive(staticEval) && is_valid(effectiveEval)
        && !is_decisive(effectiveEval))
        uncertainty += std::min(64, std::abs(int(effectiveEval) - int(staticEval)) / 3);

    if (ttHit && is_valid(ttValue) && !is_decisive(ttValue) && is_valid(staticEval)
        && !is_decisive(staticEval))
        uncertainty += std::min(56, std::abs(int(ttValue) - int(staticEval)) / 4);

    // Correction-history magnitude remains useful, but with less authority than v1.
    uncertainty += std::min(36, std::abs(correctionValue) / 49152);

    if (!improving)
        uncertainty += 8;
    if (!opponentWorsening)
        uncertainty += 8;
    if (ttPv)
        uncertainty -= 8;

    uncertainty    = std::clamp(uncertainty, 0, 256);
    out.uncertainty = uncertainty;

    // Smoother, smaller response than v1. Only LMR and child-node futility are
    // controlled in this stage. NMP and razoring remain exactly at parent policy.
    constexpr int HighThreshold = 160;
    constexpr int LowThreshold  = 80;

    if (uncertainty >= HighThreshold)
    {
        const int excess        = uncertainty - HighThreshold;
        out.lmrDelta            = -224 - 2 * excess;
        out.futilityMarginDelta = 12 + excess / 4;
    }
    else if (uncertainty <= LowThreshold)
    {
        const int confidence    = LowThreshold - uncertainty;
        out.lmrDelta            = 96 + confidence;
        out.futilityMarginDelta = -6 - confidence / 8;
    }

    return out;
}

}  // namespace Stockfish::Search

#endif  // FAYE_SEARCH_CONTROLLER_H_INCLUDED
