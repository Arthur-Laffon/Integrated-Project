"""Reproducible joint-repair experiment on known-feasible planted schools.

The generator's witness is NEVER read by the solver. Start from an ordinary
unseeded complete coloring; measure the relaxed compulsory-allocation deficit;
run conflict-guided joint time/section LNS; validate every recovered timetable
using the independent CSV validator in a separate subprocess.

Example:
 python benchmarks/benchmark_joint_repair.py --cases 12:5 18:4 33:4 \
    --seed 2026 --repair-seconds 12
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import random
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import timetable_csv as solver


def run(case, seed, build_seconds, repair_seconds, destination):
    source = ROOT / 'benchmarks' / 'planted' / f'planted_{case[0]}c_{case[1]}spec_seed2026_input.csv'
    inst, rooms = solver.load_csv(source)
    cfg = solver.Config(seed=seed, section_seconds=2.0,
                        joint_lns_size=28, joint_lns_students=24,
                        joint_lns_step_seconds=1.5)
    stats = solver.request_statistics(inst)
    start = time.perf_counter()
    trace = {}
    coloring = solver.construct(inst, rooms, cfg, random.Random(seed),
                                solver.hard_adjacency(inst), stats,
                                start + build_seconds, trace=trace)
    result = {'case': f'{case[0]}c_{case[1]}spec', 'seed': seed,
              'lessons': len(inst.courses), 'students': len(inst.students),
              'construction_depth': trace.get('depth'),
              'construction_seconds': round(time.perf_counter()-start, 3),
              'before_unmet': '', 'after_unmet': '', 'repair_attempts': 0,
              'accepted_moves': 0, 'repair_seconds': '', 'status': 'NO_COLORING',
              'valid': False}
    if coloring is None:
        return result
    prior = solver.relaxed_compulsory_sectioning(inst, coloring, .7)
    if prior is None:
        result['status'] = 'RELAXATION_UNKNOWN'
        return result
    result['before_unmet'] = len(prior['unmet'])
    if not prior['unmet']:
        ev = solver.evaluate(inst, rooms, coloring, cfg, stats)
    else:
        ev = None
    if ev is not None:
        result['status'] = 'ALREADY_FEASIBLE'
    else:
        diag = {'repair_attempts': 0, 'repair_statuses': Counter(),
                'repair_success': 0}
        begin = time.perf_counter()
        ev = solver._try_joint_repair(inst, rooms, coloring, cfg,
                                      random.Random(seed), stats,
                                      begin + repair_seconds, diag)
        result.update(repair_attempts=diag['repair_attempts'],
                      accepted_moves=diag.get('joint_accepted_moves', 0),
                      repair_seconds=round(time.perf_counter()-begin, 3),
                      after_unmet=diag.get('joint_final_unmet', ''),
                      repair_statuses=dict(diag['repair_statuses']),
                      status='REPAIRED' if ev else 'NOT_REPAIRED')
        if ev and not result['after_unmet']:
            result['after_unmet'] = 0
    if ev is None:
        return result
    prefix = destination / f"{result['case']}_seed{seed}"
    timetable = Path(str(prefix) + '_timetable.csv')
    pupils = Path(str(prefix) + '_students.csv')
    solver.save_csv(inst, {'best': ev}, timetable)
    solver.save_student_csv(inst, {'best': ev}, pupils)
    proc = subprocess.run([sys.executable, str(ROOT / 'validate_timetable_csv.py'),
                           str(source), str(timetable), '--students-output', str(pupils)],
                          cwd=ROOT, capture_output=True, text=True, timeout=120,
                          env={**os.environ, 'OPENBLAS_NUM_THREADS': '1'})
    result['valid'] = proc.returncode == 0 and 'valid=True' in proc.stdout
    Path(str(prefix)+'_validation.log').write_text(proc.stdout+'\n'+proc.stderr,encoding='utf-8')
    if not result['valid']:
        result['status'] = 'REPAIR_REJECTED_BY_VALIDATOR'
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cases', nargs='+', default=['12:5','18:4','33:4'])
    parser.add_argument('--seed', type=int, default=2026)
    parser.add_argument('--build-seconds', type=float, default=4.0)
    parser.add_argument('--repair-seconds', type=float, default=12.0)
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'benchmarks' / 'joint_lns_runs')
    args = parser.parse_args()
    args.output_dir.mkdir(exist_ok=True, parents=True)
    cases = [tuple(int(x) for x in item.split(':')) for item in args.cases]
    results = []
    for case in cases:
        row = run(case, args.seed, args.build_seconds, args.repair_seconds, args.output_dir)
        results.append(row)
        print(f"{row['case']}: coloring={row['construction_depth']}/{row['lessons']} "
              f"unmet={row['before_unmet']}->{row['after_unmet']} "
              f"status={row['status']} valid={row['valid']}", flush=True)
    output = args.output_dir / 'joint_repair_summary.csv'
    fields = ['case','seed','lessons','students','construction_depth',
              'construction_seconds','before_unmet','after_unmet',
              'repair_attempts','accepted_moves','repair_seconds','status','valid']
    with output.open('w', newline='', encoding='utf-8') as f:
        w=csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
        w.writeheader()
        w.writerows(results)
    (args.output_dir/'joint_repair_detail.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
    print('Summary:', output)

if __name__ == '__main__':
    main()
