from __future__ import annotations
import argparse
import csv
import math
import random
import sys
import time
from collections import defaultdict, Counter
from dataclasses import dataclass, field
from itertools import combinations
from pathlib import Path
WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']
TIME_BLOCKS = [('08:00', '09:00'), ('09:00', '10:00'), ('10:00', '11:00'), ('11:00', '12:00'), ('13:00', '14:00'), ('14:00', '15:00'), ('15:00', '16:00'), ('16:00', '17:00')]
KINDS = {'course', 'professor', 'room', 'reward', 'link'}

@dataclass(frozen=True)
class Link:
    first: str
    second: str
    min_gap: int = 1
    max_gap: int | None = None
    same_day: bool = False

@dataclass
class Instance:
    T: int
    department: dict[str, str]
    teacher: dict[str, str]
    prof_avail: dict[str, set[int]]
    scores: dict[tuple[str, str], float]
    links: tuple[Link, ...] = ()
    slots_per_day: int = 8
    labels: dict[int, str] | None = None

    @property
    def courses(self):
        return list(self.department)

    @property
    def departments(self):
        return sorted(set(self.department.values()))

    @property
    def professors(self):
        return sorted(set(self.teacher.values()))

    def dept_courses(self, d):
        return [c for c in self.courses if self.department[c] == d]

    def prof_courses(self, p):
        return [c for c in self.courses if self.teacher[c] == p]

    def allowed_slots(self, c):
        return self.prof_avail[self.teacher[c]]

    def slot_name(self, t):
        return self.labels.get(t, str(t)) if self.labels else str(t)

    def links_ok(self, phi: dict[str, int], partial=False):
        for x in self.links:
            if x.first not in phi or x.second not in phi:
                if partial:
                    continue
                return False
            a, b = (phi[x.first], phi[x.second])
            gap = b - a
            if gap < x.min_gap:
                return False
            if x.max_gap is not None and gap > x.max_gap:
                return False
            if x.same_day and a // self.slots_per_day != b // self.slots_per_day:
                return False
        return True

@dataclass
class Rooms:
    equipment: dict[str, set[str]]
    available: dict[str, set[int]]
    allowed_subjects: dict[str, set[str] | None]
    subject: dict[str, str]
    required: dict[str, set[str]]

    @property
    def rooms(self):
        return list(self.equipment)

    def permits(self, c, t, r):
        allowed = self.allowed_subjects[r]
        return t in self.available[r] and self.required[c] <= self.equipment[r] and (allowed is None or self.subject[c] in allowed)

@dataclass
class Config:
    time_limit: float = 10.0
    local_seconds: float = 2.0
    enforce_room_change_boundaries: bool = False
    change_boundaries: tuple[int, ...] = (2, 4, 6)
    seed: int | None = None

def split_list(value: str) -> list[str]:
    s = (value or '').strip()
    if not s or s == '*':
        return []
    return [x.strip() for x in s.split(';') if x.strip()]

def parse_slots(value: str, T: int) -> set[int]:
    s = (value or '').strip().lower()
    if s in {'', '*', 'all'}:
        return set(range(T))
    if s in {'none', '-', 'empty'}:
        return set()
    out = {int(x.strip()) for x in s.split(';') if x.strip()}
    bad = [t for t in out if not 0 <= t < T]
    if bad:
        raise ValueError(f'slot(s) outside 0..{T - 1}: {bad}')
    return out

def parse_bool(value: str) -> bool:
    return (value or '').strip().lower() in {'1', 'true', 'yes', 'y'}

def _unique_ids(rows, kind):
    ids = [r.get('id', '').strip() for r in rows if r['kind'] == kind]
    if any((not x for x in ids)):
        raise ValueError(f'{kind} rows require a nonempty id')
    dup = sorted({x for x in ids if ids.count(x) > 1})
    if dup:
        raise ValueError(f"duplicate {kind} id(s): {', '.join(dup)}")

def weekly_labels(T: int, slots_per_day: int) -> dict[int, str] | None:
    if T == 40 and slots_per_day == 8:
        return {8 * d + b: f'{WEEKDAYS[d]} {a}-{z}' for d in range(5) for b, (a, z) in enumerate(TIME_BLOCKS)}
    return None

def load_csv(path: str | Path, T=40, slots_per_day=8) -> tuple[Instance, Rooms]:
    with open(path, newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames or 'kind' not in reader.fieldnames:
            raise ValueError("input CSV needs a 'kind' column")
        rows = []
        for n, raw in enumerate(reader, start=2):
            r = {k: v or '' for k, v in raw.items()}
            r['kind'] = r['kind'].strip().lower()
            if not r['kind']:
                continue
            if r['kind'] not in KINDS:
                raise ValueError(f"row {n}: unknown kind {r['kind']!r}")
            r['_line'] = str(n)
            rows.append(r)
    for k in ('course', 'professor', 'room'):
        _unique_ids(rows, k)
    courses = [r for r in rows if r['kind'] == 'course']
    if not courses:
        raise ValueError('at least one course row is required')
    department, teacher, subject, required = ({}, {}, {}, {})
    for r in courses:
        c = r['id'].strip()
        d = r.get('department', '').strip()
        p = r.get('professor', '').strip()
        if not d or not p:
            raise ValueError(f'course {c}: department and professor are required')
        department[c] = d
        teacher[c] = p
        subject[c] = r.get('subject', '').strip() or d
        required[c] = set(split_list(r.get('required_equipment', '')))
    prof_avail = {}
    for r in rows:
        if r['kind'] == 'professor':
            prof_avail[r['id'].strip()] = parse_slots(r.get('available_slots', ''), T)
    for p in set(teacher.values()):
        prof_avail.setdefault(p, set(range(T)))
    scores = {}
    for r in rows:
        if r['kind'] != 'reward':
            continue
        d = r.get('department', '').strip()
        c = r.get('target_course', '').strip()
        if d not in set(department.values()):
            raise ValueError(f"reward row {r['_line']}: unknown department {d!r}")
        if c not in department:
            raise ValueError(f"reward row {r['_line']}: unknown target course {c!r}")
        if department[c] == d:
            raise ValueError(f"reward row {r['_line']}: target must be external to department")
        key = (d, c)
        if key in scores:
            raise ValueError(f'duplicate reward for department={d}, target_course={c}')
        try:
            w = float(r.get('weight', ''))
        except ValueError as e:
            raise ValueError(f"reward row {r['_line']}: invalid weight") from e
        if not math.isfinite(w) or w < 0:
            raise ValueError(f"reward row {r['_line']}: weight must be finite and nonnegative")
        scores[key] = w
    links = []
    for r in rows:
        if r['kind'] != 'link':
            continue
        a = r.get('from_course', '').strip()
        b = r.get('to_course', '').strip()
        if a not in department or b not in department or a == b:
            raise ValueError(f"link row {r['_line']}: use two distinct existing courses")
        try:
            lo = int(r.get('min_gap', '').strip() or 1)
            hi_s = r.get('max_gap', '').strip()
            hi = int(hi_s) if hi_s else None
        except ValueError as e:
            raise ValueError(f"link row {r['_line']}: min_gap/max_gap must be integers") from e
        if lo < 1 or (hi is not None and hi < lo):
            raise ValueError(f"link row {r['_line']}: invalid gap range")
        links.append(Link(a, b, lo, hi, parse_bool(r.get('same_day', ''))))
    room_rows = [r for r in rows if r['kind'] == 'room']
    if not room_rows:
        raise ValueError('at least one room row is required')
    equipment, available, allowed = ({}, {}, {})
    for r in room_rows:
        q = r['id'].strip()
        equipment[q] = set(split_list(r.get('equipment', '')))
        available[q] = parse_slots(r.get('available_slots', ''), T)
        s = (r.get('allowed_subjects', '') or '').strip()
        allowed[q] = None if s in {'', '*'} else set(split_list(s))
    inst = Instance(T=T, department=department, teacher=teacher, prof_avail=prof_avail, scores=scores, links=tuple(links), slots_per_day=slots_per_day, labels=weekly_labels(T, slots_per_day))
    rooms = Rooms(equipment, available, allowed, subject, required)
    validate(inst, rooms)
    return (inst, rooms)

def validate(inst: Instance, rooms: Rooms):
    if inst.T < 1 or inst.slots_per_day < 1:
        raise ValueError('T and slots_per_day must be positive')
    C = set(inst.courses)
    if set(inst.teacher) != C or not C:
        raise ValueError('course/professor maps are inconsistent')
    for p in inst.professors:
        if p not in inst.prof_avail:
            raise ValueError(f'missing availability for professor {p}')
        if any((not 0 <= t < inst.T for t in inst.prof_avail[p])):
            raise ValueError(f'invalid professor slot for {p}')
    if set(rooms.subject) != C or set(rooms.required) != C:
        raise ValueError('room requirements must be specified for every course')
    R = set(rooms.rooms)
    if set(rooms.available) != R or set(rooms.allowed_subjects) != R:
        raise ValueError('room maps have inconsistent keys')
    for r in R:
        if any((not 0 <= t < inst.T for t in rooms.available[r])):
            raise ValueError(f'invalid room slot for {r}')
    for x in inst.links:
        possible = False
        for a in inst.allowed_slots(x.first):
            for b in inst.allowed_slots(x.second):
                gap = b - a
                if gap < x.min_gap or (x.max_gap is not None and gap > x.max_gap):
                    continue
                if x.same_day and a // inst.slots_per_day != b // inst.slots_per_day:
                    continue
                possible = True
                break
            if possible:
                break
        if not possible:
            raise ValueError(f'link {x.first}->{x.second} has no possible professor-availability pair')

def access_score(inst: Instance, phi: dict[str, int]) -> float:
    used = {d: {phi[c] for c in inst.dept_courses(d)} for d in inst.departments}
    return float(sum((w for (d, c), w in inst.scores.items() if phi[c] not in used[d])))

def room_changes(inst: Instance, phi, rho, cfg: Config):
    changes = []
    for p in inst.professors:
        by_day = defaultdict(list)
        for c in inst.prof_courses(p):
            if c in phi and c in rho:
                by_day[phi[c] // inst.slots_per_day].append(c)
        for day, cs in by_day.items():
            cs.sort(key=lambda c: phi[c])
            for a, b in zip(cs, cs[1:]):
                if rho[a] == rho[b]:
                    continue
                i = phi[a] % inst.slots_per_day
                j = phi[b] % inst.slots_per_day
                permitted = any((i < q <= j for q in cfg.change_boundaries))
                changes.append((p, day, a, b, permitted))
    return changes

def schedule_gaps(inst: Instance, phi):
    dg = 0
    tg = 0
    for groups, getter in ((inst.departments, inst.dept_courses), (inst.professors, inst.prof_courses)):
        total = 0
        for g in groups:
            by_day = defaultdict(list)
            for c in getter(g):
                if c in phi:
                    t = phi[c]
                    by_day[t // inst.slots_per_day].append(t % inst.slots_per_day)
            for xs in by_day.values():
                total += max(xs) - min(xs) + 1 - len(xs)
        if groups == inst.departments:
            dg = total
        else:
            tg = total
    return dg, tg

def complete_feasible(inst: Instance, rooms: Rooms, phi, rho, cfg: Config) -> bool:
    if set(phi) != set(inst.courses) or set(rho) != set(inst.courses):
        return False
    if not inst.links_ok(phi):
        return False
    used_p, used_d, used_r = (set(), set(), set())
    for c in inst.courses:
        t, r, p, d = (phi[c], rho[c], inst.teacher[c], inst.department[c])
        if t not in inst.allowed_slots(c) or r not in rooms.equipment or (not rooms.permits(c, t, r)):
            return False
        if (p, t) in used_p or (d, t) in used_d or (r, t) in used_r:
            return False
        used_p.add((p, t))
        used_d.add((d, t))
        used_r.add((r, t))
    return not cfg.enforce_room_change_boundaries or all((x[-1] for x in room_changes(inst, phi, rho, cfg)))

def partial_feasible(inst: Instance, rooms: Rooms, phi, rho, cfg: Config) -> bool:
    if not inst.links_ok(phi, partial=True):
        return False
    used_p, used_d, used_r = (set(), set(), set())
    for c, t in phi.items():
        r, p, d = (rho[c], inst.teacher[c], inst.department[c])
        if t not in inst.allowed_slots(c) or not rooms.permits(c, t, r):
            return False
        if (p, t) in used_p or (d, t) in used_d or (r, t) in used_r:
            return False
        used_p.add((p, t))
        used_d.add((d, t))
        used_r.add((r, t))
    if cfg.enforce_room_change_boundaries:
        for x in room_changes(inst, phi, rho, cfg):
            if not x[-1]:
                return False
    return True

def domains(inst: Instance, rooms: Rooms):
    return {c: [(t, r) for t in sorted(inst.allowed_slots(c)) for r in rooms.rooms if rooms.permits(c, t, r)] for c in inst.courses}

def objective(inst, phi, rho, cfg):
    dg, tg = schedule_gaps(inst, phi)
    return (access_score(inst, phi), -dg, -tg, -len(room_changes(inst, phi, rho, cfg)))

def solve_large(inst: Instance, rooms: Rooms, cfg: Config, restarts=200):
    rng = random.Random(cfg.seed)
    start = time.perf_counter()
    end = start + cfg.time_limit
    compat = {}
    for c in inst.courses:
        compat[c] = {}
        for t in sorted(inst.allowed_slots(c)):
            rs = [r for r in rooms.rooms if rooms.permits(c, t, r)]
            if rs:
                compat[c][t] = rs
        if not compat[c]:
            return {'status': 'INFEASIBLE', 'best': None, 'nodes': 0, 'seconds': time.perf_counter() - start}
    links_from = defaultdict(list)
    links_to = defaultdict(list)
    for lk in inst.links:
        links_from[lk.first].append(lk)
        links_to[lk.second].append(lk)
    prof_load = Counter(inst.teacher.values())
    dept_load = Counter(inst.department.values())

    def link_ok(c, t, phi):
        for lk in links_to[c]:
            if lk.first in phi:
                a = phi[lk.first]
                gap = t - a
                if gap < lk.min_gap or (lk.max_gap is not None and gap > lk.max_gap):
                    return False
                if lk.same_day and a // inst.slots_per_day != t // inst.slots_per_day:
                    return False
        for lk in links_from[c]:
            if lk.second in phi:
                b = phi[lk.second]
                gap = b - t
                if gap < lk.min_gap or (lk.max_gap is not None and gap > lk.max_gap):
                    return False
                if lk.same_day and t // inst.slots_per_day != b // inst.slots_per_day:
                    return False
        return True

    def leaves_future(c, t, phi, used_p, used_d):
        for lk in links_from[c]:
            if lk.second in phi:
                continue
            q = lk.second
            ok = False
            for t2 in compat[q]:
                gap = t2 - t
                if gap < lk.min_gap or (lk.max_gap is not None and gap > lk.max_gap):
                    continue
                if lk.same_day and t // inst.slots_per_day != t2 // inst.slots_per_day:
                    continue
                if (inst.teacher[q], t2) in used_p or (inst.department[q], t2) in used_d:
                    continue
                ok = True
                break
            if not ok:
                return False
        return True

    def change_ok(c, t, r, phi, rho):
        if not cfg.enforce_room_change_boundaries:
            return True
        p = inst.teacher[c]
        for q in inst.prof_courses(p):
            if q not in phi or rho[q] == r:
                continue
            tq = phi[q]
            if tq // inst.slots_per_day != t // inst.slots_per_day:
                continue
            i, j = sorted((tq % inst.slots_per_day, t % inst.slots_per_day))
            if not any((i < x <= j for x in cfg.change_boundaries)):
                return False
        return True
    base = sorted(inst.courses, key=lambda c: (0 if links_from[c] else 1 if links_to[c] else 2, len(compat[c]), min((len(v) for v in compat[c].values())), -dept_load[inst.department[c]], -prof_load[inst.teacher[c]], c))
    nodes = 0
    for rep in range(restarts):
        if time.perf_counter() >= end:
            break
        phi = {}
        rho = {}
        used_p = set()
        used_d = set()
        used_r = set()
        load = Counter()
        pending = set(base)
        rank = {c: i for i, c in enumerate(base)}
        failed = False
        while pending:
            if time.perf_counter() >= end:
                break
            pool = sorted(pending, key=lambda c: rank[c])[:48]
            chosen = None
            chosen_vals = None
            for c in pool:
                vals = []
                p = inst.teacher[c]
                d = inst.department[c]
                for t, rs in compat[c].items():
                    if (p, t) in used_p or (d, t) in used_d:
                        continue
                    if not link_ok(c, t, phi) or not leaves_future(c, t, phi, used_p, used_d):
                        continue
                    free = [r for r in rs if (r, t) not in used_r and change_ok(c, t, r, phi, rho)]
                    if free:
                        free.sort(key=lambda r: (len(rooms.equipment[r]), rng.random()))
                        vals.extend(((t, r) for r in free[:2]))
                if chosen_vals is None or len(vals) < len(chosen_vals):
                    chosen, chosen_vals = (c, vals)
                    if not vals:
                        break
            if not chosen_vals:
                failed = True
                break

            def vkey(tr):
                t, r = tr
                p = inst.teacher[chosen]
                same = sum((1 for q in inst.prof_courses(p) if q in rho and rho[q] == r))
                return (load[t], -same, len(rooms.equipment[r]), rng.random())
            t, r = min(chosen_vals, key=vkey)
            phi[chosen] = t
            rho[chosen] = r
            used_p.add((inst.teacher[chosen], t))
            used_d.add((inst.department[chosen], t))
            used_r.add((r, t))
            load[t] += 1
            pending.remove(chosen)
            nodes += 1
        if not failed and len(phi) == len(inst.courses) and complete_feasible(inst, rooms, phi, rho, cfg):
            local_end = min(end, time.perf_counter() + cfg.local_seconds)
            cur = objective(inst, phi, rho, cfg)
            changed = True
            while changed and time.perf_counter() < local_end:
                changed = False
                order = list(inst.courses)
                rng.shuffle(order)
                for c in order:
                    vals = [(t, r) for t, rs in compat[c].items() for r in rs if t != phi[c] or r != rho[c]]
                    rng.shuffle(vals)
                    for t, r in vals[:12]:
                        old_t, old_r = phi[c], rho[c]
                        phi[c], rho[c] = t, r
                        if complete_feasible(inst, rooms, phi, rho, cfg):
                            k = objective(inst, phi, rho, cfg)
                            if k > cur:
                                cur = k
                                changed = True
                                break
                        phi[c], rho[c] = old_t, old_r
                    if changed or time.perf_counter() >= local_end:
                        break
            dg, tg = schedule_gaps(inst, phi)
            return {'status': 'FEASIBLE', 'best': {'phi': phi, 'rho': rho, 'score': access_score(inst, phi), 'cohort_gaps': dg, 'teacher_gaps': tg, 'room_changes': len(room_changes(inst, phi, rho, cfg))}, 'nodes': nodes, 'seconds': time.perf_counter() - start}
    return {'status': 'UNKNOWN', 'best': None, 'nodes': nodes, 'seconds': time.perf_counter() - start}

def solve(inst: Instance, rooms: Rooms, cfg: Config):
    validate(inst, rooms)
    if len(inst.courses) >= 80:
        return solve_large(inst, rooms, cfg)
    dom = domains(inst, rooms)
    if any((not dom[c] for c in inst.courses)):
        return {'status': 'INFEASIBLE', 'best': None, 'nodes': 0, 'seconds': 0.0}
    rng = random.Random(cfg.seed)
    tie = {c: rng.random() for c in inst.courses}
    start = time.perf_counter()
    end = start + cfg.time_limit
    phi, rho = ({}, {})
    best = None
    best_key = None
    nodes = 0
    timed_out = False
    used_p, used_d, used_r = (set(), set(), set())

    def legal_values(c):
        vals = []
        for t, r in dom[c]:
            if (inst.teacher[c], t) in used_p or (inst.department[c], t) in used_d or (r, t) in used_r:
                continue
            phi[c], rho[c] = (t, r)
            ok = partial_feasible(inst, rooms, phi, rho, cfg)
            phi.pop(c)
            rho.pop(c)
            if ok:
                vals.append((t, r))
        return vals

    def rec():
        nonlocal best, best_key, nodes, timed_out
        if time.perf_counter() >= end:
            timed_out = True
            return
        nodes += 1
        if len(phi) == len(inst.courses):
            if not complete_feasible(inst, rooms, phi, rho, cfg):
                return
            key = objective(inst, phi, rho, cfg)
            if best_key is None or key > best_key:
                best_key = key
                best = (dict(phi), dict(rho))
            return
        rem = [c for c in inst.courses if c not in phi]
        ld = {}
        for c in rem:
            vals = legal_values(c)
            if not vals:
                return
            ld[c] = vals
        c = min(rem, key=lambda z: (len(ld[z]), -len(inst.dept_courses(inst.department[z])), tie[z]))
        vals = sorted(ld[c], key=lambda tr: (len(rooms.equipment[tr[1]]), -sum((1 for x in inst.courses if tr in dom[x])), tr))
        for t, r in vals:
            phi[c], rho[c] = (t, r)
            used_p.add((inst.teacher[c], t))
            used_d.add((inst.department[c], t))
            used_r.add((r, t))
            rec()
            used_p.remove((inst.teacher[c], t))
            used_d.remove((inst.department[c], t))
            used_r.remove((r, t))
            phi.pop(c)
            rho.pop(c)
            if timed_out:
                return
    rec()
    if best is None:
        return {'status': 'UNKNOWN' if timed_out else 'INFEASIBLE', 'best': None, 'nodes': nodes, 'seconds': time.perf_counter() - start}
    p, r = best
    local_end = time.perf_counter() + min(cfg.local_seconds, max(0.0, end - time.perf_counter()))
    changed = True
    while changed and time.perf_counter() < local_end:
        changed = False
        base = objective(inst, p, r, cfg)
        cand_best = None
        cand_key = base
        for c in inst.courses:
            for t, rr in dom[c]:
                if t == p[c] and rr == r[c]:
                    continue
                p2, r2 = (dict(p), dict(r))
                p2[c], r2[c] = (t, rr)
                if complete_feasible(inst, rooms, p2, r2, cfg):
                    k = objective(inst, p2, r2, cfg)
                    if k > cand_key:
                        cand_key, cand_best = (k, (p2, r2))
            if time.perf_counter() >= local_end:
                break
        if cand_best is None and time.perf_counter() < local_end:
            for a, b in combinations(inst.courses, 2):
                p2, r2 = (dict(p), dict(r))
                p2[a], p2[b] = (p[b], p[a])
                r2[a], r2[b] = (r[b], r[a])
                if complete_feasible(inst, rooms, p2, r2, cfg):
                    k = objective(inst, p2, r2, cfg)
                    if k > cand_key:
                        cand_key, cand_best = (k, (p2, r2))
                if time.perf_counter() >= local_end:
                    break
        if cand_best is not None:
            p, r = cand_best
            changed = True
    dg, tg = schedule_gaps(inst, p)
    return {'status': 'FEASIBLE' if timed_out else 'OPTIMAL', 'best': {'phi': p, 'rho': r, 'score': access_score(inst, p), 'cohort_gaps': dg, 'teacher_gaps': tg, 'room_changes': len(room_changes(inst, p, r, cfg))}, 'nodes': nodes, 'seconds': time.perf_counter() - start}

def save_csv(inst: Instance, result, path: str | Path):
    best = result.get('best')
    if not best:
        raise ValueError('no feasible timetable to write')
    phi, rho = (best['phi'], best['rho'])
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=['slot_index', 'timeslot', 'assignments'])
        w.writeheader()
        for t in range(inst.T):
            triples = sorted(((inst.teacher[c], c, rho[c]) for c in inst.courses if phi[c] == t))
            w.writerow({'slot_index': t, 'timeslot': inst.slot_name(t), 'assignments': '; '.join((f'({p},{c},{r})' for p, c, r in triples))})

def write_example(path: str | Path):
    cols = ['kind', 'id', 'department', 'professor', 'subject', 'available_slots', 'equipment', 'allowed_subjects', 'required_equipment', 'target_course', 'weight', 'from_course', 'to_course', 'min_gap', 'max_gap', 'same_day']
    rows = [{'kind': 'course', 'id': 'CS142L', 'department': 'CS', 'professor': 'P01', 'subject': 'CS142'}, {'kind': 'course', 'id': 'CS142E', 'department': 'CS', 'professor': 'P02', 'subject': 'CS142', 'required_equipment': 'computers'}, {'kind': 'course', 'id': 'MA101', 'department': 'MA', 'professor': 'P03', 'subject': 'MA101'}, {'kind': 'professor', 'id': 'P01', 'available_slots': '0;1;2;4;5;8;9;10;12;13;16;17;18;20;21;24;25;28;29;32;33;36;37'}, {'kind': 'professor', 'id': 'P02', 'available_slots': '1;2;3;5;6;9;10;11;13;14;17;18;19;21;22;25;26;29;30;33;34;37;38'}, {'kind': 'professor', 'id': 'P03', 'available_slots': '0;2;4;6;8;10;12;14;16;18;20;22;24;26;28;30;32;34;36;38'}, {'kind': 'room', 'id': 'R101', 'available_slots': '*', 'allowed_subjects': '*'}, {'kind': 'room', 'id': 'PC1', 'available_slots': '*', 'equipment': 'computers', 'allowed_subjects': '*'}, {'kind': 'room', 'id': 'PC2', 'available_slots': '*', 'equipment': 'computers', 'allowed_subjects': '*'}, {'kind': 'link', 'from_course': 'CS142L', 'to_course': 'CS142E', 'min_gap': '1', 'max_gap': '6', 'same_day': 'true'}, {'kind': 'reward', 'department': 'MA', 'target_course': 'CS142L', 'weight': '5'}]
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow(r)

def _lycee_curriculum(level, cohort_index):
    if level == '2nde':
        return [('FR', 4), ('MATH', 4), ('HG', 3), ('ENG', 3), ('L2', 2), ('PHYS', 3), ('SVT', 2), ('SES', 1), ('SNT', 1), ('EPS', 2), ('EMC', 1), ('AP', 4)]
    if level == '1re':
        specs = ['NSI', 'MATHS_SPE', 'PHYS_SPE', 'SES_SPE', 'HGGSP']
        a, b, c = (specs[(cohort_index + i) % len(specs)] for i in range(3))
        return [('FR', 4), ('MATH', 4), ('HG', 3), ('ENG', 2), ('L2', 2), ('EPS', 2), ('EMC', 1), ('ENSCI', 2), ('SES', 2), (a, 3), (b, 3), (c, 2)]
    specs = ['NSI', 'MATHS_SPE', 'PHYS_SPE', 'SES_SPE', 'HGGSP']
    a, b, c = (specs[(cohort_index + i) % len(specs)] for i in range(3))
    return [('PHILO', 4), ('MATH', 3), ('HG', 3), ('ENG', 2), ('L2', 2), ('EPS', 2), ('EMC', 1), ('ENSCI', 2), ('SES', 2), (a, 2), (b, 2), (c, 2), ('AP', 2), ('ORAL', 1)]

def write_lycee_example(path: str | Path, cohorts=12, seed=2026):
    rng = random.Random(seed)
    levels = ['2nde', '1re', 'Tle']
    cohort_names = [f'{levels[i % 3]}{i // 3 + 1}' for i in range(cohorts)]
    curricula = {g: _lycee_curriculum(g.rstrip('0123456789'), i) for i, g in enumerate(cohort_names)}
    curricula = {}
    for i, g in enumerate(cohort_names):
        level = '2nde' if g.startswith('2nde') else '1re' if g.startswith('1re') else 'Tle'
        curricula[g] = _lycee_curriculum(level, i)
    subj_sessions = defaultdict(int)
    for g, cur in curricula.items():
        for subj, n in cur:
            subj_sessions[subj] += n
    teacher_pool = {}
    for subj, n in subj_sessions.items():
        k = max(1, math.ceil(n / 16))
        teacher_pool[subj] = [f'{subj}_P{i + 1:02d}' for i in range(k)]
    tload = Counter()
    teacher_for = {}
    for g in cohort_names:
        for subj, n in curricula[g]:
            pool = teacher_pool[subj]
            m = min((tload[p] for p in pool))
            cand = [p for p in pool if tload[p] == m]
            p0 = rng.choice(cand)
            teacher_for[g, subj] = p0
            tload[p0] += n
    courses = []
    for g in cohort_names:
        for subj, n in curricula[g]:
            for j in range(1, n + 1):
                equip = ''
                if subj in {'SNT', 'NSI'}:
                    equip = 'computers'
                elif subj == 'EPS':
                    equip = 'gym'
                elif subj in {'PHYS', 'ENSCI'} and j == n or (subj == 'SVT' and j == n):
                    equip = 'lab'
                cid = f'{g}_{subj}_{j}'
                courses.append({'id': cid, 'department': g, 'professor': teacher_for[g, subj], 'subject': subj, 'required_equipment': equip})
    general_n = cohorts + max(6, cohorts // 3)
    pc_n = max(2, math.ceil(cohorts / 5))
    lab_n = max(3, math.ceil(cohorts / 4))
    gym_n = max(2, math.ceil(cohorts / 6))
    room_types = {'general': [f'R{i + 1:03d}' for i in range(general_n)], 'computers': [f'PC{i + 1}' for i in range(pc_n)], 'lab': [f'LAB{i + 1}' for i in range(lab_n)], 'gym': [f'GYM{i + 1}' for i in range(gym_n)]}
    used_g = defaultdict(set)
    used_p = defaultdict(set)
    used_type = defaultdict(lambda: Counter())
    ref = {}

    def scarcity(c):
        eq = c['required_equipment'] or 'general'
        cap = len(room_types[eq])
        return (cap, -tload[c['professor']], c['department'], c['subject'])
    for c in sorted(courses, key=scarcity):
        eq = c['required_equipment'] or 'general'
        legal = [t for t in range(40) if t not in used_g[c['department']] and t not in used_p[c['professor']] and (used_type[t][eq] < len(room_types[eq]))]
        if not legal:
            raise RuntimeError('could not construct lycée example; increase room/teacher resources')
        t = min(legal, key=lambda z: (sum(used_type[z].values()), rng.random()))
        ref[c['id']] = t
        used_g[c['department']].add(t)
        used_p[c['professor']].add(t)
        used_type[t][eq] += 1
    prof_avail = {}
    for p in tload:
        need = {ref[c['id']] for c in courses if c['professor'] == p}
        target = min(40, max(len(need) + 5, rng.randint(30, 34)))
        extra = list(set(range(40)) - need)
        rng.shuffle(extra)
        prof_avail[p] = need | set(extra[:max(0, target - len(need))])
    room_rows = []
    for typ, rs in room_types.items():
        for r in rs:
            closed = set(rng.sample(range(40), k=rng.randint(0, 3)))
            av = set(range(40)) - closed
            allowed = '*'
            equipment = ''
            if typ == 'computers':
                equipment, allowed = ('computers', 'SNT;NSI')
            elif typ == 'lab':
                equipment, allowed = ('lab', 'PHYS;SVT;ENSCI;PHYS_SPE')
            elif typ == 'gym':
                equipment, allowed = ('gym', 'EPS')
            room_rows.append({'kind': 'room', 'id': r, 'available_slots': ';'.join(map(str, sorted(av))), 'equipment': equipment, 'allowed_subjects': allowed})
    links = []
    by = defaultdict(list)
    for c in courses:
        by[c['department'], c['subject']].append(c['id'])
    for (g, subj), ids in by.items():
        ids.sort(key=lambda x: int(x.rsplit('_', 1)[1]))
        practical = [c for c in ids if next((z for z in courses if z['id'] == c))['required_equipment'] in {'lab', 'computers'}]
        if practical and len(ids) >= 2:
            b = practical[-1]
            earlier = [a for a in ids if ref[a] < ref[b]]
            if earlier:
                a = max(earlier, key=lambda x: ref[x])
                gap = ref[b] - ref[a]
                links.append({'kind': 'link', 'from_course': a, 'to_course': b, 'min_gap': '1', 'max_gap': str(max(gap, min(16, gap + 4))), 'same_day': 'true' if ref[a] // 8 == ref[b] // 8 else 'false'})
    cols = ['kind', 'id', 'department', 'professor', 'subject', 'available_slots', 'equipment', 'allowed_subjects', 'required_equipment', 'target_course', 'weight', 'from_course', 'to_course', 'min_gap', 'max_gap', 'same_day']
    rows = []
    rows += [dict(kind='course', **c) for c in courses]
    rows += [{'kind': 'professor', 'id': p, 'available_slots': ';'.join(map(str, sorted(av)))} for p, av in sorted(prof_avail.items())]
    rows += room_rows
    rows += links
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    return {'cohorts': cohorts, 'sessions': len(courses), 'professors': len(prof_avail), 'rooms': len(room_rows), 'links': len(links)}

def parse_boundaries(s: str):
    if not s.strip():
        return ()
    return tuple((int(x) for x in s.split(',') if x.strip()))

def main(argv=None):
    ap = argparse.ArgumentParser(description='Solve a timetable from the mixed constraint CSV format.')
    ap.add_argument('input', nargs='?', help='input constraints CSV')
    ap.add_argument('output', nargs='?', default='timetable_output.csv', help='output timetable CSV')
    ap.add_argument('--slots', type=int, default=40, help='number of weekly slots (default 40)')
    ap.add_argument('--slots-per-day', type=int, default=8, help='slots per day for same_day links')
    ap.add_argument('--time-limit', type=float, default=10.0, help='search budget in seconds')
    ap.add_argument('--local-seconds', type=float, default=2.0, help='local-improvement budget')
    ap.add_argument('--change-boundaries', default='2,4,6', help='within-day room-change boundaries; default 2,4,6 (recess/lunch/recess)')
    ap.add_argument('--enforce-room-change-boundaries', action='store_true')
    ap.add_argument('--allow-room-change-anytime', action='store_true')
    ap.add_argument('--seed', type=int, default=None)
    ap.add_argument('--write-example', metavar='PATH', help='write a small example input CSV and exit')
    ap.add_argument('--write-lycee-example', metavar='PATH', help='write a lycée-scale input CSV and exit')
    ap.add_argument('--cohorts', type=int, default=12, help='number of cohorts for --write-lycee-example')
    ap.add_argument('--example-seed', type=int, default=2026, help='seed for generated lycée example')
    args = ap.parse_args(argv)
    if args.write_example:
        write_example(args.write_example)
        print(f'wrote {args.write_example}')
        return 0
    if args.write_lycee_example:
        info = write_lycee_example(args.write_lycee_example, cohorts=args.cohorts, seed=args.example_seed)
        print(f'wrote {args.write_lycee_example}: {info}')
        return 0
    if not args.input:
        ap.error('input CSV is required unless --write-example is used')
    cfg = Config(time_limit=args.time_limit, local_seconds=args.local_seconds, enforce_room_change_boundaries=args.enforce_room_change_boundaries and not args.allow_room_change_anytime, change_boundaries=parse_boundaries(args.change_boundaries), seed=args.seed)
    try:
        inst, rooms = load_csv(args.input, T=args.slots, slots_per_day=args.slots_per_day)
        res = solve(inst, rooms, cfg)
        print(f"status={res['status']} nodes={res['nodes']} seconds={res['seconds']:.3f}")
        if res['best'] is None:
            return 2
        print(f"access_score={res['best']['score']} cohort_gaps={res['best'].get('cohort_gaps', 0)} teacher_gaps={res['best'].get('teacher_gaps', 0)} room_changes={res['best']['room_changes']}")
        save_csv(inst, res, args.output)
        print(f'wrote {args.output}')
        return 0
    except (ValueError, OSError) as e:
        print(f'error: {e}', file=sys.stderr)
        return 1
if __name__ == '__main__':
    raise SystemExit(main())
