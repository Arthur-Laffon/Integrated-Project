"""Regression coverage for conflict-guided joint time/section LNS (v5.7)."""
from __future__ import annotations

import random
import time
import unittest
from collections import Counter

from timetable_csv import (
    Config, Request, _PupilFeasibilityPropagator,
    _try_joint_repair, compulsory_section_diagnostics,
    exact_repair_neighborhood, relaxed_compulsory_sectioning,
    request_statistics,
)
from tests.test_joint_propagation import artificial
from tests import test_repair


class JointLNSV57Tests(unittest.TestCase):
    def test_relaxation_exposes_globally_incompatible_mandatory_requests(self):
        students = ['S1', 'S2']
        inst = artificial(
            students, {'S1': set(), 'S2': set()},
            {'A': 'X_A', 'B': 'Y_B'},
            [Request(s, f, True, 1) for s in students for f in ('X', 'Y')],
            {'X_A': 2, 'Y_B': 2},
        )
        phi = {'A': 0, 'B': 0}
        diag = compulsory_section_diagnostics(inst, phi)
        self.assertEqual(diag['zero_requests'], 0)
        self.assertEqual(diag['combination_failures'], 2)
        relaxed = relaxed_compulsory_sectioning(inst, phi, .5)
        self.assertIsNotNone(relaxed)
        self.assertEqual(relaxed['total'], 4)
        self.assertEqual(relaxed['fulfilled'], 2)
        self.assertEqual(len(relaxed['unmet']), 2)

    def test_repair_excludes_original_failed_coloring(self):
        fixture = test_repair.RepairTests()
        inst, rooms = fixture.make_instance()
        try:
            failed_phi = {'CORE': 0, 'F1': 0}
            candidate, status = exact_repair_neighborhood(
                inst, rooms, failed_phi, {'F1'}, {'S'},
                seconds=1.5, require_change=True, backend='scipy')
            self.assertIsNotNone(candidate, status)
            self.assertEqual(candidate['F1'], 1)
        finally:
            fixture.tearDown()

    def test_joint_lns_finds_complete_valid_repair(self):
        fixture = test_repair.RepairTests()
        inst, rooms = fixture.make_instance()
        try:
            cfg = Config(section_seconds=.5, joint_lns_step_seconds=.7)
            diags = {'repair_attempts': 0, 'repair_statuses': Counter(),
                     'repair_success': 0}
            ev = _try_joint_repair(inst, rooms, {'CORE': 0, 'F1': 0},
                                   cfg, random.Random(17),
                                   request_statistics(inst),
                                   time.perf_counter() + 2, diags)
            self.assertIsNotNone(ev)
            self.assertEqual(ev['phi']['F1'], 1)
            self.assertEqual(ev['sectioning']['assignment']['S']['F'], 'F_A')
            self.assertEqual(diags['joint_initial_unmet'], 1)
            self.assertEqual(diags['repair_success'], 1)
        finally:
            fixture.tearDown()

    def test_occupied_seats_are_reserved_by_joint_milp(self):
        fixture = test_repair.RepairTests()
        inst, rooms = fixture.make_instance()
        try:
            # Another pupil has a reserved seat in this capacity-one section.
            cand, status = exact_repair_neighborhood(
                inst, rooms, {'CORE': 0, 'F1': 0}, {'F1'}, {'S'},
                seconds=.5, backend='scipy', require_change=True,
                section_reservations={'F_A': 1})
            self.assertIsNone(cand)
            self.assertIn(status, {'SCIPY_INFEASIBLE_LOCAL',
                                   'SECTION_CAPACITY_EXHAUSTED', 'SCIPY_UNKNOWN'})
        finally:
            fixture.tearDown()


if __name__ == '__main__':
    unittest.main()
