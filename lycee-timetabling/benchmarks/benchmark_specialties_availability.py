"""Certify and benchmark planted schools with more specialties and less teacher availability.

Each (cohorts, specialties, availability) combination gets its own witness
folder, avoiding collisions between files named by cohort / specialty alone.
An independently validated planted witness is generated first. The ordinary
solver receives ONLY the public input file and its outputs are validated again.

Examples:
 python benchmarks/benchmark_specialties_availability.py \
   --cohorts 9 12 --specialties 5 6 --teacher-availability .9 .7 .6 \
   --time-limit 10 --seed 2026
 python benchmarks/benchmark_specialties_availability.py \
   --cohorts 18 --specialties 6 --teacher-availability .6 --generate-only
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
from pathlib import Path

from generate_planted_feasible import build
from benchmark_intermediate import run_case

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cohorts', nargs='+', type=int, default=[9,12,18])
    parser.add_argument('--specialties', nargs='+', type=int, choices=[4,5,6], default=[5,6])
    parser.add_argument('--teacher-availability', nargs='+', type=float, default=[.9,.7,.6])
    parser.add_argument('--seed', type=int, default=2026,
                        help='Seed for generating certified inputs')
    parser.add_argument('--solver-seeds', nargs='+', type=int, default=[2026])
    parser.add_argument('--time-limit', type=float, default=10)
    parser.add_argument('--generate-only', action='store_true')
    parser.add_argument('--output-dir', type=Path, default=ROOT/'benchmarks'/'stress_specialties')
    a=parser.parse_args()
    a.output_dir.mkdir(parents=True, exist_ok=True)
    cols=['cohorts','specialties','teacher_availability','generation_seed','solver_seed',
          'students','lessons','mandatory_requests','professors','witness_valid',
          'solver_status','solver_valid','solver_seconds','deepest_partial',
          'best_seeded_depth','pupil_checks']
    outfile=a.output_dir/'stress_results.csv'
    with outfile.open('w', newline='', encoding='utf-8') as f:
        writer=csv.DictWriter(f, fieldnames=cols)
        writer.writeheader()
        for n in a.cohorts:
            for k in a.specialties:
                for av in a.teacher_availability:
                    if not .50 <= av <= 1:
                        raise ValueError('teacher availability must be between 0.50 and 1.0')
                    label=f'{n}c_{k}spec_{round(av*100):02d}pct_seed{a.seed}'
                    directory=a.output_dir/label
                    directory.mkdir(parents=True,exist_ok=True)
                    witness=build(directory, cohorts=n, specialties=k,
                                  teacher_availability=av, seed=a.seed)
                    assert witness['validation']['valid']
                    for key, filename in witness['files'].items():
                        if key in witness['sha256']:
                            assert hashlib.sha256((directory/filename).read_bytes()).hexdigest()==witness['sha256'][key]
                    common={'cohorts':n,'specialties':k,'teacher_availability':av,
                            'generation_seed':a.seed,'students':witness['students'],
                            'lessons':witness['lessons'],
                            'mandatory_requests':witness['mandatory_requests'],
                            'professors':witness['professors'], 'witness_valid':True}
                    if a.generate_only:
                        row={**common,'solver_status':'NOT_RUN'}
                        writer.writerow(row)
                        f.flush()
                        print(f'{label}: VALID witness ({witness["lessons"]} lessons), solver not run', flush=True)
                        continue
                    for seed in a.solver_seeds:
                        result=run_case(label, directory/witness['files']['input'],
                                        'clean', seed, a.time_limit, directory)
                        row={**common,'solver_seed':seed,
                             'solver_status':result['status'],
                             'solver_valid':result['valid'],
                             'solver_seconds':result['seconds'],
                             'deepest_partial':result['deepest_partial'],
                             'best_seeded_depth':result['best_seeded_depth'],
                             'pupil_checks':result['pupil_checks']}
                        writer.writerow(row)
                        f.flush()
                        print(f'{label}: {result["status"]} valid={result["valid"]} '
                              f'depth={result["deepest_partial"]}/{witness["lessons"]}',flush=True)
    print('Results:',outfile)

if __name__=='__main__': main()
