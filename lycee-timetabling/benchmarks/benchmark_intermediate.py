"""Benchmark French-lycee schools at intermediate scales.

Runs the solver in an isolated subprocess (with a wall-clock guard), retains
solver diagnostics, and independently validates completed timetables.  Use
--baseline to run unchanged v5.4 alongside the cleaned solver.

Example:
  python benchmarks/benchmark_intermediate.py --time-limit 25 --seeds 2026 \
      --cases mixed_4_90pct lycee_9c_4spec_90 lycee_12c_5spec_90
"""
from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
INPUTS = ROOT / 'benchmarks' / 'intermediate'


def locate(name: str) -> Path:
    """Find an existing benchmark or accept a direct CSV input path."""
    for candidate in (Path(name), INPUTS / f'{name}.csv', ROOT / 'benchmarks' / f'{name}.csv'):
        if candidate.is_file():
            return candidate.resolve()
    raise FileNotFoundError(f'No benchmark named {name}')


def run_case(name: str, source: Path, version: str, seed: int, budget: float,
             destination: Path) -> dict:
    prefix = f'{source.stem}_{version}_seed{seed}'
    target = destination / f'{prefix}_timetable.csv'
    students = destination / f'{prefix}_students.csv'
    diag = destination / f'{prefix}_diagnostics.json'
    log = destination / f'{prefix}_solver.log'
    env = dict(os.environ, OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1', MKL_NUM_THREADS='1')
    solver = (ROOT / 'timetable_csv.py' if version == 'clean'
              else ROOT / 'baseline' / 'timetable_csv_v54_precleanup.py')
    command = [sys.executable, str(solver), str(source), str(target),
               '--students-output', str(students), '--diagnostics', str(diag),
               '--seed', str(seed), '--time-limit', str(budget), '--feasibility-only',
               '--seed-strategy', 'optimized', '--local-seconds', '0',
               '--student-swap-seconds', '0', '--room-day-seconds', '0',
               '--repair-seconds', '1']
    row = {'case': name, 'version': version, 'seed': seed, 'students': '',
           'lessons': '', 'budget': budget, 'status': 'INTERRUPTED',
           'valid': False, 'seconds': '', 'deepest_partial': 0,
           'best_seeded_depth': 0, 'pupil_checks': 0, 'exit_code': ''}
    try:
        p = subprocess.run(command, cwd=ROOT, env=env, capture_output=True,
                           text=True, timeout=budget + 12)
        row['exit_code'] = p.returncode
        log.write_text(p.stdout + '\n' + p.stderr, encoding='utf-8')
    except subprocess.TimeoutExpired as e:
        log.write_text(f'Wall-clock guard interrupted the run after {budget+12}s.\n'
                       f'{e.stdout or b""}\n{e.stderr or b""}', encoding='utf-8')
    if diag.is_file():
        data = json.loads(diag.read_text(encoding='utf-8'))
        row.update(status=data.get('status', 'UNKNOWN'), seconds=data.get('seconds', ''),
                   deepest_partial=data.get('deepest_partial', 0),
                   best_seeded_depth=max((a.get('depth', 0) for a in data.get('attempt_log', [])
                                          if a.get('seed') != 'none'), default=0),
                   pupil_checks=sum(a.get('pupil_checks', 0) for a in data.get('attempt_log', [])))
    if target.is_file() and students.is_file():
        try:
            p = subprocess.run([sys.executable, str(ROOT / 'validate_timetable_csv.py'),
                                str(source), str(target), '--students-output', str(students)],
                               cwd=ROOT, env=env, capture_output=True, text=True, timeout=90)
            row['valid'] = p.returncode == 0 and 'valid=True' in p.stdout
            (destination / f'{prefix}_validation.log').write_text(
                p.stdout + '\n' + p.stderr, encoding='utf-8')
        except subprocess.TimeoutExpired:
            row['valid'] = False
    return row


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--cases', nargs='+', default=['mixed_4_90pct', 'lycee_9c_4spec_90',
                   'lycee_9c_5spec_90', 'lycee_12c_4spec_90', 'lycee_12c_5spec_90',
                   'lycee_18c_4spec_90', 'lycee_18c_5spec_90',
                   'lycee_24c_5spec_90', 'lycee_33c_5spec_90'])
    p.add_argument('--seeds', nargs='+', type=int, default=[2026])
    p.add_argument('--time-limit', type=float, default=25)
    p.add_argument('--baseline', action='store_true')
    p.add_argument('--output-dir', type=Path, default=ROOT / 'benchmarks' / 'intermediate_results')
    args = p.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    fieldnames = ['case','version','seed','students','lessons','budget','status','valid',
                  'seconds','deepest_partial','best_seeded_depth','pupil_checks','exit_code']
    summary = args.output_dir / 'summary.csv'
    with summary.open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for name in args.cases:
            source = locate(name)
            with source.open(newline='', encoding='utf-8-sig') as file:
                kinds = [row.get('kind') for row in csv.DictReader(file)]
            students_count, lessons_count = kinds.count('student'), kinds.count('course')
            for seed in args.seeds:
                for version in ('baseline', 'clean') if args.baseline else ('clean',):
                    row = run_case(name, source, version, seed, args.time_limit, args.output_dir)
                    row.update(students=students_count, lessons=lessons_count)
                    writer.writerow(row)
                    stream.flush()
                    print(f"{name:24s} {version:8s} seed={seed} "
                          f"status={row['status']:24s} depth={row['deepest_partial']} "
                          f"valid={row['valid']} time={row['seconds']}", flush=True)
    print('Results:', summary)


if __name__ == '__main__':
    main()
