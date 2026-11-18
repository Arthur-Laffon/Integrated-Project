"""Regression/oracle tests for the MIT-licensed Dinic adapter."""
from __future__ import annotations

import random
import unittest
from collections import Counter

from algorithms.max_flow import dinic_max_flow
from timetable_csv import _PupilFeasibilityPropagator


def brute_cut_value(n, edges, source, sink):
    other = [v for v in range(n) if v not in (source, sink)]
    return min(
        sum(cap for u, v, cap in edges if u in side and v not in side)
        for mask in range(1 << len(other))
        for side in [set([source]) | {other[i] for i in range(len(other)) if mask >> i & 1}]
    )


def brute_section_assignment(groups, capacities):
    people = [options for options, count in groups.items() for _ in range(count)]
    available = dict(capacities)

    def assign(i):
        if i == len(people):
            return True
        for q in people[i]:
            if available.get(q, 0) > 0:
                available[q] -= 1
                if assign(i + 1):
                    return True
                available[q] += 1
        return False

    return assign(0)


class ExternalDinicTests(unittest.TestCase):
    def test_known_flow_and_cutoff(self):
        edges = [(0, 1, 10), (0, 2, 10), (1, 2, 2),
                 (1, 3, 8), (2, 3, 9), (3, 4, 20)]
        self.assertEqual(dinic_max_flow(5, edges, 0, 4), 17)
        self.assertEqual(dinic_max_flow(5, edges, 0, 4, cutoff=6), 6)
        self.assertEqual(dinic_max_flow(5, edges, 0, 4, cutoff=100), 17)

    def test_random_small_graphs_vs_all_min_cuts(self):
        rng = random.Random(47825)
        for _ in range(250):
            n = rng.randint(2, 6)
            edges = [(rng.randrange(n), rng.randrange(n), rng.randrange(5))
                     for _ in range(rng.randrange(14))]
            source, sink = rng.sample(range(n), 2)
            exact = brute_cut_value(n, edges, source, sink)
            self.assertEqual(dinic_max_flow(n, edges, source, sink), exact)
            self.assertEqual(dinic_max_flow(n, edges, source, sink, cutoff=2), min(2, exact))

    def test_random_section_capacity_networks_vs_bruteforce(self):
        rng = random.Random(9192)
        for _ in range(220):
            n_sections = rng.randint(1, 4)
            caps = {f'S{i}': rng.randrange(4) for i in range(n_sections)}
            groups = Counter()
            for _ in range(rng.randrange(7)):
                opts = tuple(q for q in caps if rng.randrange(2))
                groups[opts] += 1
            self.assertEqual(_PupilFeasibilityPropagator._flow_feasible(groups, caps),
                             brute_section_assignment(groups, caps))

    def test_source_sink_errors(self):
        with self.assertRaises(ValueError):
            dinic_max_flow(2, [], 0, 0)
        with self.assertRaises(ValueError):
            dinic_max_flow(2, [(0, 1, -1)], 0, 1)


if __name__ == '__main__':
    unittest.main()
