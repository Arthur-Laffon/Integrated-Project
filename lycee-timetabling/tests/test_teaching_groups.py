import csv
import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import timetable_csv as solver
import generate_lycee_csv as generator
import validate_timetable_csv as validator


class StudentGroupsTest(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.p = Path(self.td.name) / 'school.csv'
        generator.build(str(self.p), cohorts=3, seed=2026, professor_availability=1.0,
                        language_diversity=0.0, specialities=('MATHS_SPE','PHYS_SPE','SES_SPE','HGGSP'))

    def rows(self):
        with self.p.open(newline='',encoding='utf-8') as f:
            reader=csv.DictReader(f)
            return list(reader.fieldnames),list(reader)

    def write(self,fields,rows):
        with self.p.open('w',newline='',encoding='utf-8') as f:
            writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader();writer.writerows(rows)

    def test_membership_drives_attendance(self):
        inst,rooms=solver.load_csv(self.p)
        self.assertTrue(inst.group_info)
        for student in inst.students:
            for typ in ('LVA','LVB','EPS'):
                self.assertEqual(sum(typ==inst.group_info[g]['group_type'] and student in members
                                     for g,members in inst.group_members.items()),1)
        some=next(r for r in inst.courses if inst.group_info.get(inst.group_of.get(r),{}).get('group_type')=='LVA')
        self.assertEqual(inst._fixed_attendees[some], inst.group_members[inst.group_of[some]])

    def test_all_offered_triples_eligible(self):
        triples=set()
        for seed in range(80):
            import random
            triples.add(tuple(sorted(generator.choose_pathway(random.Random(seed), ('MATHS_SPE','PHYS_SPE','SES_SPE','HGGSP')))))
        self.assertEqual(len(triples),4)

    def test_duplicate_membership_rejected(self):
        fields,rows=self.rows()
        member=next(r for r in rows if r['kind']=='membership')
        rows.append(dict(member))
        self.write(fields,rows)
        with self.assertRaisesRegex(ValueError,'duplicate membership'):
            solver.load_csv(self.p)

    def test_unknown_group_rejected(self):
        fields,rows=self.rows()
        member=next(r for r in rows if r['kind']=='membership')
        member['group_id']='DOES_NOT_EXIST'
        self.write(fields,rows)
        with self.assertRaisesRegex(ValueError,'unknown member group'):
            solver.load_csv(self.p)

    def test_too_many_pupils_rejected(self):
        fields,rows=self.rows()
        group=next(r for r in rows if r['kind']=='group' and r['group_type']=='common')
        group['capacity']='1'
        self.write(fields,rows)
        with self.assertRaisesRegex(ValueError,'exceed declared capacity'):
            solver.load_csv(self.p)

    def test_legacy_conversion_preserves_exact_attendance(self):
        from flatten_groups import flatten
        legacy=Path(self.td.name)/'flat.csv'
        flatten(self.p,legacy)
        inst,_=solver.load_csv(self.p)
        converted,_=solver.load_csv(legacy)
        self.assertEqual(inst._fixed_courses, converted._fixed_courses)
        self.assertEqual(set(inst.department),set(converted.department))


if __name__ == '__main__':
    unittest.main()

# The original input's fixed group rosters must match exported pupil lessons.
# This test uses a checked-in solved example, not an assumption from the solver.
class IndependentStudentValidationTest(unittest.TestCase):
    def test_missing_fixed_group_lesson_is_rejected(self):
        source=ROOT/'examples/french6_4.csv'
        schedule=ROOT/'examples/french6_4_out.csv'
        student_file=ROOT/'examples/french6_4_students.csv'
        if not all(p.exists() for p in (source,schedule,student_file)):
            self.skipTest('example output not packaged')
        with tempfile.TemporaryDirectory() as td:
            bad=Path(td)/'bad_students.csv'
            with student_file.open(newline='',encoding='utf-8') as f:
                reader=csv.DictReader(f);fields=list(reader.fieldnames);rows=list(reader)
            fixed=next(r for r in rows if not r['section'])
            self.assertTrue(fixed)
            removed=False
            with bad.open('w',newline='',encoding='utf-8') as f:
                writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader()
                for r in rows:
                    if not removed and r['student']==fixed['student'] and r['course']==fixed['course']:
                        removed=True;continue
                    writer.writerow(r)
            check=validator.validate(str(source),str(schedule),str(ROOT/'timetable_csv.py'),str(bad))
            self.assertFalse(check['valid'])
            self.assertTrue(any('course list mismatch' in e for e in check['errors']))
