#!/usr/bin/env python3
"""Cheap, deterministic chess-position features for FayE uncertainty pilots.

These features are deliberately engine-independent. They are a bootstrap input
representation for validating the learning target (search instability). If
that target proves useful, the next stage can replace this extractor with a
small head over internal NNUE activations without changing the dataset labels.
"""
from __future__ import annotations

import chess

PIECE_TYPES = (chess.PAWN, chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN)
START_COUNTS = {
    chess.PAWN: 8.0,
    chess.KNIGHT: 2.0,
    chess.BISHOP: 2.0,
    chess.ROOK: 2.0,
    chess.QUEEN: 1.0,
}
PIECE_CP = {
    chess.PAWN: 100,
    chess.KNIGHT: 320,
    chess.BISHOP: 330,
    chess.ROOK: 500,
    chess.QUEEN: 900,
}
CENTER = (chess.D4, chess.E4, chess.D5, chess.E5)


def _pawn_islands(board: chess.Board, color: chess.Color) -> int:
    files = sorted({chess.square_file(sq) for sq in board.pieces(chess.PAWN, color)})
    if not files:
        return 0
    islands = 1
    for a, b in zip(files, files[1:]):
        if b != a + 1:
            islands += 1
    return islands


def _doubled_pawns(board: chess.Board, color: chess.Color) -> int:
    total = 0
    pawns = board.pieces(chess.PAWN, color)
    for file_idx in range(8):
        count = sum(1 for sq in pawns if chess.square_file(sq) == file_idx)
        total += max(0, count - 1)
    return total


def _attack_count(board: chess.Board, color: chess.Color) -> int:
    attacked = set()
    pieces = (
        board.pieces(chess.PAWN, color)
        | board.pieces(chess.KNIGHT, color)
        | board.pieces(chess.BISHOP, color)
        | board.pieces(chess.ROOK, color)
        | board.pieces(chess.QUEEN, color)
        | board.pieces(chess.KING, color)
    )
    for sq in pieces:
        attacked.update(board.attacks(sq))
    return len(attacked)


def _center_attack_count(board: chess.Board, color: chess.Color) -> int:
    return sum(1 for sq in CENTER if board.is_attacked_by(color, sq))


def extract_features(board: chess.Board) -> list[float]:
    """Return 24 normalized scalar features."""
    feats: list[float] = []

    for pt in PIECE_TYPES:
        diff = len(board.pieces(pt, chess.WHITE)) - len(board.pieces(pt, chess.BLACK))
        feats.append(diff / START_COUNTS[pt])

    for pt in PIECE_TYPES:
        total = len(board.pieces(pt, chess.WHITE)) + len(board.pieces(pt, chess.BLACK))
        feats.append(total / (2.0 * START_COUNTS[pt]))

    feats.append(1.0 if board.turn == chess.WHITE else -1.0)
    feats.append(min(board.legal_moves.count(), 64) / 64.0)
    feats.append(1.0 if board.is_check() else 0.0)
    feats.append(min(board.halfmove_clock, 100) / 100.0)

    white_castle = int(board.has_kingside_castling_rights(chess.WHITE)) + int(
        board.has_queenside_castling_rights(chess.WHITE)
    )
    black_castle = int(board.has_kingside_castling_rights(chess.BLACK)) + int(
        board.has_queenside_castling_rights(chess.BLACK)
    )
    feats.extend((white_castle / 2.0, black_castle / 2.0))

    material = 0
    for pt in PIECE_TYPES:
        material += PIECE_CP[pt] * (
            len(board.pieces(pt, chess.WHITE)) - len(board.pieces(pt, chess.BLACK))
        )
    feats.append(max(-1.0, min(1.0, material / 3900.0)))
    feats.append(len(board.piece_map()) / 32.0)
    feats.append(
        (_center_attack_count(board, chess.WHITE) - _center_attack_count(board, chess.BLACK))
        / 4.0
    )
    feats.append((_attack_count(board, chess.WHITE) - _attack_count(board, chess.BLACK)) / 64.0)
    feats.append((_pawn_islands(board, chess.WHITE) - _pawn_islands(board, chess.BLACK)) / 4.0)
    feats.append((_doubled_pawns(board, chess.WHITE) - _doubled_pawns(board, chess.BLACK)) / 4.0)
    feats.append(
        float(
            int(len(board.pieces(chess.BISHOP, chess.WHITE)) >= 2)
            - int(len(board.pieces(chess.BISHOP, chess.BLACK)) >= 2)
        )
    )

    wk = board.king(chess.WHITE)
    bk = board.king(chess.BLACK)
    feats.append(0.0 if wk is None or bk is None else chess.square_distance(wk, bk) / 7.0)

    assert len(feats) == 24
    return feats
