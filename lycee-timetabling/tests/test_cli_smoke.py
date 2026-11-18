from __future__ import annotations
import csv
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

class CLISmokeTest(unittest.TestCase):
    def test_example_solves_and_validates(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            timetable = td / 'timetable.csv'
            students = td / 'students.csv'
            source = ROOT / 'examples' / 'linked_courses.csv'
            a = subprocess.run([
                sys.executable, str(ROOT / 'timetable_csv.py'), str(source), str(timetable),
                '--students-output', str(students), '--slots', '8', '--slots-per-day', '4',
                '--time-limit', '6', '--local-seconds', '1', '--seed', '2026',
            ], capture_output=True, text=True, timeout=35)
            self.assertEqual(a.returncode, 0, a.stdout + '\n' + a.stderr)
            self.assertTrue(timetable.exists())
            self.assertTrue(students.exists())
            b = subprocess.run([
                sys.executable, str(ROOT / 'validate_timetable_csv.py'), str(source),
                str(timetable), '--students-output', str(students),
                '--slots', '8', '--slots-per-day', '4',
            ], capture_output=True, text=True, timeout=20)
            self.assertEqual(b.returncode, 0, b.stdout + '\n' + b.stderr)
            self.assertIn('valid=True', b.stdout)

if __name__ == '__main__':
    unittest.main()
