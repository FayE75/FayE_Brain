/*
  FayE Brain - CPU-only adaptive search controller experiment.
  Derived from Stockfish and distributed under GPL-3.0-or-later.
*/

#ifndef FAYE_SEARCH_CONTROLLER_H_INCLUDED
#define FAYE_SEARCH_CONTROLLER_H_INCLUDED

#include <algorithm>
#include <cstdint>
#include <cstdlib>

#include "types.h"

namespace Stockfish::Search {

#if defined(_MSC_VER)
    #define FAYE_NOINLINE __declspec(noinline)
    #define FAYE_COLD
#elif defined(__GNUC__) || defined(__clang__)
    #define FAYE_NOINLINE __attribute__((noinline))
    #define FAYE_COLD __attribute__((cold))
#else
    #define FAYE_NOINLINE
    #define FAYE_COLD
#endif

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

// v2 keeps the return payload register-sized. The old v1 SearchControl carried
// five 32-bit fields (20 bytes), including an exported uncertainty value that
// search.cpp never consumed. Four signed 16-bit deltas are sufficient for all
// v2 ranges and preserve the existing integration points for disabled NMP/razoring.
struct SearchControl {
    std::int16_t lmrDelta               = 0;  // reduction units, ~1024 ~= one ply
    std::int16_t futilityMarginDelta    = 0;  // centipawn-like Value units
    std::int16_t nullMoveThresholdDelta = 0;  // v2: deliberately disabled
    std::int16_t razorMarginDelta       = 0;  // v2: deliberately disabled
};

static_assert(sizeof(SearchControl) == 8, "FAYE-0008 v2 SearchControl must stay register-sized");

// Keep the expensive multi-signal calculation out of the alpha-beta hot path.
// This helper is reached only for sufficiently deep nodes through the tiny wrapper below.
// `inline` gives this header-defined helper one ODR entity across translation units;
// FAYE_NOINLINE still prevents the compiler from folding its body back into search().
[[nodiscard]] inline FAYE_NOINLINE FAYE_COLD SearchControl
make_search_control_deep(const AdaptiveSearchState& state,
                         Value                      staticEval,
                         Value                      effectiveEval,
                         Value                      ttValue,
                         int                        correctionValue,
                         bool                       improving,
                         bool                       opponentWorsening,
                         bool                       ttHit,
                         bool                       ttPv) {
    SearchControl out;

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

    uncertainty = std::clamp(uncertainty, 0, 256);

    // Smoother, smaller response than v1. Only LMR and child-node futility are
    // controlled in this stage. NMP and razoring remain exactly at parent policy.
    constexpr int HighThreshold = 160;
    constexpr int LowThreshold  = 80;

    if (uncertainty >= HighThreshold)
    {
        const int excess        = uncertainty - HighThreshold;
        out.lmrDelta            = static_cast<std::int16_t>(-224 - 2 * excess);
        out.futilityMarginDelta = static_cast<std::int16_t>(12 + excess / 4);
    }
    else if (uncertainty <= LowThreshold)
    {
        const int confidence    = LowThreshold - uncertainty;
        out.lmrDelta            = static_cast<std::int16_t>(96 + confidence);
        out.futilityMarginDelta = static_cast<std::int16_t>(-6 - confidence / 8);
    }

    return out;
}

[[nodiscard]] inline SearchControl make_search_control(const AdaptiveSearchState& state,
                                                       Value                      staticEval,
                                                       Value                      effectiveEval,
                                                       Value                      ttValue,
                                                       int                        correctionValue,
                                                       Depth                      depth,
                                                       bool                       improving,
                                                       bool                       opponentWorsening,
                                                       bool                       ttHit,
                                                       bool                       ttPv,
                                                       int                        stabilityLmrDelta) {
    // v2 keeps the node-heavy shallow and mid-depth tree exactly on parent policy.
    // The controller activates only from depth 11 upward. This preserves the
    // adaptive architecture where evidence is more stable while keeping the
    // controller outside the exponentially larger shallow subtree.
    if (depth <= 10)
        return {};

    SearchControl out =
      make_search_control_deep(state, staticEval, effectiveEval, ttValue, correctionValue,
                               improving, opponentWorsening, ttHit, ttPv);

    // FAYE-0009 adds only a small cross-depth LMR correction. The clamp
    // keeps the combined response within the already-tested FAYE-0008-v2
    // operating envelope plus a conservative instability allowance.
    out.lmrDelta = static_cast<std::int16_t>(
      std::clamp(int(out.lmrDelta) + stabilityLmrDelta, -512, 256));
    return out;
}

#undef FAYE_NOINLINE
#undef FAYE_COLD

}  // namespace Stockfish::Search

#endif  // FAYE_SEARCH_CONTROLLER_H_INCLUDED
