"""Benchmark the unmodified solver against known-feasible planted instances.

A witness is first verified with the independent timetable validator, but is
never passed to the solver.  Each solver output is validated separately.

Example:
 python benchmarks/benchmark_planted.py --cohorts 9 12 18 24 33 \
   --specialties 4 5 --solver-seeds 2026 --time-limit 15
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

from benchmark_intermediate import run_case

ROOT = Path(__file__).resolve().parents[1]


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--cohorts', type=int, nargs='+', default=[9, 12, 18, 24, 33])
    p.add_argument('--specialties', type=int, nargs='+', choices=[4, 5, 6], default=[4, 5, 6])
    p.add_argument('--generation-seed', type=int, default=2026)
    p.add_argument('--solver-seeds', type=int, nargs='+', default=[2026])
    p.add_argument('--time-limit', type=float, default=15)
    p.add_argument('--baseline', action='store_true', help='include unchanged v5.4 solver')
    p.add_argument('--input-dir', type=Path, default=ROOT / 'benchmarks' / 'planted')
    p.add_argument('--output-dir', type=Path, default=ROOT / 'benchmarks' / 'planted_solver_runs')
    args = p.parse_args(argv)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    fields = ['case', 'version', 'generation_seed', 'seed', 'known_feasible',
              'students', 'lessons', 'mandatory_requests', 'budget',
              'status', 'valid', 'seconds', 'deepest_partial',
              'best_seeded_depth', 'pupil_checks', 'exit_code']
    summary = args.output_dir / 'summary.csv'
    with summary.open('w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for n in args.cohorts:
            for spec in args.specialties:
                case = f'planted_{n}c_{spec}spec_seed{args.generation_seed}'
                manifest = args.input_dir / f'{case}_manifest.json'
                if not manifest.is_file():
                    raise FileNotFoundError(f'{manifest} (generate the witness first)')
                details = json.loads(manifest.read_text(encoding='utf-8'))
                if details['status'] != 'PLANTED_FEASIBLE' or not details['validation']['valid']:
                    raise ValueError(f'{case} lacks a certified valid witness')
                # Reject files modified after the independent witness validation.
                for key in ('input', 'witness_timetable', 'witness_students'):
                    file_path = args.input_dir / details['files'][key]
                    if not file_path.is_file():
                        raise FileNotFoundError(file_path)
                    if hashlib.sha256(file_path.read_bytes()).hexdigest() != details['sha256'][key]:
                        raise ValueError(f'{file_path} changed after witness validation')
                source = args.input_dir / details['files']['input']
                for seed in args.solver_seeds:
                    for version in (('baseline', 'clean') if args.baseline else ('clean',)):
                        result = run_case(case, source, version, seed,
                                          args.time_limit, args.output_dir)
                        result.update(generation_seed=args.generation_seed,
                                      known_feasible=True,
                                      students=details['students'],
                                      lessons=details['lessons'],
                                      mandatory_requests=details['mandatory_requests'])
                        writer.writerow(result)
                        f.flush()
                        print(f"{case:32s} {version:8s} solver_seed={seed} "
                              f"status={result['status']:12s} valid={result['valid']} "
                              f"depth={result['deepest_partial']}/{result['lessons']} ", flush=True)
    print(f'CSV summary: {summary}')


if __name__ == '__main__':
    main()
