import csv
import tempfile
import unittest
from pathlib import Path
import timetable_csv as s

FIELDS = ['kind','id','department','professor','subject','available_slots','capacity','student_count','section','family','section_capacity','hard_group','student_id','home_class','required']

class RepairTests(unittest.TestCase):
    def make_instance(self, restrictive=False):
        rows = [
            dict(kind='course',id='CORE',department='H',professor='P0',subject='CORE',student_count='1',hard_group='true'),
            dict(kind='professor',id='P0',available_slots='0'),
            dict(kind='course',id='F1',professor='P1',subject='F',section='F_A',family='F',section_capacity='1',hard_group='false'),
            dict(kind='professor',id='P1',available_slots='0' if restrictive else '0;1'),
            dict(kind='room',id='R1',available_slots='*',capacity='5'),
            dict(kind='room',id='R2',available_slots='*',capacity='5'),
            dict(kind='student',id='S',home_class='H'),
            dict(kind='request',student_id='S',family='F',required='true'),
        ]
        self.tmp = tempfile.TemporaryDirectory()
        path = Path(self.tmp.name)/'school.csv'
        with path.open('w',newline='',encoding='utf8') as fp:
            w=csv.DictWriter(fp,FIELDS);w.writeheader();w.writerows(rows)
        return s.load_csv(path,T=4,slots_per_day=4)

    def tearDown(self):
        if hasattr(self,'tmp'):self.tmp.cleanup()

    def test_joint_repairs_section_infeasibility(self):
        inst,rooms = self.make_instance()
        phi={'CORE':0,'F1':0}
        self.assertIsNone(s.solve_sectioning(inst,phi,.1))
        recovered,status=s.exact_repair_neighborhood(inst,rooms,phi,{'F1'},{'S'},3.,'auto')
        self.assertIsNotNone(recovered,status)
        self.assertEqual(recovered['F1'],1)
        ev=s.evaluate(inst,rooms,recovered,s.Config(),s.request_statistics(inst))
        self.assertIsNotNone(ev)
        self.assertEqual(ev['sectioning']['assignment']['S']['F'],'F_A')

    def test_locked_teacher_hall_precheck(self):
        inst,rooms=self.make_instance(restrictive=True)
        self.assertFalse(s.feasibility_prechecks(inst,rooms))  # Different professors; same period is possible.
        inst.teacher['F1']='P0'
        del inst.__dict__['_prof_index']
        self.assertTrue(any('teacher' in msg for msg in s.feasibility_prechecks(inst,rooms)))

    def test_diagnostics_for_valid_small_case(self):
        inst,rooms=self.make_instance()
        cfg=s.Config(time_limit=4,local_seconds=.1,section_seconds=.15,seed=2)
        cfg.max_feasible_starts=1
        cfg.room_day_seconds=0
        cfg.student_swap_seconds=0
        cfg.repair_seconds=.5
        result=s.solve(inst,rooms,cfg)
        self.assertEqual(result['status'],'FEASIBLE')
        self.assertIn('attempt_log',result['diagnostics'])

    def test_proven_precheck_infeasibility_is_not_unknown(self):
        inst, rooms = self.make_instance(restrictive=True)
        inst.teacher['F1'] = 'P0'
        inst.__dict__.pop('_prof_index', None)
        result = s.solve(inst, rooms, s.Config(time_limit=2, seed=1))
        self.assertEqual(result['status'], 'INFEASIBLE_PRECHECK')
        self.assertTrue(result['diagnostics']['precheck_issues'])

    def test_feasibility_only_stops_at_first_schedule(self):
        inst, rooms = self.make_instance()
        cfg = s.Config(time_limit=3, local_seconds=1, seed=2)
        cfg.feasibility_only = True
        cfg.room_day_seconds = 0
        cfg.repair_seconds = 0
        result = s.solve(inst, rooms, cfg)
        self.assertEqual(result['status'], 'FEASIBLE')
        self.assertEqual(result['feasible_starts'], 1)
        self.assertEqual(result['best']['gaps']['student_total'], 0)

    def test_explicit_cp_sat_without_dependency(self):
        import importlib.util
        if importlib.util.find_spec('ortools'):
            self.skipTest('OR-Tools already installed')
        inst,rooms=self.make_instance()
        _,status=s.exact_repair_neighborhood(inst,rooms,{'CORE':0,'F1':0},{'F1'},{'S'},1,'cp-sat')
        self.assertEqual(status,'CP_SAT_NOT_INSTALLED')

if __name__=='__main__':unittest.main()
