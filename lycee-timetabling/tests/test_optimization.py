import random
import unittest
from collections import defaultdict
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from timetable_csv import _gap_value, load_csv, hard_adjacency, seed_section_assignment


class OptimizationInvariantTests(unittest.TestCase):
    def test_bitset_gap_equals_reference(self):
        rng = random.Random(4321)
        for spd in (4, 8, 10):
            for _ in range(600):
                slots = rng.choices(range(spd * 5), k=rng.randrange(60))
                groups = defaultdict(set)
                for t in slots:
                    groups[t // spd].add(t % spd)
                reference = sum(max(group) - min(group) + 1 - len(group)
                                for group in groups.values() if group)
                self.assertEqual(_gap_value(slots, spd), reference)

    def test_affinity_seed_preserves_required_sections(self):
        root = Path(__file__).resolve().parents[1]
        inst, _ = load_csv(root / 'benchmarks' / 'mixed_4_90pct.csv')
        seed = seed_section_assignment(inst, random.Random(2026), 'affinity')
        self.assertIsNotNone(seed)
        capacity = defaultdict(int)
        for request in inst.requests:
            if not request.required:
                continue
            sec = seed[request.student][request.family]
            self.assertIn(sec, inst.family_sections(request.family))
            capacity[sec] += 1
        for sec, n in capacity.items():
            self.assertLessEqual(n, inst.section_capacity[sec])

    def test_affinity_can_reduce_provisional_conflicts(self):
        root = Path(__file__).resolve().parents[1]
        inst, _ = load_csv(root / 'benchmarks' / 'mixed_4_90pct.csv')
        affinity = seed_section_assignment(inst, random.Random(2026), 'affinity')
        random_seed = seed_section_assignment(inst, random.Random(2026), 'random')
        affinity_edges = sum(len(xs) for xs in hard_adjacency(inst, affinity).values())
        random_edges = sum(len(xs) for xs in hard_adjacency(inst, random_seed).values())
        self.assertLess(affinity_edges, random_edges)


if __name__ == '__main__':
    unittest.main()

class StudentSwapTests(unittest.TestCase):
    def test_two_full_sections_can_exchange_members(self):
        import time
        from timetable_csv import Instance, Request, Config, improve_student_section_swaps
        students = ('S1', 'S2')
        courses = ['FIX1', 'FIX2', 'A1', 'B1']
        inst = Instance(
            T=8, slots_per_day=8,
            department={c: '' for c in courses},
            teacher={c: c for c in courses},
            subject={c: c for c in courses},
            required_equipment={c: set() for c in courses},
            section_of={'FIX1': None, 'FIX2': None, 'A1': 'A', 'B1': 'B'},
            hard_group={c: False for c in courses},
            explicit_size={c: 1 for c in courses},
            prof_avail={c: set(range(8)) for c in courses},
            scores={}, links=(), students=students,
            home_class={'S1': 'H1', 'S2': 'H2'},
            extra_fixed_courses={'S1': {'FIX1'}, 'S2': {'FIX2'}},
            requests=(Request('S1','F',True,1.0), Request('S2','F',True,1.0)),
            section_family={'A':'F', 'B':'F'},
            section_capacity={'A':1, 'B':1}, teacher_pref={},
            lock_time={},lock_room={})
        phi={'FIX1':6, 'FIX2':1, 'A1':0, 'B1':7}
        sec={'assignment':{'S1':{'F':'A'}, 'S2':{'F':'B'}},
             'loads':{'A':1,'B':1},'optional_score':0.0,
             'optimal':True,'refinements':0}
        revised, swaps = improve_student_section_swaps(
            inst,phi,sec,Config(),time.perf_counter()+0.5)
        self.assertEqual(swaps,1)
        self.assertEqual(revised['assignment']['S1']['F'],'B')
        self.assertEqual(revised['assignment']['S2']['F'],'A')
        self.assertEqual(revised['loads'],sec['loads'])
        self.assertEqual(sec['assignment']['S1']['F'],'A')
