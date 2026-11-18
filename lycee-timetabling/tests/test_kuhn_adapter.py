"""Independent tests for the MIT-licensed iterative Kuhn adapter."""
import random
import unittest

from algorithms.bipartite_matching import has_full_bipartite_matching


def brute_feasible(neighbors, count):
    used = set()

    def recurse(i):
        if i == len(neighbors):
            return True
        for r in neighbors[i]:
            if r not in used:
                used.add(r)
                if recurse(i + 1):
                    return True
                used.remove(r)
        return False

    return recurse(0)


class KuhnAdapterTests(unittest.TestCase):
    def test_augmenting_path(self):
        self.assertTrue(has_full_bipartite_matching([[0, 1], [0]], 2))
        self.assertFalse(has_full_bipartite_matching([[0], [0]], 2))

    def test_random_against_enumeration(self):
        rng = random.Random(3109)
        for _ in range(300):
            n_left, n_right = rng.randrange(8), rng.randrange(8)
            choices = [[r for r in range(n_right) if rng.randrange(3)]
                       for _ in range(n_left)]
            self.assertEqual(has_full_bipartite_matching(choices, n_right),
                             brute_feasible(choices, n_right))

    def test_long_alternating_chain_without_recursion(self):
        n = 1200
        choices = [[i, i + 1] for i in range(n - 1)] + [[0]]
        self.assertTrue(has_full_bipartite_matching(choices, n))


if __name__ == '__main__':
    unittest.main()
