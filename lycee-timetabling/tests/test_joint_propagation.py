"""Targeted correctness tests for v5.3's A (safe pruning) and D (seeding)."""
import random
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from timetable_csv import (Instance, Request, _PupilFeasibilityPropagator,
                           hard_adjacency, load_csv, optimized_section_seed,
                           seed_section_assignment)
from validate_timetable_csv import parse_output
from benchmarks.generate_planted_feasible import build

ROOT = Path(__file__).resolve().parents[1]


def artificial(students, fixed, sections, requests, capacities):
    courses = sorted(set().union(*fixed.values())) + list(sections)
    return Instance(
        T=4, slots_per_day=4,
        department={c: '' for c in courses},
        teacher={c: c for c in courses},
        subject={c: c for c in courses},
        required_equipment={c: set() for c in courses},
        section_of={c: sections.get(c) for c in courses},
        hard_group={c: False for c in courses},
        explicit_size={c: 1 for c in courses},
        prof_avail={c: {0, 1, 2, 3} for c in courses},
        scores={}, links=(), students=tuple(students),
        home_class={s: 'H' for s in students},
        extra_fixed_courses={s: set(fixed.get(s, ())) for s in students},
        requests=tuple(requests),
        section_family={sec: sec.split('_')[0] for sec in set(sections.values())},
        section_capacity=capacities, teacher_pref={}, lock_time={}, lock_room={})


class PropagationTests(unittest.TestCase):
    def test_disallows_last_compulsory_section(self):
        inst = artificial(['S'], {'S': {'F'}}, {'A': 'X_A', 'B': 'X_B'},
                          [Request('S', 'X', True, 1)], {'X_A': 1, 'X_B': 1})
        # Both individual section options become blocked by the fixed lesson.
        p = _PupilFeasibilityPropagator(inst, 0)
        self.assertTrue(p.push('F', 0, 1))
        self.assertTrue(p.push('A', 0, 2))
        self.assertFalse(p.push('B', 0, 3))
        self.assertEqual(p.section_mask['X_B'], 0)  # failed push reverted
        p.pop(); p.pop()
        self.assertEqual(p.fixed_mask['S'], 0)

    def test_detects_incompatible_combination(self):
        inst = artificial(['S'], {}, {'A': 'X_A', 'B': 'Y_B'},
                          [Request('S', 'X', True, 1), Request('S', 'Y', True, 1)],
                          {'X_A': 1, 'Y_B': 1})
        p = _PupilFeasibilityPropagator(inst, 0)
        self.assertTrue(p.push('A', 1, 1))
        self.assertFalse(p.push('B', 1, 2))
        self.assertTrue(p.pupil_possible('S'))
        p.pop()

    def test_capacity_hall_violation_not_visible_per_student(self):
        inst = artificial(['S1', 'S2'],
                          {'S1': {'F'}, 'S2': {'F'}},
                          {'A': 'X_A', 'B': 'X_B'},
                          [Request('S1','X',True,1), Request('S2','X',True,1)],
                          {'X_A': 1, 'X_B': 1})
        p = _PupilFeasibilityPropagator(inst, 0)
        self.assertTrue(p.push('F', 0, 1))
        self.assertTrue(p.push('A', 0, 2))
        self.assertTrue(all(p.pupil_possible(s) for s in inst.students))
        self.assertFalse(p.capacity_possible())
        p.pop(); p.pop()
        self.assertTrue(p.capacity_possible())

    def test_never_rejects_known_valid_five_specialty_timetable(self):
        # Generate a fresh five-specialty witness rather than retaining
        # output from an earlier solver version in this minimal package.
        with tempfile.TemporaryDirectory() as tmp:
            details = build(Path(tmp), cohorts=6, specialties=5, seed=2026)
            inst, _ = load_csv(Path(tmp) / details['files']['input'])
            phi, _, _, _, errors = parse_output(
                Path(tmp) / details['files']['witness_timetable'], inst.T)
        self.assertFalse(errors)
        self.assertEqual(len(phi), len(inst.courses))
        p = _PupilFeasibilityPropagator(inst, 64)
        for depth, c in enumerate(inst.courses, 1):
            self.assertTrue(p.push(c, phi[c], depth), (c, depth))
        self.assertTrue(p.capacity_possible())
        for _ in inst.courses:
            p.pop()
        self.assertTrue(all(not bits for bits in p.fixed_mask.values()))
        self.assertTrue(all(not bits for bits in p.section_mask.values()))


class OptimizedSeedTests(unittest.TestCase):
    def test_capacity_lock_and_edge_improvement(self):
        inst, _ = load_csv(ROOT / 'benchmarks' / 'mixed_5.csv')
        optimized = optimized_section_seed(inst, random.Random(2026), .5)
        baseline = seed_section_assignment(inst, random.Random(2026), 'affinity')
        self.assertIsNotNone(optimized)
        loads = Counter()
        for r in inst.requests:
            if not r.required:
                continue
            sec = optimized[r.student][r.family]
            self.assertIn(sec, inst.family_sections(r.family))
            if r.locked_section:
                self.assertEqual(sec, r.locked_section)
            loads[sec] += 1
        self.assertTrue(all(loads[s] <= inst.section_capacity[s] for s in loads))
        def edges(a):
            return sum(len(x) for x in hard_adjacency(inst, a).values()) // 2
        self.assertLessEqual(edges(optimized), edges(baseline))


if __name__ == '__main__':
    unittest.main()
