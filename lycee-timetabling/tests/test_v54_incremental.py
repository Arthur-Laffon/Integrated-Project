"""v5.4 regression tests for cached witnesses, incremental MRV and seed LNS."""
import random
import unittest
from collections import Counter
from pathlib import Path

from timetable_csv import (
    _PupilFeasibilityPropagator, _ConstructState, Config, hard_adjacency,
    load_csv, optimized_section_seed, request_statistics,
)

ROOT = Path(__file__).resolve().parents[1]


class IncrementalWitnessTests(unittest.TestCase):
    def test_cached_witness_matches_full_recomputation_with_rollback(self):
        inst, _ = load_csv(ROOT / 'benchmarks' / 'mixed_5.csv')
        fast = _PupilFeasibilityPropagator(inst, matching_interval=0, incremental=True)
        slow = _PupilFeasibilityPropagator(inst, matching_interval=0, incremental=False)
        rng = random.Random(37)
        scheduled = []
        for _ in range(220):
            if scheduled and rng.random() < .32:
                scheduled.pop()
                fast.pop()
                slow.pop()
            else:
                c = rng.choice(inst.courses)
                t = rng.choice(tuple(inst.allowed_slots(c)))
                af = fast.push(c, t, len(scheduled)+1)
                as_ = slow.push(c, t, len(scheduled)+1)
                self.assertEqual(af, as_, (c, t, len(scheduled)))
                if af:
                    scheduled.append((c, t))
            for s in rng.sample(list(inst.students), min(5, len(inst.students))):
                self.assertEqual(fast.pupil_possible(s), slow.pupil_possible(s))
        while scheduled:
            scheduled.pop()
            fast.pop()
            slow.pop()
        self.assertEqual(fast.fixed_mask, slow.fixed_mask)
        self.assertEqual(fast.section_mask, slow.section_mask)

    def test_incremental_heap_keeps_rejected_course_available(self):
        inst, rooms = load_csv(ROOT / 'benchmarks' / 'small_5.csv')
        cfg = Config()
        state = _ConstructState(inst, rooms, random.Random(11),
                                hard_adjacency(inst), request_statistics(inst),
                                None, cfg)
        c = state.choose()
        # Rejection at the initial domain check must not remove the lesson
        # from the heap (and cause a false completion later).
        self.assertIsNone(state.place(c, inst.T + 1))
        self.assertEqual(state.choose(), c)
        for t in state.ordered_times(c):
            changes = state.place(c, t)
            if changes is not None:
                state.unplace(c, t, changes)
                self.assertEqual(state.choose(), c)
                break
        else:
            self.fail('expected one legal candidate in small benchmark')

    def test_seed_lns_preserves_capacities_and_never_worsens_base_edge_count(self):
        inst, _ = load_csv(ROOT / 'benchmarks' / 'mixed_5.csv')
        metrics = {}
        seed = optimized_section_seed(inst, random.Random(2026), .25,
                                      lns=True, lns_seconds=.25, metrics=metrics)
        self.assertGreaterEqual(metrics['lns_attempts'], 1)
        self.assertLessEqual(metrics['edge_count_final'], metrics['edge_count_initial'])
        loads = Counter()
        for r in inst.requests:
            if not r.required:
                continue
            q = seed[r.student][r.family]
            loads[q] += 1
            if r.locked_section:
                self.assertEqual(q, r.locked_section)
        for q, load in loads.items():
            self.assertLessEqual(load, inst.section_capacity[q])


if __name__ == '__main__':
    unittest.main()
