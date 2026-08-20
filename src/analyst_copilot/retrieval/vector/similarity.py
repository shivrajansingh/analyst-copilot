"""Shared math utilities for vector retrieval."""

from __future__ import annotations

import math
from typing import List


def cosine_similarity(left: List[float], right: List[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right))
    norm_left = math.sqrt(sum(a * a for a in left))
    norm_right = math.sqrt(sum(b * b for b in right))
    if norm_left == 0 or norm_right == 0:
        return 0.0
    return dot / (norm_left * norm_right)


def cosine_similarity_matrix(
    query_vector: List[float],
    vectors: List[List[float]],
) -> List[float]:
    return [cosine_similarity(query_vector, vector) for vector in vectors]
