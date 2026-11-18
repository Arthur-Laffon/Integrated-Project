"""Tests that known-feasible examples really come with valid witnesses."""
from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'benchmarks'))
from generate_planted_feasible import build
from validate_timetable_csv import validate


class PlantedGeneratorTests(unittest.TestCase):
    def test_witness_four_and_five_specialties(self):
        for specialties in (4, 5):
            with self.subTest(specialties=specialties), tempfile.TemporaryDirectory() as temp:
                result = build(Path(temp), cohorts=6, specialties=specialties,
                               seed=31, class_size=12, section_capacity=12,
                               group_capacity=12, teacher_availability=0.8)
                self.assertEqual(result['status'], 'PLANTED_FEASIBLE')
                self.assertTrue(result['validation']['valid'])
                self.assertEqual(result['mandatory_requests'], 12 * 6 * 5 // 3)
                input_file = Path(temp) / result['files']['input']
                with input_file.open(encoding='utf-8', newline='') as f:
                    rows = list(csv.DictReader(f))
                self.assertFalse(any(r['kind'] == 'lock' for r in rows))
                self.assertFalse(any(r['kind'] == 'request' and r['locked_section'] for r in rows))
                self.assertEqual(sum(r['kind'] == 'course' for r in rows), result['lessons'])

    def test_six_specialties_with_reduced_teacher_availability(self):
        with tempfile.TemporaryDirectory() as temp:
            result = build(Path(temp), cohorts=6, specialties=6, seed=2026,
                           class_size=12, section_capacity=12,
                           group_capacity=12, teacher_availability=0.60)
            self.assertTrue(result['validation']['valid'])
            self.assertEqual(result['offered_specialties'][-1], 'NSI')
            self.assertEqual(result['effective_teacher_availability_fraction'], .60)
            with (Path(temp) / result['files']['input']).open(encoding='utf-8', newline='') as f:
                rows = list(csv.DictReader(f))
            courses = [r for r in rows if r['kind'] == 'course']
            self.assertTrue(any(r['subject'] == 'NSI' for r in courses))
            professors = [r for r in rows if r['kind'] == 'professor']
            self.assertTrue(professors)
            self.assertTrue(all(len(r['available_slots'].split(';')) == 24 for r in professors))
            self.assertFalse(any(r['kind'] == 'request' and r['locked_section'] for r in rows))

    def test_reproducible_generation(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            ra = build(Path(a), cohorts=6, specialties=5, seed=4242,
                       class_size=12, section_capacity=12, group_capacity=12)
            rb = build(Path(b), cohorts=6, specialties=5, seed=4242,
                       class_size=12, section_capacity=12, group_capacity=12)
            for key in ('input', 'witness_timetable', 'witness_students'):
                self.assertEqual((Path(a) / ra['files'][key]).read_bytes(),
                                 (Path(b) / rb['files'][key]).read_bytes())

    def test_independent_validator_detects_corrupted_witness(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            r = build(folder, cohorts=6, specialties=4, seed=51,
                      class_size=12, section_capacity=12, group_capacity=12,
                      chronology_rate=0.10)
            source = folder / r['files']['input']
            timetable = folder / r['files']['witness_timetable']
            students = folder / r['files']['witness_students']
            with timetable.open(encoding='utf-8', newline='') as f:
                rows = list(csv.DictReader(f))
            # Drop a scheduled course; the resulting witness MUST fail validation.
            for row in rows:
                if row['assignments']:
                    row['assignments'] = '; '.join(row['assignments'].split('; ')[1:])
                    break
            corrupted = folder / 'corrupt_timetable.csv'
            with corrupted.open('w', encoding='utf-8', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=['slot_index', 'timeslot', 'assignments'])
                writer.writeheader()
                writer.writerows(rows)
            validation = validate(source, corrupted, ROOT / 'timetable_csv.py', students)
            self.assertFalse(validation['valid'])
            self.assertTrue(any('lesson set mismatch' in e for e in validation['errors']))

    def test_input_guard(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(ValueError):
                build(Path(temp), cohorts=2)
            with self.assertRaises(ValueError):
                build(Path(temp), cohorts=6, teacher_availability=0.1)


if __name__ == '__main__':
    unittest.main()
