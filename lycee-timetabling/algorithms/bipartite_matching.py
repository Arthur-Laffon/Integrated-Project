"""Unweighted bipartite maximum matching by an iterative Kuhn search.

Adapted from the MIT-licensed implementation at:
    https://algorithm.tamnd.com/kuhn-algorithm/
    https://github.com/tamnd/algorithm/blob/main/nodes/graphs/matching/kuhn-algorithm/impl/python/kuhn_algorithm.py
Original authors: The algorithm contributors (2026).
SPDX-License-Identifier: MIT. Full attribution and licence below.

Changes: retain only the boolean full-matching query needed for classroom
allocation. The iterative DFS/augmenting-path reversal is based on the source.
"""


def has_full_bipartite_matching(neighbors: list[list[int]], right_count: int) -> bool:
    """Return whether each left item can receive a distinct allowed right item."""
    if len(neighbors) > right_count:
        return False
    mate_right = [-1] * right_count
    for root in range(len(neighbors)):
        seen = [False] * right_count
        # One explicit frame per left vertex in the alternating path:
        # [left, next-neighbor index, right used to descend].
        stack = [[root, 0, -1]]
        found = False
        while stack:
            frame = stack[-1]
            left, pos = frame[0], frame[1]
            if pos >= len(neighbors[left]):
                stack.pop()
                continue
            right = neighbors[left][pos]
            frame[1] = pos + 1
            if seen[right]:
                continue
            seen[right] = True
            incumbent = mate_right[right]
            if incumbent != -1:
                frame[2] = right
                stack.append([incumbent, 0, -1])
                continue
            # Reverse this augmenting path, assigning all encountered pupils.
            for depth in range(len(stack) - 1, -1, -1):
                target = right if depth == len(stack) - 1 else stack[depth][2]
                mate_right[target] = stack[depth][0]
            found = True
            break
        if not found:
            return False
    return True

# Third-party MIT licence and attribution (included in source, not as a separate file):
# MIT License
#
# Copyright (c) 2026 The algorithm contributors <https://algorithm.tamnd.com/about/>
#
# Permission is hereby granted, free of charge, to any person obtaining a copy of this software and
# associated documentation files (the "Software"), to deal in the Software without restriction, including
# without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the
# following conditions:
#
# The above copyright notice and this permission notice shall be included in all copies or substantial
# portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT
# LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO
# EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER
# IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE
# USE OR OTHER DEALINGS IN THE SOFTWARE.
#
# Source: https://github.com/tamnd/algorithm/blob/main/LICENSES/MIT.txt
