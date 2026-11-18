"""Integer-capacity Dinic maximum flow, specialised for scheduling feasibility.

Adapted from the MIT-licensed iterative Python implementation at:
    https://algorithm.tamnd.com/dinic/
    https://github.com/tamnd/algorithm/blob/main/nodes/graphs/flows-and-cuts/dinic/impl/python/dinic.py
Original authors: The algorithm contributors (2026).
SPDX-License-Identifier: MIT. Full attribution and licence below.

Modifications: remove general numeric types, flow reconstruction, callbacks and
minimum-cut output; add the required-flow cutoff. The BFS level graph and
non-recursive blocking-flow DFS follow the credited implementation.
"""

from collections import deque


def dinic_max_flow(node_count: int, edges: list[tuple[int, int, int]],
                   source: int, sink: int, cutoff: int | None = None) -> int:
    """Return max flow (or `cutoff` once reached) on an integer directed network.

    Parallel edges are supported; capacities must be nonnegative. No recursive
    calls are made, and each level-graph edge has a current-arc pointer.
    """
    if source == sink:
        raise ValueError('source and sink must differ')
    if not (0 <= source < node_count and 0 <= sink < node_count):
        raise ValueError('source or sink outside graph')
    if cutoff is not None and cutoff <= 0:
        return 0

    # Arc i and i^1 are reverse residual edges, as in the credited source.
    adjacency = [[] for _ in range(node_count)]
    head = []
    residual = []
    for u, v, capacity in edges:
        if not (0 <= u < node_count and 0 <= v < node_count) or capacity < 0:
            raise ValueError('invalid edge or negative capacity')
        adjacency[u].append(len(head))
        head.append(v)
        residual.append(capacity)
        adjacency[v].append(len(head))
        head.append(u)
        residual.append(0)

    flow = 0
    while cutoff is None or flow < cutoff:
        level = [-1] * node_count
        level[source] = 0
        queue = deque([source])
        while queue:
            u = queue.popleft()
            for arc in adjacency[u]:
                v = head[arc]
                if residual[arc] > 0 and level[v] < 0:
                    level[v] = level[u] + 1
                    queue.append(v)
        if level[sink] < 0:
            break

        next_arc = [0] * node_count
        path = []
        u = source
        # Non-recursive DFS through the level graph (adapted from source).
        while cutoff is None or flow < cutoff:
            if u == sink:
                delta = min(residual[arc] for arc in path)
                if cutoff is not None:
                    delta = min(delta, cutoff - flow)
                for arc in path:
                    residual[arc] -= delta
                    residual[arc ^ 1] += delta
                flow += delta
                path.clear()
                u = source
            elif next_arc[u] < len(adjacency[u]):
                arc = adjacency[u][next_arc[u]]
                v = head[arc]
                if residual[arc] > 0 and level[v] == level[u] + 1:
                    path.append(arc)
                    u = v
                else:
                    next_arc[u] += 1
            elif u == source:
                break
            else:
                arc = path.pop()
                u = head[arc ^ 1]
                next_arc[u] += 1
    return flow

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
