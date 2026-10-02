#!/usr/bin/env python3
from pathlib import Path


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text()
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    path.write_text(text.replace(old, new, 1))


search_h = Path("src/search.h")
search_cpp = Path("src/search.cpp")

replace_once(
    search_h,
    '#include "score.h"\n#include "syzygy/tbprobe.h"',
    '#include "score.h"\n#include "search_controller.h"\n#include "syzygy/tbprobe.h"',
    "search_controller include",
)

replace_once(
    search_h,
    '    Depth     rootDepth;\n    Value     rootDelta;\n\n    PVMoves lastIterationIdxPV;',
    '    Depth     rootDepth;\n    Value     rootDelta;\n\n    AdaptiveSearchState adaptiveSearch;\n    PVMoves             lastIterationIdxPV;',
    "adaptive worker state",
)

replace_once(
    search_cpp,
    '    PVMoves pv;\n\n    RootPVMoves lastBestMovePV;',
    '    PVMoves pv;\n\n    adaptiveSearch.reset();\n\n    RootPVMoves lastBestMovePV;',
    "adaptive reset",
)

replace_once(
    search_cpp,
    '''        if (!threads.stop)\n        {\n            if (lastBestMovePV.empty() || lastBestMovePV[0] != rootMoves[0].pv[0])''',
    '''        if (!threads.stop)\n        {\n            if (!rootMoves.empty() && !rootMoves[0].pv.empty())\n                adaptiveSearch.observe_root_iteration(rootMoves[0].pv[0], rootMoves[0].score);\n\n            if (lastBestMovePV.empty() || lastBestMovePV[0] != rootMoves[0].pv[0])''',
    "root instability observer",
)

replace_once(
    search_cpp,
    '''    improving         = ss->staticEval > (ss - 2)->staticEval;\n    opponentWorsening = ss->staticEval > -(ss - 1)->staticEval;\n\n    // Hindsight adjustment of reductions based on static evaluation difference''',
    '''    improving         = ss->staticEval > (ss - 2)->staticEval;\n    opponentWorsening = ss->staticEval > -(ss - 1)->staticEval;\n\n    const SearchControl searchControl =\n      make_search_control(adaptiveSearch, ss->staticEval, eval, ttData.value, correctionValue, depth,\n                          improving, opponentWorsening, ss->ttHit, ss->ttPv);\n\n    // Hindsight adjustment of reductions based on static evaluation difference''',
    "controller construction",
)

replace_once(
    search_cpp,
    '    if (allNode && eval < alpha - 342 * depth && !seekMate)',
    '    if (allNode && eval < alpha - (342 * depth + searchControl.razorMarginDelta) && !seekMate)',
    "adaptive razoring",
)

replace_once(
    search_cpp,
    '''        Value futilityMargin = futilityMult * depth\n                             - (2789 * improving + 335 * opponentWorsening) * futilityMult / 1024\n                             + std::abs(correctionValue) / 198435;\n\n        if (eval - futilityMargin >= beta)''',
    '''        Value futilityMargin = futilityMult * depth\n                             - (2789 * improving + 335 * opponentWorsening) * futilityMult / 1024\n                             + std::abs(correctionValue) / 198435\n                             + searchControl.futilityMarginDelta;\n\n        if (eval - futilityMargin >= beta)''',
    "adaptive futility",
)

replace_once(
    search_cpp,
    '''        && ss->staticEval + 50 * ss->priorNMPFailHigh >= beta - 13 * depth - 47 * improving + 365\n        && !excludedMove''',
    '''        && ss->staticEval + 50 * ss->priorNMPFailHigh\n             >= beta - 13 * depth - 47 * improving + 365 + searchControl.nullMoveThresholdDelta\n        && !excludedMove''',
    "adaptive null move gate",
)

replace_once(
    search_cpp,
    '''        r -= moveCount * 65;\n        r -= std::abs(correctionValue) / 26310;\n\n        // Increase reduction for cut nodes''',
    '''        r -= moveCount * 65;\n        r -= std::abs(correctionValue) / 26310;\n        r += searchControl.lmrDelta;\n\n        // Increase reduction for cut nodes''',
    "adaptive LMR",
)

print("Applied FAYE-0008 v1 adaptive-search controller patch")
