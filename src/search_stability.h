/*
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
