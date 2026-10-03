from pathlib import Path
import json


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly 1 match, found {count}")
    return text.replace(old, new, 1)


root = Path(__file__).resolve().parents[1]

# -----------------------------------------------------------------------------
# 1) Add a compact per-worker position stability table.
# -----------------------------------------------------------------------------
stability_header = r'''/*
  FayE Brain - FAYE-0009 per-position cross-depth stability memory.
  Derived from Stockfish and distributed under GPL-3.0-or-later.
*/

#ifndef FAYE_SEARCH_STABILITY_H_INCLUDED
#define FAYE_SEARCH_STABILITY_H_INCLUDED

#include <algorithm>
#include <array>
#include <cstdint>
#include <cstdlib>

#include "types.h"

namespace Stockfish::Search {

// A deliberately small, direct-mapped table that survives the iterative-
// deepening loop of one UCI `go`, but is reset before the next search.
// It records whether the best move / score for the exact same position remain
// stable as that position is revisited at greater depth.
class PositionStabilityTable {
   public:
    static constexpr usize EntryCount = 4096;

    struct Entry {
        std::uint32_t key32      = 0;
        std::uint16_t move16     = 0;
        std::int16_t  score16    = 0;
        std::uint8_t  depth8     = 0;
        std::int8_t   confidence = 0;  // [-7, 7], positive = stable
    };

    static_assert((EntryCount & (EntryCount - 1)) == 0,
                  "FAYE-0009 stability table size must be a power of two");
    static_assert(sizeof(Entry) <= 12,
                  "FAYE-0009 stability entry must stay cache-compact");

    void reset() { entries.fill({}); }

    [[nodiscard]] int lmr_delta(Key key, Depth depth) const {
        if (depth <= 10)
            return 0;

        const Entry& e = entries[index(key)];
        if (!e.depth8 || e.key32 != fingerprint(key) || int(e.depth8) >= int(depth))
            return 0;

        // Require repeated cross-depth evidence before affecting search.
        // Stable positions may be reduced very slightly more; unstable positions
        // are searched more conservatively. Values are in Stockfish LMR units
        // where ~1024 is roughly one ply.
        if (e.confidence >= 3)
            return 48;
        if (e.confidence <= -3)
            return -96;
        return 0;
    }

    void observe(Key key, Move bestMove, Value score, Depth depth) {
        if (depth <= 10 || !bestMove.is_ok() || !is_valid(score) || is_decisive(score))
            return;

        Entry&              e   = entries[index(key)];
        const std::uint32_t fp  = fingerprint(key);
        const int           dep = std::clamp(int(depth), 1, 255);
        const int           sc  = std::clamp(int(score), -30000, 30000);

        int confidence = 0;

        if (e.depth8 && e.key32 == fp)
        {
            // Cross-depth means deeper evidence only. Do not let repeated visits
            // at the same or shallower depth overwrite the stronger observation.
            if (dep <= int(e.depth8))
                return;

            confidence = int(e.confidence);
            const bool sameMove  = e.move16 == bestMove.raw();
            const int  scoreDiff = std::abs(sc - int(e.score16));

            int sample = 0;
            if (!sameMove)
                sample = -2;
            else if (scoreDiff <= 24)
                sample = 2;
            else if (scoreDiff <= 64)
                sample = 1;
            else if (scoreDiff >= 128)
                sample = -1;

            confidence = std::clamp(confidence + sample, -7, 7);
        }

        e.key32      = fp;
        e.move16     = bestMove.raw();
        e.score16    = static_cast<std::int16_t>(sc);
        e.depth8     = static_cast<std::uint8_t>(dep);
        e.confidence = static_cast<std::int8_t>(confidence);
    }

   private:
    [[nodiscard]] static std::uint32_t fingerprint(Key key) {
        return static_cast<std::uint32_t>(key ^ (key >> 32));
    }

    [[nodiscard]] static usize index(Key key) {
        const Key mixed = key ^ (key >> 33) ^ (key >> 17);
        return static_cast<usize>(mixed) & (EntryCount - 1);
    }

    std::array<Entry, EntryCount> entries{};
};

}  // namespace Stockfish::Search

#endif  // FAYE_SEARCH_STABILITY_H_INCLUDED
'''
(root / "src/search_stability.h").write_text(stability_header)

# -----------------------------------------------------------------------------
# 2) Wire the table into each search worker.
# -----------------------------------------------------------------------------
search_h_path = root / "src/search.h"
search_h = search_h_path.read_text()
search_h = replace_once(
    search_h,
    '#include "search_controller.h"\n',
    '#include "search_controller.h"\n#include "search_stability.h"\n',
    "search.h include",
)
search_h = replace_once(
    search_h,
    '    AdaptiveSearchState adaptiveSearch;\n    PVMoves             lastIterationIdxPV;\n',
    '    AdaptiveSearchState   adaptiveSearch;\n    PositionStabilityTable stabilityTable;\n    PVMoves               lastIterationIdxPV;\n',
    "search.h worker state",
)
search_h_path.write_text(search_h)

# -----------------------------------------------------------------------------
# 3) Let cross-depth stability add a small independent LMR delta on top of the
#    promoted FAYE-0008-v2 controller. All other v2 behavior stays unchanged.
# -----------------------------------------------------------------------------
controller_path = root / "src/search_controller.h"
controller = controller_path.read_text()
controller = replace_once(
    controller,
    '                                                       bool                       ttHit,\n'
    '                                                       bool                       ttPv) {\n',
    '                                                       bool                       ttHit,\n'
    '                                                       bool                       ttPv,\n'
    '                                                       int                        stabilityLmrDelta) {\n',
    "search_controller wrapper signature",
)
controller = replace_once(
    controller,
    '    return make_search_control_deep(state, staticEval, effectiveEval, ttValue, correctionValue,\n'
    '                                    improving, opponentWorsening, ttHit, ttPv);\n',
    '    SearchControl out =\n'
    '      make_search_control_deep(state, staticEval, effectiveEval, ttValue, correctionValue,\n'
    '                               improving, opponentWorsening, ttHit, ttPv);\n\n'
    '    // FAYE-0009 adds only a small cross-depth LMR correction. The clamp\n'
    '    // keeps the combined response within the already-tested FAYE-0008-v2\n'
    '    // operating envelope plus a conservative instability allowance.\n'
    '    out.lmrDelta = static_cast<std::int16_t>(\n'
    '      std::clamp(int(out.lmrDelta) + stabilityLmrDelta, -512, 256));\n'
    '    return out;\n',
    "search_controller wrapper return",
)
controller_path.write_text(controller)

# -----------------------------------------------------------------------------
# 4) Reset once per go, probe before LMR policy is formed, and learn only from
#    completed non-root/non-singular searches that actually found a best move.
# -----------------------------------------------------------------------------
search_cpp_path = root / "src/search.cpp"
search_cpp = search_cpp_path.read_text()
search_cpp = replace_once(
    search_cpp,
    '    adaptiveSearch.reset();\n\n    RootPVMoves lastBestMovePV;\n',
    '    adaptiveSearch.reset();\n    stabilityTable.reset();\n\n    RootPVMoves lastBestMovePV;\n',
    "search.cpp reset",
)
search_cpp = replace_once(
    search_cpp,
    '    const SearchControl searchControl =\n'
    '      make_search_control(adaptiveSearch, ss->staticEval, eval, ttData.value, correctionValue, depth,\n'
    '                          improving, opponentWorsening, ss->ttHit, ss->ttPv);\n',
    '    const int stabilityLmrDelta =\n'
    '      (!rootNode && !excludedMove && depth > 10) ? stabilityTable.lmr_delta(posKey, depth) : 0;\n\n'
    '    const SearchControl searchControl =\n'
    '      make_search_control(adaptiveSearch, ss->staticEval, eval, ttData.value, correctionValue, depth,\n'
    '                          improving, opponentWorsening, ss->ttHit, ss->ttPv, stabilityLmrDelta);\n',
    "search.cpp controller probe",
)
search_cpp = replace_once(
    search_cpp,
    '    // Step 24. Write gathered information in transposition table. Note that the\n'
    '    // static evaluation is saved as it was before correction history.\n',
    '    // FAYE-0009: retain cross-depth evidence for this exact internal position.\n'
    '    // Excluded-move searches are deliberately ignored because they describe an\n'
    '    // artificial search state rather than the normal position policy.\n'
    '    if (!rootNode && !excludedMove && depth > 10 && bestMove && !is_decisive(bestValue))\n'
    '        stabilityTable.observe(posKey, bestMove, bestValue, depth);\n\n'
    '    // Step 24. Write gathered information in transposition table. Note that the\n'
    '    // static evaluation is saved as it was before correction history.\n',
    "search.cpp stability observe",
)
search_cpp_path.write_text(search_cpp)

# -----------------------------------------------------------------------------
# 5) Record experiment intent so later result/promotion decisions remain auditable.
# -----------------------------------------------------------------------------
manifest = {
    "experiment": "FAYE-0009-v1-cross-depth-stability-memory",
    "status": "engineering-screen",
    "base_branch": "main",
    "base_sha": "7ec08af834430aef731f1189bf982418d2a6af94",
    "promoted_baseline": "FAYE-0008-v2",
    "feature": {
        "name": "Per-Position Cross-Depth Stability Memory",
        "scope": "per-worker, per-go, internal search positions",
        "table_entries": 4096,
        "minimum_depth": 11,
        "stable_threshold": 3,
        "unstable_threshold": -3,
        "stable_lmr_delta": 48,
        "unstable_lmr_delta": -96,
        "only_controlled_channel": "LMR",
        "persistent_across_games": False,
        "gpu_required": False
    },
    "design_guards": [
        "No NNUE or evaluation changes",
        "No NMP, ProbCut, TT-cutoff, razoring, or futility-policy changes",
        "No heap allocation in the node hot path",
        "Ignore excluded-move/singular-search observations",
        "Require repeated deeper observations before LMR changes",
        "Reset stability memory once per UCI go"
    ],
    "primary_strength_protocol": {
        "opponent": "official-stockfish/Stockfish master fetched at run start",
        "paired_openings": "UHO_Lichess_4852_v1.epd",
        "threads": 1,
        "games": 600,
        "workflow": ".github/workflows/faye-vs-stockfish-latest.yml"
    }
}
manifest_path = root / "experiments/FAYE-0009-v1-cross-depth-stability.json"
manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")

print("FAYE-0009 cross-depth stability patch applied successfully")
