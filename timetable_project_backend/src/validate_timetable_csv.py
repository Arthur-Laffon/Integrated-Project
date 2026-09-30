from __future__ import annotations
import argparse
import csv
import importlib.util
import math
import re
import sys
from pathlib import Path

def load_solver(path):
    spec = importlib.util.spec_from_file_location('tt_solver', path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod

def parse_output(path, T):
    phi = {}
    rho = {}
    prof = {}
    seen_slots = set()
    errors = []
    pat = re.compile('^\\(([^,]+),([^,]+),([^,]+)\\)$')
    with open(path, newline='', encoding='utf-8-sig') as f:
        r = csv.DictReader(f)
        if not r.fieldnames or 'slot_index' not in r.fieldnames or 'assignments' not in r.fieldnames:
            return (phi, rho, prof, ['output CSV needs slot_index and assignments columns'], seen_slots)
        for n, row in enumerate(r, start=2):
            try:
                t = int((row.get('slot_index') or '').strip())
            except ValueError:
                errors.append(f'row {n}: invalid slot_index')
                continue
            if not 0 <= t < T:
                errors.append(f'row {n}: slot {t} outside 0..{T - 1}')
                continue
            if t in seen_slots:
                errors.append(f'row {n}: duplicate slot row {t}')
            seen_slots.add(t)
            s = (row.get('assignments') or '').strip()
            if not s:
                continue
            for token in [x.strip() for x in s.split(';') if x.strip()]:
                m = pat.match(token)
                if not m:
                    errors.append(f'row {n}: malformed assignment {token!r}')
                    continue
                p, c, room = (x.strip() for x in m.groups())
                if c in phi:
                    errors.append(f'course {c} appears more than once')
                    continue
                phi[c] = t
                rho[c] = room
                prof[c] = p
    return (phi, rho, prof, errors, seen_slots)

def validate(constraints, output, solver_path, slots=40, slots_per_day=8, change_boundaries=(2, 4, 6), enforce_room_changes=False):
    s = load_solver(solver_path)
    inst, rooms = s.load_csv(constraints, T=slots, slots_per_day=slots_per_day)
    phi, rho, out_prof, errors, seen_slots = parse_output(output, slots)
    expected = set(inst.courses)
    actual = set(phi)
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    if missing:
        errors.append(f"missing courses: {', '.join(missing[:20])}" + (' ...' if len(missing) > 20 else ''))
    if extra:
        errors.append(f"unknown courses: {', '.join(extra[:20])}" + (' ...' if len(extra) > 20 else ''))
    if seen_slots != set(range(slots)):
        miss_slots = sorted(set(range(slots)) - seen_slots)
        errors.append(f'missing slot rows: {miss_slots}')
    for c in expected & actual:
        if out_prof[c] != inst.teacher[c]:
            errors.append(f'{c}: professor {out_prof[c]} does not match required {inst.teacher[c]}')
        if rho[c] not in rooms.equipment:
            errors.append(f'{c}: unknown room {rho[c]}')
            continue
        if phi[c] not in inst.allowed_slots(c):
            errors.append(f'{c}: professor unavailable at slot {phi[c]}')
        if not rooms.permits(c, phi[c], rho[c]):
            errors.append(f'{c}: room {rho[c]} incompatible or unavailable at slot {phi[c]}')
    for a in inst.courses:
        if a not in phi:
            continue
        for b in inst.courses:
            if b <= a or b not in phi or phi[a] != phi[b]:
                continue
            if inst.teacher[a] == inst.teacher[b]:
                errors.append(f'teacher collision at slot {phi[a]}: {a}, {b}')
            if inst.department[a] == inst.department[b]:
                errors.append(f'cohort collision at slot {phi[a]}: {a}, {b}')
            if rho[a] == rho[b]:
                errors.append(f'room collision at slot {phi[a]} in {rho[a]}: {a}, {b}')
    if not inst.links_ok(phi, partial=False):
        for lk in inst.links:
            if lk.first not in phi or lk.second not in phi:
                continue
            a, b = (phi[lk.first], phi[lk.second])
            gap = b - a
            ok = gap >= lk.min_gap and (lk.max_gap is None or gap <= lk.max_gap) and (not lk.same_day or a // slots_per_day == b // slots_per_day)
            if not ok:
                errors.append(f'link violated: {lk.first}->{lk.second}')
    cfg = s.Config(enforce_room_change_boundaries=enforce_room_changes, change_boundaries=tuple(change_boundaries))
    bad_changes = []
    if expected <= actual and all((c in rho for c in expected)):
        bad_changes = [x for x in s.room_changes(inst, phi, rho, cfg) if not x[-1]]
        if enforce_room_changes:
            for p, day, a, b, ok in bad_changes:
                errors.append(f'room-change boundary violated: {p} day={day} {a}->{b}')
    complete = expected == actual and (not extra)
    access = s.access_score(inst, phi) if complete else math.nan
    upper = float(sum(inst.scores.values()))
    frac = access / upper if complete and upper > 0 else 1.0 if complete and upper == 0 else math.nan
    room_change_count = len(s.room_changes(inst, phi, rho, cfg)) if complete else -1
    cohort_gaps, teacher_gaps = s.schedule_gaps(inst, phi) if complete else (-1, -1)
    return {'valid': len(errors) == 0, 'errors': errors, 'courses_expected': len(expected), 'courses_scheduled': len(actual & expected), 'access_score': access, 'access_upper_bound': upper, 'access_fraction_upper_bound': frac, 'cohort_gaps': cohort_gaps, 'teacher_gaps': teacher_gaps, 'room_changes': room_change_count, 'room_change_boundary_violations': len(bad_changes), 'score_tuple': (access, -cohort_gaps, -teacher_gaps, -room_change_count) if complete else None}

def write_report(path, report):
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['metric', 'value'])
        for k, v in report.items():
            if k == 'errors':
                continue
            w.writerow([k, v])
        for i, e in enumerate(report['errors'], 1):
            w.writerow([f'error_{i}', e])

def main():
    p = argparse.ArgumentParser()
    p.add_argument('constraints')
    p.add_argument('output')
    p.add_argument('--solver', default=str(Path(__file__).with_name('timetable_csv_1h.py')))
    p.add_argument('--slots', type=int, default=40)
    p.add_argument('--slots-per-day', type=int, default=8)
    p.add_argument('--change-boundaries', default='2,4,6')
    p.add_argument('--enforce-room-change-boundaries', action='store_true')
    p.add_argument('--allow-room-change-anytime', action='store_true')
    p.add_argument('--report')
    a = p.parse_args()
    bounds = tuple((int(x) for x in a.change_boundaries.split(',') if x.strip()))
    r = validate(a.constraints, a.output, a.solver, a.slots, a.slots_per_day, bounds, a.enforce_room_change_boundaries and not a.allow_room_change_anytime)
    for k, v in r.items():
        if k != 'errors':
            print(f'{k}={v}')
    for e in r['errors']:
        print(f'error={e}')
    if a.report:
        write_report(a.report, r)
    raise SystemExit(0 if r['valid'] else 2)
if __name__ == '__main__':
    main()
