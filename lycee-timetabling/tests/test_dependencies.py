from __future__ import annotations
import csv
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import timetable_csv as solver
import validate_timetable_csv as checker

COLUMNS = ['kind','id','department','professor','subject','available_slots','equipment','allowed_subjects','required_equipment','capacity','room_type','student_count','section','family','section_capacity','hard_group','student_id','home_class','fixed_courses','required','weight','locked_section','slots','target_course','from_course','to_course','from_family','to_family','min_gap','max_gap','same_day','slot','room']

def fixture(path, c_slot=3, b_capacity=1, fixed_source=False):
    rows = []
    for subj,slot in [('CORE',0),('A',1),('B',2),('C',c_slot),('D',4)]:
        r = {'kind':'course','id':f'{subj}1','professor':f'P{subj}','subject':subj}
        if subj=='CORE':
            r.update(department='H',student_count='2',hard_group='true')
        else:
            r.update(section=subj+'SECTION',family=subj,section_capacity=str(b_capacity if subj=='B' else 2),hard_group='false')
        rows.append(r)
        rows.append({'kind':'professor','id':f'P{subj}','available_slots':str(slot)})
    rows.append({'kind':'room','id':'R1','capacity':'3','available_slots':'*'})
    rows.append({'kind':'room','id':'R2','capacity':'3','available_slots':'*'})
    rows.extend([{'kind':'student','id':x,'home_class':'H'} for x in ['S1','S2']])
    rows.append({'kind':'request','student_id':'S1','family':'A','required':'true'})
    rows.append({'kind':'request','student_id':'S2','family':'A','required':'false','weight':'100'})
    rows.extend([
        {'kind':'dependency','from_family':'A','to_family':'B','required':'true'},
        {'kind':'dependency','from_family':'B','to_family':'D','required':'true'},
        {'kind':'dependency','from_family':'A','to_family':'C','required':'false','weight':'5'},
    ])
    if fixed_source:
        rows.append({'kind':'dependency','from_course':'CORE1','to_family':'B','required':'true'})
    with open(path,'w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=COLUMNS)
        w.writeheader();w.writerows(rows)
    return rows

class DependencyTests(unittest.TestCase):
    def run_case(self, **kw):
        td = tempfile.TemporaryDirectory()
        base = Path(td.name)
        inp,out,student = [base/s for s in ('input.csv','out.csv','students.csv')]
        fixture(inp, **kw)
        inst,rooms=solver.load_csv(inp,T=8,slots_per_day=4)
        result=solver.solve(inst,rooms,solver.Config(time_limit=5, local_seconds=0.0, section_seconds=1.0, seed=1, max_feasible_starts=1, room_day_seconds=0))
        self.assertIsNotNone(result['best'],result)
        solver.save_csv(inst,result,out)
        solver.save_student_csv(inst,result,student)
        rep=checker.validate(inp,out,str(ROOT/'timetable_csv.py'),student,slots=8,slots_per_day=4)
        self.assertTrue(rep['valid'],rep['errors'])
        with open(student, newline='',encoding='utf-8') as f:
            records=list(csv.DictReader(f))
        memberships={s:{r['subject'] for r in records if r['student']==s} for s in ('S1','S2')}
        return td, inp, out, student, inst, memberships

    def test_mandatory_chain_and_optional_target(self):
        td,_,_,_,inst,m=self.run_case()
        try:
            self.assertTrue({'CORE','A','B','D','C'} <= m['S1'])
            self.assertNotIn('A',m['S2'])
            self.assertNotIn('B',m['S2'])
            self.assertNotIn('C',m['S2'])
            self.assertEqual(len(inst.dependencies),3)
        finally:
            td.cleanup()

    def test_optional_target_cannot_break_a_conflict(self):
        td,_,_,_,_,m=self.run_case(c_slot=0)
        try:
            self.assertTrue({'CORE','A','B','D'} <= m['S1'])
            self.assertNotIn('C',m['S1'])
        finally:
            td.cleanup()

    def test_fixed_course_activates_dependency(self):
        td,_,_,_,inst,m=self.run_case(fixed_source=True,b_capacity=2)
        try:
            self.assertIn('B',m['S1'])
            self.assertIn('B',m['S2'])
            self.assertIn('D',m['S2'])
            self.assertIn('CORE',m['S2'])
        finally:
            td.cleanup()

    def test_validator_rejects_missing_mandatory_link(self):
        td,inp,out,students,_,_ = self.run_case()
        try:
            with open(students,newline='',encoding='utf-8') as f:
                rows=list(csv.DictReader(f));cols=list(rows[0])
            with open(students,'w',newline='',encoding='utf-8') as f:
                w=csv.DictWriter(f,fieldnames=cols);w.writeheader();w.writerows(r for r in rows if not (r['student']=='S1' and r['subject']=='B'))
            report=checker.validate(inp,out,str(ROOT/'timetable_csv.py'),students,slots=8,slots_per_day=4)
            self.assertFalse(report['valid'])
            self.assertTrue(any('mandatory linked' in e for e in report['errors']))
        finally:
            td.cleanup()

    def test_optional_bonus_in_addition_to_existing_request(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'input.csv'
            rows=fixture(p)
            rows.append({'kind':'request','student_id':'S1','family':'C','required':'false','weight':'7'})
            with p.open('w',newline='',encoding='utf-8') as f:
                w=csv.DictWriter(f,fieldnames=COLUMNS);w.writeheader();w.writerows(rows)
            inst,rooms=solver.load_csv(p,8,4)
            phi={c:{'CORE1':0,'A1':1,'B1':2,'C1':3,'D1':4}[c] for c in inst.courses}
            sectioning=solver.solve_sectioning(inst,phi,1.0,solver.Config())
            self.assertIsNotNone(sectioning)
            self.assertIn('C',sectioning['assignment']['S1'])
            self.assertAlmostEqual(sectioning['optional_score'],12.0)

    def test_validation_rejects_unknown_family(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'bad.csv';rows=fixture(p);rows.append({'kind':'dependency','from_family':'A','to_family':'DOES_NOT_EXIST','required':'true'})
            with open(p,'w',newline='',encoding='utf-8') as f:
                w=csv.DictWriter(f,fieldnames=COLUMNS);w.writeheader();w.writerows(rows)
            with self.assertRaisesRegex(ValueError,'unknown target family'):
                solver.load_csv(p,8,4)

if __name__=='__main__':
    unittest.main()
