## Contents

- `timetable_csv.py` — scheduling, mandatory pupil sectioning, repair and CLI
- `algorithms/` — Dinic flow and Kuhn matching implementations
- `validate_timetable_csv.py` — independent schedule validator to check the constraints are applied. 
- `generate_lycee_csv.py` (+ legacy code helper, will clean up) — a randomly lycée input generator
- `benchmarks/benchmark_intermediate.py` — repeated runs for testing
- `benchmarks/benchmark_planted.py`, `benchmarks/benchmark_joint_repair.py` — planted recovery and joint-repair experiments
- `debug_gui.py`, `flatten_groups.py` — GUI and conversion utilities
- `tests/` — 


## Install and test

```powershell
py -m pip install -r requirements.txt
py -m unittest discover -s tests -v
```

- Run and validate (example command)

```powershell
New-Item -ItemType Directory -Force output | Out-Null
py timetable_csv.py benchmarks/mixed_5.csv output/timetable.csv `
  --students-output output/students.csv --seed 2026 `
  --time-limit 30 --feasibility-only --diagnostics output/diagnostics.json
py validate_timetable_csv.py benchmarks/mixed_5.csv output/timetable.csv `
  --students-output output/students.csv
```
`UNKNOWN` means the solver did not establish feasibility within its compute time budget, not that the school constraints render a timetable impossible.

## Automated benchmarks

```powershell
py benchmarks/benchmark_intermediate.py `
  --cases mixed_5 mixed_4_90pct `
  --seeds 2026 2027 --time-limit 30 `
  --output-dir benchmarks/my_results
```

Generate and certify with numbers of your choice (with an example here) :

```powershell
py benchmarks/generate_planted_feasible.py `
    --cohorts 15 `
    --specialties 6 `
    --teacher-availability 0.90 `
    --seed 2026 `
    --output-dir benchmarks/planted
```

```powershell
New-Item -ItemType Directory -Force output | Out-Null

py timetable_csv.py `
    benchmarks/planted/planted_15c_6spec_seed2026_input.csv `
    output/timetable_15c.csv `
    --students-output output/students_15c.csv `
    --seed 2026 `
    --time-limit 120 `
    --feasibility-only 
```
if the output is flagged as valid, you can go to the debugger using 
```powershell
py debug_gui.py
```

To run direct joint-repair experiments, first generate the instances. You can then use:

```powershell
py benchmarks/benchmark_joint_repair.py --cases 12:5 18:4 `
  --seed 2026 --build-seconds 4 --repair-seconds 12
```