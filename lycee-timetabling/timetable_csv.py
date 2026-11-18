from __future__ import annotations
import argparse
import csv
import json
import heapq
import math
import random
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
import numpy as np
from scipy.optimize import Bounds, LinearConstraint, linear_sum_assignment, milp
from scipy.sparse import coo_matrix
from algorithms.max_flow import dinic_max_flow
from algorithms.bipartite_matching import has_full_bipartite_matching

WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']
TIME_BLOCKS = [('08:00', '09:00'), ('09:00', '10:00'), ('10:00', '11:00'), ('11:00', '12:00'), ('13:00', '14:00'), ('14:00', '15:00'), ('15:00', '16:00'), ('16:00', '17:00')]
KINDS = {'course', 'professor', 'room', 'reward', 'link', 'student', 'request', 'preference', 'lock', 'relation', 'dependency', 'group', 'membership'}

@dataclass(frozen=True)
class Link:
    first: str
    second: str
    min_gap: int = 1
    max_gap: int | None = None
    same_day: bool = False

@dataclass(frozen=True)
class Relation:
    first: str
    second: str
    kind: str

@dataclass(frozen=True)
class Request:
    student: str
    family: str
    required: bool
    weight: float
    locked_section: str | None = None

@dataclass(frozen=True)
class Dependency:
    from_family: str | None
    from_course: str | None
    to_family: str
    required: bool
    weight: float

@dataclass
class Instance:
    T: int
    slots_per_day: int
    department: dict[str, str]
    teacher: dict[str, str]
    subject: dict[str, str]
    required_equipment: dict[str, set[str]]
    section_of: dict[str, str | None]
    hard_group: dict[str, bool]
    explicit_size: dict[str, int]
    prof_avail: dict[str, set[int]]
    scores: dict[tuple[str, str], float]
    links: tuple[Link, ...]
    students: tuple[str, ...]
    home_class: dict[str, str]
    extra_fixed_courses: dict[str, set[str]]
    requests: tuple[Request, ...]
    section_family: dict[str, str]
    section_capacity: dict[str, int]
    teacher_pref: dict[tuple[str, int], float]
    lock_time: dict[str, int]
    lock_room: dict[str, str]
    labels: dict[int, str] | None = None
    relations: tuple[Relation, ...] = ()
    prof_room_weight: dict[str, float] = field(default_factory=dict)
    prof_room_max: dict[str, int] = field(default_factory=dict)
    _slot_domains: dict[str, frozenset[int]] | None = field(default=None, repr=False)
    dependencies: tuple[Dependency, ...] = ()
    synthetic_requests: frozenset[tuple[str, str]] = frozenset()
    group_of: dict[str, str] = field(default_factory=dict)
    group_info: dict[str, dict[str, str]] = field(default_factory=dict)
    group_members: dict[str, set[str]] = field(default_factory=dict)
    student_profile: dict[str, dict[str, str]] = field(default_factory=dict)

    @cached_property
    def courses(self):
        return list(self.department)

    @cached_property
    def professors(self):
        return sorted(set(self.teacher.values()))

    @cached_property
    def departments(self):
        return sorted({d for d in self.department.values() if d})

    @cached_property
    def sections(self):
        return sorted(self.section_family)

    @cached_property
    def families(self):
        return sorted(set(self.section_family.values()))

    @cached_property
    def _prof_index(self):
        d = defaultdict(list)
        for c in self.courses:
            d[self.teacher[c]].append(c)
        return d

    @cached_property
    def _dept_index(self):
        d = defaultdict(list)
        for c in self.courses:
            if self.department[c] and self.hard_group[c]:
                d[self.department[c]].append(c)
        return d

    @cached_property
    def _section_index(self):
        d = defaultdict(list)
        for c in self.courses:
            if self.section_of[c]:
                d[self.section_of[c]].append(c)
        return d

    @cached_property
    def _family_index(self):
        d = defaultdict(list)
        for sec, fam in self.section_family.items():
            d[fam].append(sec)
        return d

    @cached_property
    def _group_index(self):
        groups = defaultdict(list)
        for c, group in self.group_of.items():
            if group:
                groups[group].append(c)
        return groups

    @cached_property
    def _fixed_courses(self):
        d = {s: set(self.extra_fixed_courses.get(s, set())) for s in self.students}
        for s in self.students:
            for c in self.dept_courses(self.home_class[s]):
                if not self.group_of.get(c):
                    d[s].add(c)
        for group, members in self.group_members.items():
            for s in members:
                d[s].update(self._group_index[group])
        return d

    @cached_property
    def _fixed_attendees(self):
        d = {c: set() for c in self.courses}
        for s, cs in self._fixed_courses.items():
            for c in cs:
                if c in d:
                    d[c].add(s)
        return d

    def prof_courses(self, p):
        return self._prof_index[p]

    def dept_courses(self, d):
        return self._dept_index[d]

    def section_courses(self, section):
        return self._section_index[section]

    def family_sections(self, family):
        return self._family_index[family]

    def allowed_slots(self, c):
        if self._slot_domains is not None:
            return self._slot_domains[c]
        return self._basic_slots(c)

    def _basic_slots(self, c):
        x = self.prof_avail[self.teacher[c]]
        return x & {self.lock_time[c]} if c in self.lock_time else x

    def slot_name(self, t):
        return self.labels.get(t, str(t)) if self.labels else str(t)

    def links_ok(self, phi, partial=False):
        for x in self.links:
            if x.first not in phi or x.second not in phi:
                if partial:
                    continue
                return False
            a, b = phi[x.first], phi[x.second]
            gap = b - a
            if gap < x.min_gap:
                return False
            if x.max_gap is not None and gap > x.max_gap:
                return False
            if x.same_day and a // self.slots_per_day != b // self.slots_per_day:
                return False
        for x in self.relations:
            if x.first not in phi or x.second not in phi:
                if partial:
                    continue
                return False
            a, b = phi[x.first], phi[x.second]
            if not relation_ok(x.kind, a, b, self.slots_per_day):
                return False
        return True

@dataclass
class Rooms:
    equipment: dict[str, set[str]]
    available: dict[str, set[int]]
    allowed_subjects: dict[str, set[str] | None]
    capacity: dict[str, int]
    room_type: dict[str, str]

    @cached_property
    def rooms(self):
        return list(self.equipment)

@dataclass
class Config:
    time_limit: float = 15.0
    local_seconds: float = 6.0
    section_seconds: float = 1.0
    restarts: int = 120
    candidate_moves: int = 32
    exact_candidates: int = 6
    tabu_tenure: int = 12
    lns_size: int = 5
    lns_nodes: int = 500
    seed: int | None = None
    w_room_waste: float = 2.0
    w_room_balance: float = 1.0
    w_room_change: float = 3.0
    w_special_room: float = 3.0
    w_optional: float = 80.0
    w_student_max: float = 25.0
    w_student_sq: float = 2.5
    w_student_gaps: float = 0.75
    w_teacher_max: float = 12.0
    w_teacher_sq: float = 1.25
    w_teacher_gaps: float = 0.5
    w_teacher_pref: float = 4.0
    w_daily: float = 0.025
    section_gap_weight: float = 2.0
    section_refine_rounds: int = 3
    max_feasible_starts: int = 3
    room_day_seconds: float = 0.25
    seed_strategy: str = 'auto'
    student_swap_seconds: float = 0.6
    repair_seconds: float = 3.0
    repair_size: int = 16
    repair_students: int = 8
    repair_backend: str = 'auto'
    attempt_policy: str = 'adaptive'
    diagnostics: str | None = None
    feasibility_only: bool = False
    pupil_propagation: bool = True
    propagation_match_interval: int = 64
    optimized_seed_seconds: float = 0.7
    propagation_match_limit: int = 128
    incremental_propagation: bool = True
    incremental_mrv: bool = True
    seed_lns: bool = True
    seed_lns_seconds: float = 0.5
    joint_lns_size: int = 28
    joint_lns_students: int = 24
    joint_lns_step_seconds: float = 1.5
    joint_lns_enabled: bool = True


def relation_ok(kind, a, b, slots_per_day):
    if kind == 'SAME_DAY':
        return a // slots_per_day == b // slots_per_day
    if kind == 'DIFFERENT_DAY':
        return a // slots_per_day != b // slots_per_day
    if kind == 'CONSECUTIVE':
        return b == a + 1 and a // slots_per_day == b // slots_per_day
    if kind == 'SAME_SLOT':
        return a == b
    raise ValueError(f'unknown relation {kind}')


def propagate_domains(inst):
    edges = []
    for x in inst.links:
        edges.append((x.first, x.second, lambda a, b, z=x: b - a >= z.min_gap and (z.max_gap is None or b - a <= z.max_gap) and (not z.same_day or a // inst.slots_per_day == b // inst.slots_per_day)))
    for x in inst.relations:
        edges.append((x.first, x.second, lambda a, b, z=x: relation_ok(z.kind, a, b, inst.slots_per_day)))
    graph = defaultdict(list)
    indeg = Counter()
    for x in inst.links:
        graph[x.first].append(x.second)
        indeg[x.second] += 1
    queue = [c for c in inst.courses if indeg[c] == 0]
    visited = 0
    while queue:
        a = queue.pop()
        visited += 1
        for b in graph[a]:
            indeg[b] -= 1
            if indeg[b] == 0:
                queue.append(b)
    if visited != len(inst.courses):
        raise ValueError('chronological precedence cycle')
    domains = {c: set(inst._basic_slots(c)) for c in inst.courses}
    changed = True
    while changed:
        changed = False
        for a, b, predicate in edges:
            da, db = domains[a], domains[b]
            na = {x for x in da if any(predicate(x, y) for y in db)}
            nb = {y for y in db if any(predicate(x, y) for x in na)}
            if not na or not nb:
                raise ValueError(f'chronological relation makes {a},{b} infeasible')
            if na != da or nb != db:
                domains[a], domains[b] = na, nb
                changed = True
    inst._slot_domains = {c: frozenset(d) for c, d in domains.items()}


def split_list(value):
    s = (value or '').strip()
    if not s or s == '*':
        return []
    return [x.strip() for x in s.split(';') if x.strip()]


def parse_bool(value, default=False):
    s = (value or '').strip().lower()
    if not s:
        return default
    return s in {'1', 'true', 'yes', 'y'}


def parse_slots(value, T):
    s = (value or '').strip().lower()
    if s in {'', '*', 'all'}:
        return set(range(T))
    if s in {'none', '-', 'empty'}:
        return set()
    out = {int(x.strip()) for x in s.split(';') if x.strip()}
    bad = [x for x in out if x < 0 or x >= T]
    if bad:
        raise ValueError(f'slot(s) outside 0..{T - 1}: {bad}')
    return out


def weekly_labels(T, slots_per_day):
    if T == 40 and slots_per_day == 8:
        return {8 * d + p: f'{WEEKDAYS[d]} {a}-{b}' for d in range(5) for p, (a, b) in enumerate(TIME_BLOCKS)}
    return None


def _int(value, default=0):
    s = (value or '').strip()
    return int(s) if s else default


def _float(value, default=0.0):
    s = (value or '').strip()
    return float(s) if s else default


def load_csv(path: str | Path, T=40, slots_per_day=8):
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
            r['_line'] = n
            rows.append(r)
    seen = defaultdict(set)
    for kind in ('course', 'professor', 'room', 'student', 'group'):
        for r in rows:
            if r['kind'] != kind:
                continue
            x = r.get('id', '').strip()
            if not x:
                raise ValueError(f'row {r["_line"]}: {kind} id required')
            if x in seen[kind]:
                raise ValueError(f'duplicate {kind} id {x}')
            seen[kind].add(x)
    course_rows = [r for r in rows if r['kind'] == 'course']
    if not course_rows:
        raise ValueError('at least one course row is required')
    department = {}
    teacher = {}
    subject = {}
    required_equipment = {}
    section_of = {}
    hard_group = {}
    explicit_size = {}
    section_family = {}
    section_capacity = {}
    group_rows = {r['id'].strip(): r for r in rows if r['kind'] == 'group'}
    group_of = {}
    for r in course_rows:
        c = r['id'].strip()
        p = r.get('professor', '').strip()
        if not p:
            raise ValueError(f'course {c}: professor required')
        sec = r.get('section', '').strip() or None
        fam = r.get('family', '').strip() or (r.get('subject', '').strip() if sec else '')
        cap = _int(r.get('section_capacity', ''), 30)
        if sec:
            if sec in section_family and section_family[sec] != fam:
                raise ValueError(f'section {sec}: inconsistent family')
            if sec in section_capacity and section_capacity[sec] != cap:
                raise ValueError(f'section {sec}: inconsistent capacity')
            section_family[sec] = fam
            section_capacity[sec] = cap
        group_id = r.get('group_id', '').strip()
        if group_id and group_id not in group_rows:
            raise ValueError(f'course {c}: unknown teaching group {group_id}')
        if group_id and sec and group_id != sec:
            raise ValueError(f'course {c}: flexible section group_id must equal its section')
        group_of[c] = group_id
        department[c] = r.get('department', '').strip()
        teacher[c] = p
        subject[c] = r.get('subject', '').strip() or fam or department[c]
        required_equipment[c] = set(split_list(r.get('required_equipment', '')))
        section_of[c] = sec
        hard_group[c] = parse_bool(r.get('hard_group', ''), default=(sec is None and bool(department[c])))
        explicit_size[c] = _int(r.get('student_count', ''), 0)
    prof_room_weight = {}
    prof_room_max = {}
    for r in rows:
        if r['kind'] == 'professor':
            p = r['id'].strip()
            prof_room_weight[p] = _float(r.get('room_change_weight', ''), 1.0)
            limit = r.get('max_room_changes_per_day', '').strip()
            if limit:
                prof_room_max[p] = int(limit)
                if prof_room_max[p] < 0:
                    raise ValueError(f'professor {p}: negative room change limit')
            if prof_room_weight[p] < 0:
                raise ValueError(f'professor {p}: negative room change weight')
    prof_avail = {}
    for r in rows:
        if r['kind'] == 'professor':
            prof_avail[r['id'].strip()] = parse_slots(r.get('available_slots', ''), T)
    for p in set(teacher.values()):
        prof_avail.setdefault(p, set(range(T)))
    room_rows = [r for r in rows if r['kind'] == 'room']
    if not room_rows:
        raise ValueError('at least one room row is required')
    equipment = {}
    room_avail = {}
    allowed = {}
    room_capacity = {}
    room_type = {}
    for r in room_rows:
        q = r['id'].strip()
        equipment[q] = set(split_list(r.get('equipment', '')))
        room_avail[q] = parse_slots(r.get('available_slots', ''), T)
        a = r.get('allowed_subjects', '').strip()
        allowed[q] = None if a in {'', '*'} else set(split_list(a))
        room_capacity[q] = _int(r.get('capacity', ''), 10**9)
        room_type[q] = r.get('room_type', '').strip() or ('special' if equipment[q] else 'general')
    students = []
    home_class = {}
    extra_fixed_courses = {}
    student_profile = {}
    for r in rows:
        if r['kind'] != 'student':
            continue
        s = r['id'].strip()
        students.append(s)
        home_class[s] = r.get('home_class', '').strip()
        extra_fixed_courses[s] = set(split_list(r.get('fixed_courses', '')))
        student_profile[s] = {k: r.get(k, '').strip() for k in ('grade', 'lva', 'lvb', 'previous_specialities', 'track')}
    group_members = {g: set() for g in group_rows}
    flexible_groups = {group_of[c] for c in group_of if group_of[c] and section_of[c]}
    for r in rows:
        if r['kind'] != 'membership':
            continue
        student = r.get('student_id', '').strip()
        group = r.get('group_id', '').strip()
        if student not in home_class:
            raise ValueError(f'row {r["_line"]}: unknown member student {student}')
        if group not in group_rows:
            raise ValueError(f'row {r["_line"]}: unknown member group {group}')
        if student in group_members[group]:
            raise ValueError(f'row {r["_line"]}: duplicate membership {student},{group}')
        if group in flexible_groups:
            raise ValueError(f'row {r["_line"]}: flexible specialty groups must be allocated through requests')
        group_members[group].add(student)
    group_info = {g: {k: r.get(k, '').strip() for k in ('grade', 'subject', 'group_type', 'parent_group', 'capacity')} for g, r in group_rows.items()}
    for group, members in group_members.items():
        grade = group_info[group]['grade']
        role = group_info[group]['group_type']
        language = group_info[group]['subject']
        for student in members:
            profile = student_profile[student]
            if grade and profile.get('grade') and grade != profile['grade']:
                raise ValueError(f'group {group}: student {student} has incompatible grade')
            if role in ('LVA', 'LVB') and profile.get(role.lower()) and profile[role.lower()] != language:
                raise ValueError(f'group {group}: student {student} enrolled in incorrect {role} language')
        capacity = _int(group_info[group]['capacity'], 0)
        if capacity and len(members) > capacity:
            raise ValueError(f'group {group}: {len(members)} pupils exceed declared capacity {capacity}')
    requests = []
    for r in rows:
        if r['kind'] != 'request':
            continue
        s = r.get('student_id', '').strip() or r.get('id', '').strip()
        fam = r.get('family', '').strip()
        if s not in home_class:
            raise ValueError(f'row {r["_line"]}: unknown student {s}')
        if fam not in set(section_family.values()):
            raise ValueError(f'row {r["_line"]}: unknown family {fam}')
        locked = r.get('locked_section', '').strip() or None
        if locked and (locked not in section_family or section_family[locked] != fam):
            raise ValueError(f'row {r["_line"]}: invalid locked section {locked}')
        requests.append(Request(s, fam, parse_bool(r.get('required', ''), True), _float(r.get('weight', ''), 1.0), locked))
    dependencies = []
    known_families = set(section_family.values())
    for r in rows:
        if r['kind'] != 'dependency':
            continue
        source_family = r.get('from_family', '').strip() or None
        source_course = r.get('from_course', '').strip() or None
        target_family = r.get('to_family', '').strip()
        if bool(source_family) == bool(source_course):
            raise ValueError(f'row {r["_line"]}: specify exactly one of from_family or from_course')
        if source_family and source_family not in known_families:
            raise ValueError(f'row {r["_line"]}: unknown source family {source_family}')
        if source_course and source_course not in department:
            raise ValueError(f'row {r["_line"]}: unknown source course {source_course}')
        if source_course and section_of[source_course]:
            raise ValueError(f'row {r["_line"]}: from_course must be a fixed/non-section lesson; use from_family for specialty sections')
        if target_family not in known_families:
            raise ValueError(f'row {r["_line"]}: unknown target family {target_family}')
        if source_family == target_family:
            raise ValueError(f'row {r["_line"]}: a family cannot depend on itself')
        dep_weight = _float(r.get('weight', ''), 1.0)
        if dep_weight < 0 or not math.isfinite(dep_weight):
            raise ValueError(f'row {r["_line"]}: dependency weight must be nonnegative and finite')
        dependencies.append(Dependency(source_family, source_course, target_family, parse_bool(r.get('required', ''), True), dep_weight))
    original_requests = {(r.student, r.family): r for r in requests}
    expanded_requests = dict(original_requests)
    synthetic_requests = set()
    fixed_by_student = {s: set(extra_fixed_courses[s]) for s in students}
    legacy_courses_by_home = defaultdict(set)
    for c in department:
        if hard_group[c] and not section_of[c] and department[c] and not group_of[c]:
            legacy_courses_by_home[department[c]].add(c)
    for s in students:
        fixed_by_student[s].update(legacy_courses_by_home.get(home_class[s], ()))
    fixed_group_courses = defaultdict(set)
    for c, group in group_of.items():
        if group and not section_of[c]:
            fixed_group_courses[group].add(c)
    for group, members in group_members.items():
        for s in members:
            fixed_by_student[s].update(fixed_group_courses[group])
    change = True
    while change:
        change = False
        for s in students:
            for dep in dependencies:
                source_is_fixed = bool(dep.from_course and dep.from_course in fixed_by_student[s])
                source_req = expanded_requests.get((s, dep.from_family)) if dep.from_family else None
                if not source_is_fixed and source_req is None:
                    continue
                key = (s, dep.to_family)
                existing = expanded_requests.get(key)
                definitely_required = dep.required and (source_is_fixed or bool(source_req and source_req.required))
                if existing is None:
                    expanded_requests[key] = Request(s, dep.to_family, definitely_required, 0.0)
                    synthetic_requests.add(key)
                    change = True
                elif definitely_required and not existing.required:
                    expanded_requests[key] = Request(s, dep.to_family, True, existing.weight, existing.locked_section)
                    change = True
    requests = list(expanded_requests.values())
    req_keys = [(x.student, x.family) for x in requests]
    if len(req_keys) != len(set(req_keys)):
        raise ValueError('duplicate request for same student/family')
    scores = {}
    for r in rows:
        if r['kind'] != 'reward':
            continue
        d = r.get('department', '').strip()
        c = r.get('target_course', '').strip()
        if c not in department:
            raise ValueError(f'row {r["_line"]}: unknown reward course {c}')
        scores[d, c] = _float(r.get('weight', ''), 1.0)
    links = []
    relations = []
    for r in rows:
        if r['kind'] != 'link':
            continue
        a = r.get('from_course', '').strip()
        b = r.get('to_course', '').strip()
        if a not in department or b not in department or a == b:
            raise ValueError(f'row {r["_line"]}: invalid link')
        lo = _int(r.get('min_gap', ''), 1)
        hi_s = r.get('max_gap', '').strip()
        hi = int(hi_s) if hi_s else None
        if lo < 1 or (hi is not None and hi < lo):
            raise ValueError(f'row {r["_line"]}: invalid link gap')
        links.append(Link(a, b, lo, hi, parse_bool(r.get('same_day', ''), False)))
    for r in rows:
        if r['kind'] != 'relation':
            continue
        kind = r.get('relation', '').strip().upper()
        a = r.get('from_course', '').strip() or r.get('course', '').strip()
        b = r.get('to_course', '').strip()
        if kind == 'BETWEEN':
            before, after = r.get('before', '').strip(), r.get('after', '').strip()
            if any(c not in department for c in (a, before, after)) or len({a, before, after}) != 3:
                raise ValueError(f'row {r["_line"]}: invalid BETWEEN relation')
            links.extend([Link(before, a), Link(a, after)])
        elif kind == 'BEFORE':
            if a not in department or b not in department or a == b:
                raise ValueError(f'row {r["_line"]}: invalid BEFORE relation')
            links.append(Link(a, b))
        elif kind in {'SAME_DAY', 'DIFFERENT_DAY', 'CONSECUTIVE', 'SAME_SLOT'}:
            if a not in department or b not in department or a == b:
                raise ValueError(f'row {r["_line"]}: invalid {kind} relation')
            relations.append(Relation(a, b, kind))
        else:
            raise ValueError(f'row {r["_line"]}: unknown relation {kind}')
    teacher_pref = defaultdict(float)
    for r in rows:
        if r['kind'] != 'preference':
            continue
        p = r.get('professor', '').strip()
        if p not in prof_avail:
            raise ValueError(f'row {r["_line"]}: unknown professor {p}')
        slots = parse_slots(r.get('slots', '') or r.get('available_slots', ''), T)
        w = _float(r.get('weight', ''), 0.0)
        for t in slots:
            teacher_pref[p, t] += w
    lock_time = {}
    lock_room = {}
    for r in rows:
        if r['kind'] != 'lock':
            continue
        c = r.get('target_course', '').strip() or r.get('id', '').strip()
        if c not in department:
            raise ValueError(f'row {r["_line"]}: unknown locked course {c}')
        slot_s = r.get('slot', '').strip()
        room_s = r.get('room', '').strip()
        if slot_s:
            t = int(slot_s)
            if t < 0 or t >= T:
                raise ValueError(f'row {r["_line"]}: invalid lock slot')
            lock_time[c] = t
        if room_s:
            if room_s not in equipment:
                raise ValueError(f'row {r["_line"]}: unknown lock room')
            lock_room[c] = room_s
    inst = Instance(T, slots_per_day, department, teacher, subject, required_equipment, section_of, hard_group, explicit_size, prof_avail, scores, tuple(links), tuple(students), home_class, extra_fixed_courses, tuple(requests), section_family, section_capacity, dict(teacher_pref), lock_time, lock_room, weekly_labels(T, slots_per_day), tuple(relations), prof_room_weight, prof_room_max)
    inst.dependencies = tuple(dependencies)
    inst.synthetic_requests = frozenset(synthetic_requests)
    inst.group_of = group_of
    inst.group_info = group_info
    inst.group_members = group_members
    inst.student_profile = student_profile
    rooms = Rooms(equipment, room_avail, allowed, room_capacity, room_type)
    validate_instance(inst, rooms)
    propagate_domains(inst)
    return inst, rooms


def fixed_student_courses(inst):
    return {s: set(cs) for s, cs in inst._fixed_courses.items()}


def fixed_students_by_course(inst):
    return inst._fixed_attendees


def validate_instance(inst, rooms):
    for c in inst.courses:
        if not inst.allowed_slots(c):
            raise ValueError(f'course {c}: no allowed professor slot')
        if c in inst.lock_room and inst.lock_room[c] not in rooms.rooms:
            raise ValueError(f'course {c}: invalid locked room')
    for c in inst.courses:
        if inst.group_of.get(c) and not inst.section_of[c] and inst.explicit_size[c] > 0 and inst.explicit_size[c] != len(inst._fixed_attendees[c]):
            raise ValueError(f'course {c}: declared student_count does not match explicit group roster')
    for group in set(inst.group_of.values()) - {''}:
        if not inst.group_members.get(group) and not any(inst.section_of[c] for c in inst._group_index[group]):
            raise ValueError(f'fixed teaching group {group}: no members')
    for sec in inst.sections:
        if inst.section_capacity[sec] <= 0:
            raise ValueError(f'section {sec}: capacity must be positive')
    for s in inst.students:
        bad = inst.extra_fixed_courses[s] - set(inst.courses)
        if bad:
            raise ValueError(f'student {s}: unknown fixed course(s) {sorted(bad)}')


def seed_section_assignment(inst, rng, strategy='affinity'):
    by_family = defaultdict(list)
    for r in inst.requests:
        if r.required:
            by_family[r.family].append(r)
    fixed = inst._fixed_courses
    out = defaultdict(dict)
    for family, requests in by_family.items():
        sections = inst.family_sections(family)
        loads = Counter()
        covered = {sec: set() for sec in sections}
        locked = [r for r in requests if r.locked_section]
        free = [r for r in requests if not r.locked_section]
        for r in locked:
            sec = r.locked_section
            if loads[sec] >= inst.section_capacity[sec]:
                return None
            out[r.student][family] = sec
            loads[sec] += 1
            covered[sec].update(fixed[r.student])
        if strategy == 'affinity':
            by_home = defaultdict(list)
            for req in free:
                by_home[inst.home_class[req.student]].append(req)
            home_keys = list(by_home)
            rng.shuffle(home_keys)
            free = []
            for home in home_keys:
                rng.shuffle(by_home[home])
                free.extend(by_home[home])
        else:
            rng.shuffle(free)
        for r in free:
            candidates = [sec for sec in sections if loads[sec] < inst.section_capacity[sec]]
            if not candidates:
                return None
            if strategy == 'affinity':
                pupil_courses = fixed[r.student]
                def cost(sec):
                    already_shared = len(pupil_courses & covered[sec])
                    # Sharing fixed teaching groups reduces redundant hard edges.
                    # This affects only the provisional coloring, not eligibility.
                    return (-already_shared, loads[sec] / inst.section_capacity[sec], rng.random())
                sec = min(candidates, key=cost)
            else:
                sec = min(candidates, key=lambda q: (loads[q], rng.random()))
            out[r.student][family] = sec
            loads[sec] += 1
            covered[sec].update(fixed[r.student])
    return {student: dict(families) for student, families in out.items()}


def optimized_section_seed(inst, rng, seconds=0.7, lns=True, lns_seconds=0.5, metrics=None):
    """Primary objective is the NUMBER of distinct edges, matching graph
    construction costs; restricted course domains break ties.
    """
    initial = seed_section_assignment(inst, rng, 'affinity')
    if initial is None:
        return None
    requests = [r for r in inst.requests if r.required]
    if not requests:
        return initial
    start = time.perf_counter()
    swap_deadline = start + max(0., seconds)
    deadline = swap_deadline + (max(0., lns_seconds) if lns else 0.0)
    base = hard_adjacency(inst)
    loads = Counter(q for fs in initial.values() for q in fs.values())
    assignments = {s: dict(fs) for s, fs in initial.items()}
    counts = Counter()
    fixed = inst._fixed_courses
    sec_courses = {q: tuple(inst.section_courses(q)) for q in inst.sections}
    idx = {c: i for i, c in enumerate(inst.courses)}
    base_idx = {idx[c]: {idx[d] for d in nb} for c, nb in base.items()}
    allowed = [sum(1 << t for t in inst.allowed_slots(c)) for c in inst.courses]
    sizes = [b.bit_count() for b in allowed]
    edge_weights = {}

    def edge(a, b):
        x, y = idx[a], idx[b]
        if x == y or y in base_idx[x]:
            return None
        return (x, y) if x < y else (y, x)

    def pupil_edges(student):
        chosen = list(assignments[student].values())
        result = set()
        for q in chosen:
            for a in fixed[student]:
                for b in sec_courses[q]:
                    e = edge(a, b)
                    if e is not None:
                        result.add(e)
        for i, asec in enumerate(chosen):
            for bsec in chosen[i+1:]:
                for a in sec_courses[asec]:
                    for b in sec_courses[bsec]:
                        e = edge(a, b)
                        if e is not None:
                            result.add(e)
        return result

    def weight(e):
        # The main objective is unweighted edge count. A small tie-break
        # favours avoiding new edges involving tightly constrained lessons.
        if e not in edge_weights:
            a, b = e
            overlap = (allowed[a] & allowed[b]).bit_count()
            tightness = max(1, min(sizes[a], sizes[b]))
            # Edges with disjoint time domains are harmless for colouring.
            # Prefer removing edges that destroy a substantial share of a
            # constrained lesson's currently legal times.
            edge_weights[e] = (.01 if overlap == 0 else
                               1.0 + 2.5 * overlap / tightness
                               * (1.0 + 2.0 / tightness))
        return edge_weights[e]

    def update(edges, direction):
        for e in edges:
            counts[e] += direction
            if not counts[e]:
                del counts[e]

    initial_assignments = {s: dict(fs) for s, fs in assignments.items()}
    pupil_cache = {s: pupil_edges(s) for s in assignments}
    for edges in pupil_cache.values():
        update(edges, +1)
    movable = [r for r in requests if not r.locked_section]
    if not movable or seconds <= 0:
        return assignments

    def incremental_cost(edges):
        return sum(weight(e) for e in edges if e not in counts)

    # A local improvement cannot increase the unique-edge objective.
    # Moving one pupil may free room for another; hence swap moves follow.
    for _ in range(3):
        rng.shuffle(movable)
        improved = False
        for r in movable:
            if time.perf_counter() >= swap_deadline:
                break
            student, fam = r.student, r.family
            old_q = assignments[student][fam]
            old_edges = pupil_cache[student]
            update(old_edges, -1)
            best_q, best_edges, best_cost = old_q, old_edges, incremental_cost(old_edges)
            for q in inst.family_sections(fam):
                if q == old_q or loads[q] >= inst.section_capacity[q]:
                    continue
                assignments[student][fam] = q
                candidate = pupil_edges(student)
                score = incremental_cost(candidate)
                if score + 1e-8 < best_cost:
                    best_q, best_edges, best_cost = q, candidate, score
            assignments[student][fam] = best_q
            update(best_edges, +1)
            pupil_cache[student] = best_edges
            if best_q != old_q:
                loads[old_q] -= 1
                loads[best_q] += 1
                improved = True
        if not improved or time.perf_counter() >= swap_deadline:
            break

    # A short capacity-preserving exchange phase can break local minima
    # where every section is already full.
    by_family = defaultdict(list)
    for r in movable:
        by_family[r.family].append(r)
    while time.perf_counter() < swap_deadline:
        round_improved = False
        families = list(by_family)
        rng.shuffle(families)
        for fam in families:
            pupil_reqs = by_family[fam]
            if len(pupil_reqs) < 2:
                continue
            for _ in range(min(3 * len(pupil_reqs), 150)):
                if time.perf_counter() >= swap_deadline:
                    break
                a, b = rng.sample(pupil_reqs, 2)
                sa, sb = a.student, b.student
                qa, qb = assignments[sa][fam], assignments[sb][fam]
                if qa == qb:
                    continue
                ea, eb = pupil_cache[sa], pupil_cache[sb]
                update(ea, -1)
                update(eb, -1)
                previous = incremental_cost(ea | eb)
                assignments[sa][fam], assignments[sb][fam] = qb, qa
                na, nb = pupil_edges(sa), pupil_edges(sb)
                current = incremental_cost(na | nb)
                if current + 1e-8 < previous:
                    pupil_cache[sa], pupil_cache[sb] = na, nb
                    update(na, +1)
                    update(nb, +1)
                    round_improved = True
                else:
                    assignments[sa][fam], assignments[sb][fam] = qa, qb
                    update(ea, +1)
                    update(eb, +1)
        if not round_improved:
            break
    # Larger capacity-preserving neighborhoods: remove a small set of
    # pupils from one family, optimise a permutation of their existing section
    # seats by a Hungarian assignment, then accept only an actual (not proxy)
    # improvement to the full unique-edge objective. Locked pupils are never
    # selected, capacities are unchanged, and existing other choices remain.
    lns_attempts = 0
    lns_improvements = 0
    if lns and lns_seconds > 0:
        groups = {f: rr for f, rr in by_family.items()
                  if len(rr) >= 3 and len(inst.family_sections(f)) >= 2}
        family_weights = [len(rr) for rr in groups.values()]
        family_keys = list(groups)
        stagnant = 0
        while family_keys and time.perf_counter() < deadline and stagnant < 40:
            lns_attempts += 1
            fam = rng.choices(family_keys, weights=family_weights, k=1)[0]
            rr = groups[fam]
            target = min(len(rr), rng.choice((5, 7, 9, 12)))
            # Sample a varied set of currently occupied sections.
            per_sec = defaultdict(list)
            for r in rr:
                per_sec[assignments[r.student][fam]].append(r.student)
            section_keys = list(per_sec)
            rng.shuffle(section_keys)
            picked = []
            for q in section_keys:
                picked.append(rng.choice(per_sec[q]))
                if len(picked) >= target:
                    break
            if len(picked) < target:
                used = set(picked)
                pool = [r.student for r in rr if r.student not in used]
                picked += rng.sample(pool, min(len(pool), target-len(picked)))
            if len(picked) < 3:
                stagnant += 1
                continue
            seats = [assignments[s][fam] for s in picked]
            if len(set(seats)) < 2:
                stagnant += 1
                continue
            old_edges = {s: pupil_cache[s] for s in picked}
            old_unique = set().union(*old_edges.values())
            for edges in old_edges.values():
                update(edges, -1)
            outside_edges = set(counts)
            old_score = sum(weight(e) for e in old_unique if e not in outside_edges)
            # Approximate the best joint permutation by assignment costs.
            marginal = []
            candidate_edges = []
            for s in picked:
                original = assignments[s][fam]
                row, edges_row = [], []
                for q in seats:
                    assignments[s][fam] = q
                    es = pupil_edges(s)
                    edges_row.append(es)
                    row.append(sum(weight(e) for e in es if e not in outside_edges))
                assignments[s][fam] = original
                candidate_edges.append(edges_row)
                marginal.append(row)
            # SciPy's modified Jonker-Volgenant assignment algorithm:
            # https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.linear_sum_assignment.html
            rows, cols = linear_sum_assignment(np.asarray(marginal))
            new_edges = {picked[i]: candidate_edges[i][int(j)] for i, j in zip(rows, cols)}
            actual_unique = set().union(*new_edges.values())
            new_score = sum(weight(e) for e in actual_unique if e not in outside_edges)
            if new_score + 1e-7 < old_score:
                for i, j in zip(rows, cols):
                    assignments[picked[i]][fam] = seats[int(j)]
                for s in picked:
                    pupil_cache[s] = new_edges[s]
                    update(new_edges[s], +1)
                stagnant = 0
                lns_improvements += 1
            else:
                for s in picked:
                    update(old_edges[s], +1)
                stagnant += 1
    # Maintain the original no-increase-in-edge-count regression guarantee.
    initial_edges = hard_adjacency(inst, initial_assignments)
    initial_total = sum(map(len, initial_edges.values()))
    final_total = sum(map(len, hard_adjacency(inst, assignments).values()))
    if metrics is not None:
        metrics.update(edge_count_initial=initial_total//2,
                       edge_count_final=min(initial_total, final_total)//2,
                       lns_attempts=lns_attempts,
                       lns_improvements=lns_improvements)
    return initial_assignments if final_total > initial_total else assignments

class _PupilFeasibilityPropagator:
    """Sound incremental pupil feasibility with watched section combinations.

    A pupil's cached tuple of compatible sections is a *witness*: a new
    assignment can only invalidate it when it schedules a lesson in one of
    its watched sections or in a compulsory fixed course at an occupied
    witness time. Witnesses need not be restored on DFS rollback, because
    removing a scheduled lesson only relaxes conflicts. Capacity-flow
    certificates are cached by family until a relevant time mask changes.
    """
    def __init__(self, inst, matching_interval=64, matching_limit=128,
                 incremental=True):
        self.inst = inst
        self.incremental = incremental
        self.fixed_mask = {s: 0 for s in inst.students}
        self.section_mask = {q: 0 for q in inst.sections}
        self.fixed_by_course = inst._fixed_attendees
        self.section_of = inst.section_of
        self.required = defaultdict(list)
        self.family_pupils = defaultdict(set)
        self.family_requests = defaultdict(list)
        self.pupil_families = defaultdict(set)
        for r in inst.requests:
            if not r.required:
                continue
            eligible = (r.locked_section,) if r.locked_section else tuple(inst.family_sections(r.family))
            self.required[r.student].append((r.family, eligible))
            self.family_pupils[r.family].add(r.student)
            self.family_requests[r.family].append((r.student, eligible))
            self.pupil_families[r.student].add(r.family)
        self.witness = {}
        self.watchers = defaultdict(set)
        for pupil, requests in self.required.items():
            # All section masks are initially empty.
            initial = tuple(options[0] for _, options in requests)
            self.witness[pupil] = initial
            for section in initial:
                self.watchers[section].add(pupil)
        self.capacity_dirty = set(self.family_requests)
        self.all_capacity_families = frozenset(self.family_requests)
        self.capacity_certified = set()
        self.stacks = []
        self.matching_interval = max(0, matching_interval)
        self.matching_limit = max(0, matching_limit)
        self.checks = self.prunes = self.matching_checks = self.matching_prunes = 0
        self.watch_skips = self.witness_recomputes = self.family_flow_checks = 0

    def _witness_works(self, s, witness):
        occupied = self.fixed_mask[s]
        for section in witness:
            bits = self.section_mask[section]
            if bits & occupied:
                return False
            occupied |= bits
        return True

    def _find_witness(self, s):
        fixed = self.fixed_mask[s]
        requests = self.required[s]
        domains = [tuple(q for q in eligible if not (self.section_mask[q] & fixed))
                   for _, eligible in requests]
        if any(not options for options in domains):
            return None
        ordering = sorted(range(len(domains)), key=lambda i: len(domains[i]))
        selected = [None] * len(domains)
        def visit(j, occupied):
            if j == len(ordering):
                return tuple(selected)
            idx = ordering[j]
            for q in domains[idx]:
                bits = self.section_mask[q]
                if not (bits & occupied):
                    selected[idx] = q
                    result = visit(j+1, occupied | bits)
                    if result is not None:
                        return result
            return None
        return visit(0, fixed)

    def _replace_witness(self, s, result):
        previous = self.witness[s]
        if result == previous:
            return
        for q in previous:
            self.watchers[q].discard(s)
        self.witness[s] = result
        for q in result:
            self.watchers[q].add(s)

    def pupil_possible(self, s):
        if s not in self.required:
            return True
        if self.incremental and self._witness_works(s, self.witness[s]):
            return True
        self.witness_recomputes += 1
        result = self._find_witness(s)
        if result is None:
            return False
        self._replace_witness(s, result)
        return True

    @staticmethod
    def _flow_feasible(groups, capacities):
        """Test whether all compulsory family requests fit their sections.

        Source (MIT-licensed Dinic adapter):
        https://algorithm.tamnd.com/dinic/
        The scheduling network is source -> request domains -> sections -> sink.
        """
        if not groups:
            return True
        sections = sorted({section for choices in groups for section in choices})
        if not sections:
            return False
        demand_total = sum(groups.values())
        if sum(capacities[section] for section in sections) < demand_total:
            return False

        group_count = len(groups)
        sink = 1 + group_count + len(sections)
        section_nodes = {section: group_count + i + 1
                         for i, section in enumerate(sections)}
        edges = []
        for group_node, (choices, demand) in enumerate(groups.items(), start=1):
            edges.append((0, group_node, demand))
            edges.extend((group_node, section_nodes[q], demand) for q in choices)
        edges.extend((node, sink, capacities[section])
                     for section, node in section_nodes.items())
        return dinic_max_flow(sink + 1, edges, 0, sink,
                              cutoff=demand_total) == demand_total

    def capacity_possible(self):
        # A family already proved feasible stays feasible until a relevant
        # placement changes masks; a backtrack marks it dirty again.
        families = self.family_requests if not self.incremental else (
            self.capacity_dirty | (self.all_capacity_families-self.capacity_certified))
        for family in tuple(families):
            requests = self.family_requests[family]
            groups = Counter()
            for s, eligible in requests:
                available = tuple(q for q in eligible
                                  if not (self.section_mask[q] & self.fixed_mask[s]))
                if not available:
                    return False
                groups[available] += 1
            self.family_flow_checks += 1
            if not self._flow_feasible(groups, self.inst.section_capacity):
                return False
            self.capacity_certified.add(family)
            self.capacity_dirty.discard(family)
        return True

    def push(self, c, t, depth):
        bit = 1 << t
        fixed_changes = [(s, self.fixed_mask[s]) for s in self.fixed_by_course[c]]
        for s, old in fixed_changes:
            self.fixed_mask[s] = old | bit
        section = self.section_of[c]
        section_old = self.section_mask[section] if section else None
        if section:
            self.section_mask[section] |= bit
        changed_families = ({self.inst.section_family[section]} if section else set())
        for s, _ in fixed_changes:
            changed_families.update(self.pupil_families[s])
        self.capacity_dirty.update(changed_families)
        self.capacity_certified.difference_update(changed_families)
        self.stacks.append((fixed_changes, section, section_old, changed_families))

        if self.incremental:
            affected = set()
            for s, _ in fixed_changes:
                if s in self.required and any(self.section_mask[q] & bit
                       for q in self.witness[s]):
                    affected.add(s)
            if section:
                for s in tuple(self.watchers[section]):
                    if s in affected:
                        continue
                    if self.fixed_mask[s] & bit or any(
                           q != section and self.section_mask[q] & bit
                           for q in self.witness[s]):
                        affected.add(s)
            self.watch_skips += len(self.fixed_by_course[c]) + (
                len(self.family_pupils[self.inst.section_family[section]]) if section else 0
            ) - len(affected)
        else:
            affected = set(self.fixed_by_course[c])
            if section:
                affected.update(self.family_pupils[self.inst.section_family[section]])
        for s in affected:
            if s not in self.required:
                continue
            self.checks += 1
            if not self.pupil_possible(s):
                self.prunes += 1
                self.pop()
                return False
        if (self.matching_interval and depth % self.matching_interval == 0
                and self.matching_checks < self.matching_limit):
            self.matching_checks += 1
            if not self.capacity_possible():
                self.matching_prunes += 1
                self.pop()
                return False
        return True

    def pop(self):
        fixed_changes, section, old, changed_families = self.stacks.pop()
        for s, previous in fixed_changes:
            self.fixed_mask[s] = previous
        if section:
            self.section_mask[section] = old
        # Cached witnesses remain valid on relaxation. Flow certificates
        # obtained at greater depth are also valid on relaxation, but
        # dirty-marking is conservative and avoids stale certificates.
        self.capacity_dirty.update(changed_families)
        self.capacity_certified.difference_update(changed_families)


def hard_adjacency(inst, section_assignment=None):
    if section_assignment is None and '_base_hard_adjacency' in inst.__dict__:
        return inst._base_hard_adjacency
    if section_assignment is None:
        adj = {c: set() for c in inst.courses}
    else:
        adj = {c: set(v) for c, v in hard_adjacency(inst).items()}

    def clique(cs):
        cs = list(cs)
        for i, a in enumerate(cs):
            others = cs[:i] + cs[i + 1:]
            adj[a].update(others)

    if section_assignment is None:
        for d in (inst._prof_index, inst._dept_index, inst._section_index, inst._group_index):
            for cs in d.values():
                clique(cs)
        for cs in inst._fixed_courses.values():
            clique(cs)
        inst._base_hard_adjacency = adj
    else:
        for s, fs in section_assignment.items():
            cs = set(inst._fixed_courses.get(s, set()))
            for sec in fs.values():
                cs.update(inst.section_courses(sec))
            clique(cs)
    return adj


def request_statistics(inst):
    fam_home = Counter()
    fam_pair = Counter()
    fam_fixed = Counter()
    by_student = defaultdict(list)
    for r in inst.requests:
        weight = 1.0 if r.required else 0.4 * max(1.0, r.weight)
        fam_home[r.family, inst.home_class[r.student]] += weight
        by_student[r.student].append(r.family)
        for c in inst._fixed_courses.get(r.student, ()):
            fam_fixed[r.family, c] += weight
    for fs in by_student.values():
        uniq = sorted(set(fs))
        for i, a in enumerate(uniq):
            for b in uniq[i + 1:]:
                fam_pair[a, b] += 1
    nsec = Counter(inst.section_family.values())
    return fam_home, fam_pair, nsec, fam_fixed


def overlap_weight(inst, a, b, stats):
    fam_home, fam_pair, nsec, fam_fixed = stats
    sa, sb = inst.section_of[a], inst.section_of[b]
    fa = inst.section_family.get(sa) if sa else None
    fb = inst.section_family.get(sb) if sb else None
    if fa and fb and fa != fb:
        return fam_pair.get(tuple(sorted((fa, fb))), 0) / max(1, nsec[fa] * nsec[fb])
    if fa and not sb:
        if inst._fixed_attendees[b]:
            return fam_fixed[fa, b] / max(1, nsec[fa])
        if inst.department[b]:
            return fam_home[fa, inst.department[b]] / max(1, nsec[fa])
    if fb and not sa:
        if inst._fixed_attendees[a]:
            return fam_fixed[fb, a] / max(1, nsec[fb])
        if inst.department[a]:
            return fam_home[fb, inst.department[a]] / max(1, nsec[fb])
    return 0.0


def potential_overlap(inst, phi, stats):
    by_slot = defaultdict(list)
    for c, t in phi.items():
        by_slot[t].append(c)
    total = 0.0
    for cs in by_slot.values():
        for i, a in enumerate(cs):
            for b in cs[i + 1:]:
                total += overlap_weight(inst, a, b, stats)
    return total


def access_score(inst, phi):
    used = defaultdict(set)
    for c, t in phi.items():
        if inst.department[c]:
            used[inst.department[c]].add(t)
    return float(sum(w for (d, c), w in inst.scores.items() if c in phi and phi[c] not in used[d]))


def _gap_value(slots, slots_per_day):
    masks = {}
    for t in slots:
        day, period = divmod(t, slots_per_day)
        masks[day] = masks.get(day, 0) | (1 << period)
    total = 0
    for mask in masks.values():
        total += mask.bit_length() - (mask & -mask).bit_length() + 1 - mask.bit_count()
    return total


def solve_sectioning(inst, phi, seconds=1.0, cfg=None):
    sections_by_family = defaultdict(list)
    section_slots = {}
    for sec in inst.sections:
        sections_by_family[inst.section_family[sec]].append(sec)
        section_slots[sec] = {phi[c] for c in inst.section_courses(sec)}
        if len(section_slots[sec]) != len(inst.section_courses(sec)):
            return None
    fixed = fixed_student_courses(inst)
    fixed_slots = {s: {phi[c] for c in cs if c in phi} for s, cs in fixed.items()}
    reqs = list(inst.requests)
    var_keys = []
    var_idx = {}
    req_vars = defaultdict(list)
    student_vars = defaultdict(list)
    for ri, r in enumerate(reqs):
        for sec in sections_by_family[r.family]:
            if r.locked_section and sec != r.locked_section:
                continue
            if section_slots[sec] & fixed_slots[r.student]:
                continue
            idx = len(var_keys)
            var_keys.append((ri, r.student, r.family, sec))
            var_idx[ri, sec] = idx
            req_vars[ri].append(idx)
            student_vars[r.student].append((idx, sec, r.family))
    for ri, r in enumerate(reqs):
        if r.required and not req_vars[ri]:
            return None
    n_x = len(var_keys)
    vars_by_section = defaultdict(list)
    for idx, (_, _, _, sec) in enumerate(var_keys):
        vars_by_section[sec].append(idx)
    sec_list = inst.sections
    dp_idx = {}
    dn_idx = {}
    n = n_x
    for sec in sec_list:
        dp_idx[sec] = n
        n += 1
        dn_idx[sec] = n
        n += 1
    req_by_student_family = {(req.student, req.family): i for i, req in enumerate(reqs)}
    dep_bonus_idx = {}
    fixed_bonus = []
    for student in inst.students:
        for di, dep in enumerate(inst.dependencies):
            if dep.required or dep.weight == 0.0 or (student, dep.to_family) not in req_by_student_family:
                continue
            if dep.from_course:
                if dep.from_course in fixed[student]:
                    fixed_bonus.append((student, di))
            elif (student, dep.from_family) in req_by_student_family:
                dep_bonus_idx[student, di] = n
                n += 1
    cvec = np.zeros(n, dtype=float)
    for (student, di), j in dep_bonus_idx.items():
        cvec[j] = -(cfg.w_optional if cfg else 80.0) * inst.dependencies[di].weight
    for student, di in fixed_bonus:
        dep = inst.dependencies[di]
        ri = req_by_student_family[student, dep.to_family]
        for j in req_vars[ri]:
            cvec[j] -= (cfg.w_optional if cfg else 80.0) * dep.weight
    for idx, (ri, s, fam, sec) in enumerate(var_keys):
        r = reqs[ri]
        slots = fixed_slots[s]
        added = section_slots[sec]
        delta_gap = _gap_value(slots | added, inst.slots_per_day) - _gap_value(slots, inst.slots_per_day)
        cvec[idx] = (cfg.section_gap_weight if cfg else 2.0) * delta_gap
        if not r.required:
            cvec[idx] -= (cfg.w_optional if cfg else 80.0) * r.weight
    for sec in sec_list:
        cvec[dp_idx[sec]] = 0.25
        cvec[dn_idx[sec]] = 0.25
    rows = []
    lbs = []
    ubs = []
    for ri, r in enumerate(reqs):
        entries = [(j, 1.0) for j in req_vars[ri]]
        if r.required:
            rows.append(entries)
            lbs.append(1.0)
            ubs.append(1.0)
        else:
            rows.append(entries)
            lbs.append(0.0)
            ubs.append(1.0)
    for sec in sec_list:
        entries = []
        for idx in vars_by_section[sec]:
            entries.append((idx, 1.0))
        rows.append(entries)
        lbs.append(0.0)
        ubs.append(float(inst.section_capacity[sec]))
    active_dep_sources = defaultdict(set)
    for s in inst.students:
        for dep in inst.dependencies:
            target_i = req_by_student_family.get((s, dep.to_family))
            if target_i is None:
                continue
            target_entries = [(j, 1.0) for j in req_vars[target_i]]
            if dep.from_course:
                active = dep.from_course in fixed[s]
                if active:
                    active_dep_sources[s, dep.to_family].add(None)
                    if dep.required:
                        rows.append(target_entries)
                        lbs.append(1.0)
                        ubs.append(1.0)
                continue
            source_i = req_by_student_family.get((s, dep.from_family))
            if source_i is None:
                continue
            active_dep_sources[s, dep.to_family].add(dep.from_family)
            if dep.required:
                rows.append(target_entries + [(j, -1.0) for j in req_vars[source_i]])
                lbs.append(0.0)
                ubs.append(np.inf)
    for (student, di), z in dep_bonus_idx.items():
        dep = inst.dependencies[di]
        source = req_vars[req_by_student_family[student, dep.from_family]]
        target = req_vars[req_by_student_family[student, dep.to_family]]
        rows.append([(z, 1.0)] + [(j, -1.0) for j in source])
        lbs.append(-np.inf)
        ubs.append(0.0)
        rows.append([(z, 1.0)] + [(j, -1.0) for j in target])
        lbs.append(-np.inf)
        ubs.append(0.0)
        rows.append([(z, 1.0)] + [(j, -1.0) for j in source] + [(j, -1.0) for j in target])
        lbs.append(-1.0)
        ubs.append(np.inf)
    for student, family in inst.synthetic_requests:
        if (student, family) not in active_dep_sources:
            continue
        sources = active_dep_sources[student, family]
        if None in sources:
            continue
        target_i = req_by_student_family[student, family]
        entries = [(j, 1.0) for j in req_vars[target_i]]
        for source in sources:
            si = req_by_student_family.get((student, source))
            if si is not None:
                entries.extend((j, -1.0) for j in req_vars[si])
        rows.append(entries)
        lbs.append(-np.inf)
        ubs.append(0.0)
    for student, choices in student_vars.items():
        by_time = defaultdict(list)
        for idx, sec, family in choices:
            for t in section_slots[sec]:
                by_time[t].append(idx)
        for indices in by_time.values():
            if len(indices) > 1:
                rows.append([(j, 1.0) for j in indices])
                lbs.append(0.0)
                ubs.append(1.0)
    req_count = Counter(r.family for r in reqs if r.required)
    for sec in sec_list:
        fam = inst.section_family[sec]
        target = req_count[fam] / max(1, len(sections_by_family[fam]))
        entries = [(idx, 1.0) for idx in vars_by_section[sec]]
        entries += [(dp_idx[sec], -1.0), (dn_idx[sec], 1.0)]
        rows.append(entries)
        lbs.append(target)
        ubs.append(target)
    rr = []
    cc = []
    dd = []
    for i, entries in enumerate(rows):
        for j, v in entries:
            rr.append(i)
            cc.append(j)
            dd.append(v)
    A = coo_matrix((dd, (rr, cc)), shape=(len(rows), n)).tocsr()
    integrality = np.zeros(n, dtype=int)
    integrality[:n_x] = 1
    for j in dep_bonus_idx.values():
        integrality[j] = 1
    lbv = np.zeros(n)
    ubv = np.full(n, np.inf)
    ubv[:n_x] = 1.0
    for j in dep_bonus_idx.values():
        ubv[j] = 1.0
    try:
        res = milp(cvec, integrality=integrality, bounds=Bounds(lbv, ubv), constraints=LinearConstraint(A, np.array(lbs), np.array(ubs)), options={'time_limit': max(0.05, seconds), 'mip_rel_gap': 0.0})
    except Exception:
        return None
    if res.x is None:
        return None
    x = res.x
    assignment = defaultdict(dict)
    optional_score = 0.0
    optional_count = 0
    for idx, (ri, s, fam, sec) in enumerate(var_keys):
        if x[idx] > 0.5:
            assignment[s][fam] = sec
            if not reqs[ri].required:
                optional_score += reqs[ri].weight
                optional_count += 1
    for s in inst.students:
        for dep in inst.dependencies:
            active = (dep.from_course in fixed[s]) if dep.from_course else (dep.from_family in assignment[s])
            if active and dep.required and dep.to_family not in assignment[s]:
                return None
            if (s, dep.to_family) in inst.synthetic_requests and dep.to_family in assignment[s]:
                activating = any((d.from_course in fixed[s] if d.from_course else d.from_family in assignment[s]) for d in inst.dependencies if d.to_family == dep.to_family)
                if not activating:
                    return None
    for s in inst.students:
        for dep in inst.dependencies:
            if dep.required:
                continue
            source_taken = dep.from_course in fixed[s] if dep.from_course else dep.from_family in assignment[s]
            if source_taken and dep.to_family in assignment[s]:
                optional_score += dep.weight
                optional_count += 1
    for ri, r in enumerate(reqs):
        if r.required and r.family not in assignment[r.student]:
            return None
    loads = Counter()
    for s, fs in assignment.items():
        for sec in fs.values():
            loads[sec] += 1
    balance = 0.0
    for fam, secs in sections_by_family.items():
        if not secs:
            continue
        vals = [loads[s] for s in secs]
        m = sum(vals) / len(vals)
        balance += sum(abs(x - m) for x in vals)
    refinements = 0
    if cfg is not None:
        by_student_req = defaultdict(dict)
        for req in reqs:
            by_student_req[req.student][req.family] = req
        for _ in range(cfg.section_refine_rounds):
            changed = False
            for student in inst.students:
                selected = assignment.get(student, {})
                if not selected:
                    continue
                for family, old_sec in list(selected.items()):
                    req = by_student_req[student][family]
                    if req.locked_section:
                        continue
                    baseline = set(fixed_slots[student])
                    for fam, sec in selected.items():
                        if fam != family:
                            baseline.update(section_slots[sec])
                    if len(baseline) != len(fixed_slots[student]) + sum(len(section_slots[sec]) for fam, sec in selected.items() if fam != family):
                        continue
                    old_slots = baseline | section_slots[old_sec]
                    old_g = _gap_value(old_slots, inst.slots_per_day)
                    current_cost = cfg.w_student_sq * old_g * old_g + cfg.w_student_gaps * old_g
                    winner, winner_cost = None, current_cost
                    for sec in sections_by_family[family]:
                        if sec == old_sec or loads[sec] >= inst.section_capacity[sec] or section_slots[sec] & baseline:
                            continue
                        g = _gap_value(baseline | section_slots[sec], inst.slots_per_day)
                        cost = cfg.w_student_sq * g * g + cfg.w_student_gaps * g
                        cost += 0.02 * (loads[sec] - loads[old_sec] + 1)
                        if cost + 1e-8 < winner_cost:
                            winner, winner_cost = sec, cost
                    if winner is not None:
                        selected[family] = winner
                        loads[old_sec] -= 1
                        loads[winner] += 1
                        refinements += 1
                        changed = True
            if not changed:
                break
        balance = 0.0
        for fam, secs in sections_by_family.items():
            avg = sum(loads[sec] for sec in secs) / len(secs)
            balance += sum(abs(loads[sec] - avg) for sec in secs)
    return {'assignment': {s: dict(v) for s, v in assignment.items()}, 'loads': dict(loads), 'optional_score': optional_score, 'optional_count': optional_count, 'balance': balance, 'optimal': res.status == 0 and not refinements, 'milp_proxy_optimal': res.status == 0, 'refinements': refinements, 'status': int(res.status), 'mip_gap': float(getattr(res, 'mip_gap', math.nan))}


def improve_student_section_swaps(inst, phi, sectioning, cfg, deadline):
    if not sectioning or cfg.student_swap_seconds <= 0 or not inst.students:
        return None, 0
    assignments = {student: dict(families)
                   for student, families in sectioning['assignment'].items()}
    section_slots = {sec: {phi[c] for c in inst.section_courses(sec)}
                     for sec in inst.sections}
    fixed_slots = {student: {phi[c] for c in inst._fixed_courses[student]}
                   for student in inst.students}
    locked = {(r.student, r.family) for r in inst.requests if r.locked_section}
    members = defaultdict(set)
    for student, fams in assignments.items():
        for sec in fams.values():
            members[sec].add(student)
    student_slots = {}
    student_gaps = {}
    for student in inst.students:
        occupied = set(fixed_slots[student])
        for sec in assignments.get(student, {}).values():
            occupied.update(section_slots[sec])
        student_slots[student] = occupied
        student_gaps[student] = _gap_value(occupied, inst.slots_per_day)
    initial_max = max(student_gaps.values(), default=0)
    changed = 0

    def cost(slots):
        g = _gap_value(slots, inst.slots_per_day)
        counts = [0] * ((inst.T + inst.slots_per_day - 1) // inst.slots_per_day)
        for t in slots:
            counts[t // inst.slots_per_day] += 1
        mean = len(slots) / len(counts)
        imbalance = sum((n - mean) ** 2 for n in counts)
        return cfg.w_student_sq * g * g + cfg.w_student_gaps * g + cfg.w_daily * imbalance, g

    for _ in range(2):
        if time.perf_counter() >= deadline:
            break
        any_change = False
        students = sorted(assignments, key=lambda student: student_gaps[student], reverse=True)
        for student in students:
            if time.perf_counter() >= deadline:
                break
            for family, old_sec in list(assignments[student].items()):
                if (student, family) in locked:
                    continue
                other_old = student_slots[student] - section_slots[old_sec]
                # A swap is allowed only if the family has no time overlap with other lessons.
                if len(other_old) + len(section_slots[old_sec]) != len(student_slots[student]):
                    continue
                previous_cost, old_g = cost(student_slots[student])
                winner = None
                for new_sec in inst.family_sections(family):
                    if new_sec == old_sec or other_old & section_slots[new_sec]:
                        continue
                    new_student_slots = other_old | section_slots[new_sec]
                    new_cost, new_g = cost(new_student_slots)
                    if new_g > initial_max:
                        continue
                    for other_student in tuple(members[new_sec]):
                        if other_student == student or (other_student, family) in locked:
                            continue
                        other_base = student_slots[other_student] - section_slots[new_sec]
                        if (len(other_base) + len(section_slots[new_sec]) != len(student_slots[other_student])
                                or other_base & section_slots[old_sec]):
                            continue
                        other_new_slots = other_base | section_slots[old_sec]
                        other_cost, other_g = cost(other_new_slots)
                        if other_g > initial_max:
                            continue
                        existing_other_cost, _ = cost(student_slots[other_student])
                        gain = (previous_cost + existing_other_cost) - (new_cost + other_cost)
                        if gain > 1e-7 and (winner is None or gain > winner[0]):
                            winner = (gain, new_sec, other_student, new_student_slots,
                                      other_new_slots, new_g, other_g)
                    if time.perf_counter() >= deadline:
                        break
                if winner:
                    _, new_sec, other_student, new_slots, other_slots, g_s, g_o = winner
                    assignments[student][family] = new_sec
                    assignments[other_student][family] = old_sec
                    members[old_sec].remove(student)
                    members[old_sec].add(other_student)
                    members[new_sec].remove(other_student)
                    members[new_sec].add(student)
                    student_slots[student], student_slots[other_student] = new_slots, other_slots
                    student_gaps[student], student_gaps[other_student] = g_s, g_o
                    changed += 1
                    any_change = True
                    break
        if not any_change:
            break
    if not changed:
        return None, 0
    result = dict(sectioning)
    result['assignment'] = assignments
    result['optimal'] = False
    result['refinements'] = sectioning.get('refinements', 0) + changed
    result['student_swaps'] = changed
    return result, changed


def course_students(inst, sectioning):
    out = {c: set() for c in inst.courses}
    fixed = fixed_students_by_course(inst)
    for c in inst.courses:
        out[c].update(fixed[c])
    if sectioning:
        inv = defaultdict(set)
        for s, fs in sectioning['assignment'].items():
            for sec in fs.values():
                inv[sec].add(s)
        for c in inst.courses:
            sec = inst.section_of[c]
            if sec:
                out[c].update(inv[sec])
    return out


def course_size(inst, c, sectioning):
    sec = inst.section_of[c]
    if sec and sectioning:
        return int(sectioning['loads'].get(sec, 0))
    if sec and sectioning is None:
        return inst.section_capacity[sec]
    if inst.group_of.get(c):
        return len(inst._fixed_attendees[c])
    if inst.explicit_size[c] > 0:
        return inst.explicit_size[c]
    if inst.students:
        return len(fixed_students_by_course(inst)[c])
    return 0


def room_permits(inst, rooms, c, t, r, sectioning):
    if r not in rooms.equipment or t not in rooms.available[r]:
        return False
    if not inst.required_equipment[c] <= rooms.equipment[r]:
        return False
    allowed = rooms.allowed_subjects[r]
    if allowed is not None and inst.subject[c] not in allowed:
        return False
    if course_size(inst, c, sectioning) > rooms.capacity[r]:
        return False
    if c in inst.lock_room and inst.lock_room[c] != r:
        return False
    return True


def assign_rooms(inst, rooms, phi, sectioning, cfg, previous=None):
    rho = {}
    load = Counter()
    previous = previous or {}
    for t in range(inst.T):
        cs = [c for c in inst.courses if phi[c] == t]
        if not cs:
            continue
        rs = rooms.rooms
        if len(cs) > len(rs):
            return None
        M = np.full((len(cs), len(rs)), 1e9, dtype=float)
        for i, c in enumerate(cs):
            p = inst.teacher[c]
            req = inst.required_equipment[c]
            size = course_size(inst, c, sectioning)
            for j, r in enumerate(rs):
                if not room_permits(inst, rooms, c, t, r, sectioning):
                    continue
                cap = rooms.capacity[r]
                waste = 0.0 if cap >= 10**8 or size <= 0 else max(0.0, (cap - size) / max(1, cap))
                special = 1.0 if not req and rooms.equipment[r] else 0.0
                avail = max(1, len(rooms.available[r]))
                balance = load[r] / avail
                change = 0.0
                prev_courses = [q for q in inst.prof_courses(p) if q in rho and phi[q] // inst.slots_per_day == t // inst.slots_per_day]
                if prev_courses:
                    q = max(prev_courses, key=lambda z: phi[z])
                    if r != rho[q]:
                        change = inst.prof_room_weight.get(p, 1.0) * (1.0 if t == phi[q] + 1 else 0.25)
                if c in previous and previous[c] == r:
                    change -= 0.25
                M[i, j] = cfg.w_room_waste * waste + cfg.w_special_room * special + cfg.w_room_balance * balance + cfg.w_room_change * change
        ri, cj = linear_sum_assignment(M)
        if len(ri) != len(cs) or any(M[i, j] >= 1e8 for i, j in zip(ri, cj)):
            return None
        for i, j in zip(ri, cj):
            rho[cs[i]] = rs[j]
            load[rs[j]] += 1
    if not room_limits_ok(inst, phi, rho):
        for day in range(math.ceil(inst.T / inst.slots_per_day)):
            better = optimize_room_day(inst, rooms, phi, sectioning, rho, cfg, day, min(0.5, cfg.room_day_seconds))
            if better is not None:
                rho = better
        if not room_limits_ok(inst, phi, rho):
            return None
    return rho


def room_change_details(inst, phi, rho):
    weighted = 0.0
    count = 0
    day_counts = Counter()
    for p in inst.professors:
        by_day = defaultdict(list)
        for c in inst.prof_courses(p):
            if c in phi and c in rho:
                by_day[phi[c] // inst.slots_per_day].append(c)
        for d, cs in by_day.items():
            cs.sort(key=lambda c: phi[c])
            for a, b in zip(cs, cs[1:]):
                if rho[a] != rho[b]:
                    count += 1
                    day_counts[p, d] += 1
                    consecutive = phi[b] == phi[a] + 1
                    weighted += inst.prof_room_weight.get(p, 1.0) * (1.0 if consecutive else 0.25)
    return count, weighted, day_counts


def room_limits_ok(inst, phi, rho):
    if not inst.prof_room_max:
        return True
    _, _, day_counts = room_change_details(inst, phi, rho)
    return all(day_counts[p, d] <= limit for p, limit in inst.prof_room_max.items() for d in range(math.ceil(inst.T / inst.slots_per_day)))


def room_metrics(inst, rooms, phi, rho, sectioning):
    waste = 0.0
    special = 0
    for c, r in rho.items():
        size = course_size(inst, c, sectioning)
        cap = rooms.capacity[r]
        if cap < 10**8 and size > 0:
            waste += max(0.0, (cap - size) / max(1, cap))
        if not inst.required_equipment[c] and rooms.equipment[r]:
            special += 1
    load = Counter(rho.values())
    by_type = defaultdict(list)
    for r in rooms.rooms:
        by_type[rooms.room_type[r]].append(load[r] / max(1, len(rooms.available[r])))
    imbalance = 0.0
    for vals in by_type.values():
        if vals:
            m = sum(vals) / len(vals)
            imbalance += sum((x - m) ** 2 for x in vals)
    changes = room_change_details(inst, phi, rho)[0]
    return waste, imbalance, special, changes


def room_objective(inst, rooms, phi, rho, sectioning, cfg):
    waste, imbalance, special, changes = room_metrics(inst, rooms, phi, rho, sectioning)
    weighted = room_change_details(inst, phi, rho)[1]
    return cfg.w_room_waste * waste + cfg.w_room_balance * imbalance + cfg.w_special_room * special + cfg.w_room_change * weighted


def optimize_room_day(inst, rooms, phi, sectioning, rho, cfg, day, seconds):
    cs = [c for c in inst.courses if c in phi and phi[c] // inst.slots_per_day == day]
    if not cs:
        return rho
    keys = []
    course_idx = defaultdict(list)
    by_room_slot = defaultdict(list)
    idx = {}
    for c in cs:
        t = phi[c]
        for r in rooms.rooms:
            if room_permits(inst, rooms, c, t, r, sectioning):
                j = len(keys)
                keys.append((c, r))
                idx[c, r] = j
                course_idx[c].append(j)
                by_room_slot[r, t].append(j)
        if not course_idx[c]:
            return None
    transitions = []
    for p in inst.professors:
        pc = sorted([c for c in cs if inst.teacher[c] == p], key=lambda c: phi[c])
        for a, b in zip(pc, pc[1:]):
            transitions.append((p, a, b, phi[b] == phi[a] + 1))
    x_count = len(keys)
    n = x_count + len(transitions)
    entries = []
    lbs, ubs = [], []
    def add(row, lo, hi):
        if row:
            entries.append(row)
            lbs.append(lo)
            ubs.append(hi)
    for c in cs:
        add([(j, 1.0) for j in course_idx[c]], 1.0, 1.0)
    for js in by_room_slot.values():
        if len(js) > 1:
            add([(j, 1.0) for j in js], 0.0, 1.0)
    for k, (p, a, b, consecutive) in enumerate(transitions):
        z = x_count + k
        union = {r for c, r in keys if c in {a, b}}
        for r in union:
            ia, ib = idx.get((a, r)), idx.get((b, r))
            pair = [(z, -1.0)]
            if ia is not None:
                pair.append((ia, 1.0))
            if ib is not None:
                pair.append((ib, -1.0))
            add(pair, -np.inf, 0.0)
            other = [(z, -1.0)]
            if ib is not None:
                other.append((ib, 1.0))
            if ia is not None:
                other.append((ia, -1.0))
            add(other, -np.inf, 0.0)
    for p, limit in inst.prof_room_max.items():
        which = [x_count + k for k, (q, a, b, consecutive) in enumerate(transitions) if p == q]
        if which:
            add([(j, 1.0) for j in which], 0.0, float(limit))
    group_load = Counter(rho.values())
    usage = {r: group_load[r] / max(1, len(rooms.available[r])) for r in rooms.rooms}
    typ_mean = {}
    for typ in set(rooms.room_type.values()):
        rr = [r for r in rooms.rooms if rooms.room_type[r] == typ]
        typ_mean[typ] = sum(usage[r] for r in rr) / len(rr)
    cvec = np.zeros(n)
    for j, (c, r) in enumerate(keys):
        cap = rooms.capacity[r]
        size = course_size(inst, c, sectioning)
        waste = (cap - size) / cap if cap < 10**8 and size > 0 else 0.0
        special = 1.0 if not inst.required_equipment[c] and rooms.equipment[r] else 0.0
        grad = 2 * (usage[r] - typ_mean[rooms.room_type[r]]) / max(1, len(rooms.available[r]))
        cvec[j] = cfg.w_room_waste * waste + cfg.w_special_room * special + cfg.w_room_balance * grad
    for k, (p, a, b, consecutive) in enumerate(transitions):
        cvec[x_count + k] = cfg.w_room_change * inst.prof_room_weight.get(p, 1.0) * (1.0 if consecutive else 0.25)
    rr, cc, dd = [], [], []
    for i, row in enumerate(entries):
        for j, value in row:
            rr.append(i)
            cc.append(j)
            dd.append(value)
    A = coo_matrix((dd, (rr, cc)), shape=(len(entries), n)).tocsr()
    try:
        res = milp(cvec, integrality=np.ones(n, dtype=int), bounds=Bounds(np.zeros(n), np.ones(n)), constraints=LinearConstraint(A, np.asarray(lbs), np.asarray(ubs)), options={'time_limit': max(0.04, seconds), 'mip_rel_gap': 0.02})
    except (ValueError, RuntimeError):
        return None
    if res.x is None:
        return None
    candidate = dict(rho)
    for c in cs:
        chosen = [keys[j][1] for j in course_idx[c] if res.x[j] > 0.5]
        if len(chosen) != 1:
            return None
        candidate[c] = chosen[0]
    if day in range(math.ceil(inst.T / inst.slots_per_day)):
        _, _, day_counts = room_change_details(inst, phi, candidate)
        if any(day_counts[p, day] > limit for p, limit in inst.prof_room_max.items()):
            return None
    return candidate


def optimize_rooms_week(inst, rooms, ev, cfg, deadline):
    rho = dict(ev['rho'])
    phi, sectioning = ev['phi'], ev['sectioning']
    old_cost = room_objective(inst, rooms, phi, rho, sectioning, cfg)
    applied = 0
    attempted = 0
    for day in range(math.ceil(inst.T / inst.slots_per_day)):
        if time.perf_counter() >= deadline:
            break
        attempted += 1
        seconds = min(cfg.room_day_seconds, max(0.04, deadline - time.perf_counter()))
        result = optimize_room_day(inst, rooms, phi, sectioning, rho, cfg, day, seconds)
        if result is None:
            continue
        cost = room_objective(inst, rooms, phi, result, sectioning, cfg)
        if cost + 1e-7 < old_cost:
            rho, old_cost = result, cost
            applied += 1
    return rho, attempted, applied


def refresh_room_eval(inst, rooms, ev, rho, cfg):
    out = dict(ev)
    waste, rimb, special, changes = room_metrics(inst, rooms, ev['phi'], rho, ev['sectioning'])
    penalty = room_objective(inst, rooms, ev['phi'], rho, ev['sectioning'], cfg)
    out['quality'] = ev['quality'] - penalty + ev['room_penalty']
    out['key'] = (out['quality'], ev['wish_score'] + ev['access_score'], -ev['gaps']['student_max'], -ev['gaps']['student_sq'], -ev['gaps']['student_total'], -ev['gaps']['teacher_max'], -ev['gaps']['teacher_sq'], ev['teacher_preference'], -ev['gaps']['teacher_total'], -ev['gaps']['cohort_total'], -changes, -waste, -rimb, -special)
    out.update(rho=rho, room_waste=waste, room_imbalance=rimb, special_room_misuse=special, room_changes=changes, room_penalty=penalty, room_change_cost=room_change_details(inst, ev['phi'], rho)[1])
    return out


def student_course_sets(inst, sectioning):
    out = fixed_student_courses(inst)
    if sectioning:
        for s, fs in sectioning['assignment'].items():
            for sec in fs.values():
                out[s].update(inst.section_courses(sec))
    return out


def gap_metrics(inst, phi, sectioning):
    sc = student_course_sets(inst, sectioning)
    sg = {}
    daily_imbalance = 0.0
    for s in inst.students:
        slots = [phi[c] for c in sc.get(s, set()) if c in phi]
        g = _gap_value(slots, inst.slots_per_day)
        sg[s] = g
        loads = [0] * max(1, math.ceil(inst.T / inst.slots_per_day))
        for t in slots:
            loads[t // inst.slots_per_day] += 1
        m = sum(loads) / len(loads)
        daily_imbalance += sum((x - m) ** 2 for x in loads)
    tg = {}
    for p in inst.professors:
        tg[p] = _gap_value([phi[c] for c in inst.prof_courses(p) if c in phi], inst.slots_per_day)
    cg = {}
    for d in inst.departments:
        cg[d] = _gap_value([phi[c] for c in inst.dept_courses(d) if c in phi], inst.slots_per_day)
    return {'student_by_id': sg, 'student_total': sum(sg.values()), 'student_max': max(sg.values(), default=0), 'student_sq': sum(x * x for x in sg.values()), 'teacher_by_id': tg, 'teacher_total': sum(tg.values()), 'teacher_max': max(tg.values(), default=0), 'teacher_sq': sum(x * x for x in tg.values()), 'cohort_total': sum(cg.values()), 'daily_imbalance': daily_imbalance}


def teacher_preference_score(inst, phi):
    return sum(inst.teacher_pref.get((inst.teacher[c], t), 0.0) for c, t in phi.items())


def hard_time_feasible(inst, phi, adj, partial=False):
    for c, t in phi.items():
        if t not in inst.allowed_slots(c):
            return False
    by_slot = defaultdict(set)
    for c, t in phi.items():
        if by_slot[t] & adj[c]:
            return False
        by_slot[t].add(c)
    return inst.links_ok(phi, partial=partial)


def evaluate(inst, rooms, phi, cfg, stats, previous_rho=None, sectioning_override=None, failure=None):
    if set(phi) != set(inst.courses):
        if failure is not None: failure.append('incomplete')
        return None
    adj = hard_adjacency(inst)
    if not hard_time_feasible(inst, phi, adj, partial=False):
        if failure is not None: failure.append('time')
        return None
    remaining = max(0.05, cfg.section_seconds)
    sectioning = (sectioning_override if sectioning_override is not None
                  else solve_sectioning(inst, phi, remaining, cfg))
    if inst.requests and sectioning is None:
        if failure is not None: failure.append('section')
        return None
    rho = assign_rooms(inst, rooms, phi, sectioning, cfg, previous_rho)
    if rho is None:
        if failure is not None: failure.append('room')
        return None
    gaps = gap_metrics(inst, phi, sectioning)
    waste, rimb, special, changes = room_metrics(inst, rooms, phi, rho, sectioning)
    wish = sectioning['optional_score'] if sectioning else 0.0
    access = access_score(inst, phi)
    pref = teacher_preference_score(inst, phi)
    room_penalty = room_objective(inst, rooms, phi, rho, sectioning, cfg)
    quality = cfg.w_optional * (wish + access) - cfg.w_student_max * gaps['student_max'] - cfg.w_student_sq * gaps['student_sq'] - cfg.w_student_gaps * gaps['student_total'] - cfg.w_teacher_max * gaps['teacher_max'] - cfg.w_teacher_sq * gaps['teacher_sq'] - cfg.w_teacher_gaps * gaps['teacher_total'] + cfg.w_teacher_pref * pref - cfg.w_daily * gaps['daily_imbalance'] - room_penalty
    key = (quality, wish + access, -gaps['student_max'], -gaps['student_sq'], -gaps['student_total'], -gaps['teacher_max'], -gaps['teacher_sq'], pref, -gaps['teacher_total'], -gaps['cohort_total'], -changes, -waste, -rimb, -special)
    return {'phi': dict(phi), 'rho': rho, 'sectioning': sectioning, 'key': key, 'quality': quality, 'gaps': gaps, 'wish_score': wish, 'access_score': access, 'teacher_preference': pref, 'room_waste': waste, 'room_imbalance': rimb, 'special_room_misuse': special, 'room_changes': changes, 'room_change_cost': room_change_details(inst, phi, rho)[1], 'room_penalty': room_penalty, 'potential_overlap': potential_overlap(inst, phi, stats)}


class _ConstructState:
    def __init__(self, inst, rooms, rng, adjacency, stats, seed_assignment, cfg=None):
        self.propagator = _PupilFeasibilityPropagator(inst, cfg.propagation_match_interval, cfg.propagation_match_limit, cfg.incremental_propagation) if cfg is not None and cfg.pupil_propagation and inst.requests and not seed_assignment else None
        self.inst, self.rooms, self.rng, self.adj, self.stats = inst, rooms, rng, adjacency, stats
        self.courses = tuple(inst.courses)
        self.phi = {}
        self.occupied = [set() for _ in range(inst.T)]
        self.available_room_masks = [0] * inst.T
        room_index = {r: i for i, r in enumerate(rooms.rooms)}
        for r, i in room_index.items():
            for t in rooms.available[r]:
                self.available_room_masks[t] |= 1 << i
        self.room_count = [x.bit_count() for x in self.available_room_masks]
        self.course_room_masks = {}
        for c in self.courses:
            mask = 0
            size = inst.section_capacity[inst.section_of[c]] if inst.section_of[c] else (
                len(inst._fixed_attendees[c]) if inst.group_of.get(c) else (inst.explicit_size[c] if inst.explicit_size[c] > 0 else len(inst._fixed_attendees[c])))
            for r, i in room_index.items():
                allowed = rooms.allowed_subjects[r]
                if (inst.required_equipment[c] <= rooms.equipment[r]
                    and (allowed is None or inst.subject[c] in allowed)
                    and size <= rooms.capacity[r]
                    and (c not in inst.lock_room or inst.lock_room[c] == r)):
                    mask |= 1 << i
            self.course_room_masks[c] = mask
        self.domains = {}
        for c in self.courses:
            room_mask = self.course_room_masks[c]
            domain = 0
            for t in inst.allowed_slots(c):
                if room_mask & self.available_room_masks[t]:
                    domain |= 1 << t
            self.domains[c] = domain
        self.initially_infeasible = any(not v for v in self.domains.values())
        self.relations = defaultdict(list)
        rel_entries = []
        for link in inst.links:
            def link_pred(a, b, link=link):
                gap = b - a
                return (gap >= link.min_gap and (link.max_gap is None or gap <= link.max_gap)
                        and (not link.same_day or a // inst.slots_per_day == b // inst.slots_per_day))
            rel_entries.append((link.first, link.second, link_pred))
        for rel in inst.relations:
            def rel_pred(a, b, kind=rel.kind):
                return relation_ok(kind, a, b, inst.slots_per_day)
            rel_entries.append((rel.first, rel.second, rel_pred))
        grouped = defaultdict(list)
        for a, b, predicate in rel_entries:
            grouped[a, b].append(predicate)
        for (a, b), predicates in grouped.items():
            forwards = []
            backwards = []
            for t in range(inst.T):
                forwards.append(sum(1 << u for u in range(inst.T) if all(p(t, u) for p in predicates)))
                backwards.append(sum(1 << u for u in range(inst.T) if all(p(u, t) for p in predicates)))
            self.relations[a].append((b, tuple(forwards)))
            self.relations[b].append((a, tuple(backwards)))
        self.tie = {c: rng.random() for c in self.courses}
        self.student_attendees = {c: set(inst._fixed_attendees[c]) for c in self.courses}
        if seed_assignment:
            inv = defaultdict(set)
            for student, families in seed_assignment.items():
                for section in families.values():
                    inv[section].add(student)
            for c in self.courses:
                section = inst.section_of[c]
                if section:
                    self.student_attendees[c].update(inv[section])
        n_days = (inst.T + inst.slots_per_day - 1) // inst.slots_per_day
        self.student_bits = {s: [0] * n_days for s in inst.students}
        self.prof_bits = {p: [0] * n_days for p in inst.professors}
        self.dept_bits = {d: [0] * n_days for d in inst.departments}
        self.total_count = len(self.courses)
        self.nodes = 0
        self.incremental_mrv = (cfg.incremental_mrv and len(self.courses) >= 500) if cfg is not None else len(self.courses) >= 500
        self.conflict_pressure = Counter()
        self.domain_version = Counter()
        self.mrv_heap = []
        if self.incremental_mrv:
            self._rebuild_heap()

    def _rank(self, c):
        # Dynamic weighted-degree tie break: repeat offenders are considered
        # before unrelated lessons with the same number of choices.
        return (self.domains[c].bit_count(),
                -len(self.adj[c]) - min(100, self.conflict_pressure[c]),
                self.tie[c])

    def _rebuild_heap(self):
        self.mrv_heap = [(self._rank(c), self.domain_version[c], c)
                         for c in self.courses if c not in self.phi]
        heapq.heapify(self.mrv_heap)

    def _refresh(self, c):
        if not self.incremental_mrv:
            return
        self.domain_version[c] += 1
        if c not in self.phi:
            heapq.heappush(self.mrv_heap, (self._rank(c), self.domain_version[c], c))

    def _bump_conflict(self, c, related=()):
        # An ordering heuristic only: it never removes a valid timetable.
        self.conflict_pressure[c] += 2
        self._refresh(c)
        for q in related:
            self.conflict_pressure[q] += 1
            self._refresh(q)

    @staticmethod
    def _delta_span(mask, pos):
        if not mask:
            return 0
        if mask & (1 << pos):
            return 0
        low = (mask & -mask).bit_length() - 1
        high = mask.bit_length() - 1
        if pos < low:
            return low - pos - 1
        if pos > high:
            return pos - high - 1
        return -1

    def choose(self):
        if self.incremental_mrv:
            # Rebuild occasionally to bound stale heap entries after long DFS.
            if len(self.mrv_heap) > 12 * len(self.courses):
                self._rebuild_heap()
            while self.mrv_heap:
                rank, version, c = heapq.heappop(self.mrv_heap)
                if c in self.phi or version != self.domain_version[c]:
                    continue
                heapq.heappush(self.mrv_heap, (rank, version, c))
                return c if self.domains[c] else None
            return None
        best, best_rank = None, None
        for c in self.courses:
            if c in self.phi:
                continue
            mask = self.domains[c]
            if not mask:
                return None
            rank = self._rank(c)
            if best_rank is None or rank < best_rank:
                best, best_rank = c, rank
                if mask.bit_count() == 1:
                    break
        return best

    def ordered_times(self, c):
        inst, spd = self.inst, self.inst.slots_per_day
        teacher, department = inst.teacher[c], inst.department[c]
        p_bits = self.prof_bits[teacher]
        d_bits = self.dept_bits.get(department)
        attendees = self.student_attendees[c]
        section = inst.section_of[c]
        family = inst.section_family.get(section) if section else None
        unassigned_neighbours = [q for q in self.adj[c] if q not in self.phi]
        pressure = [0] * inst.T
        active = self.domains[c]
        for q in unassigned_neighbours:
            bits = self.domains[q] & active
            while bits:
                bit = bits & -bits
                bits -= bit
                pressure[bit.bit_length() - 1] += 1
        scored = []
        domain = active
        while domain:
            bit = domain & -domain
            domain -= bit
            t = bit.bit_length() - 1
            day, period = divmod(t, spd)
            block = pressure[t]
            overlap = sum(overlap_weight(inst, c, q, self.stats) for q in self.occupied[t])
            parallel = 0.0
            if family:
                for q in self.occupied[t]:
                    other = inst.section_of[q]
                    other_family = inst.section_family.get(other) if other else None
                    if other_family and family != other_family and self.stats[1].get(tuple(sorted((family, other_family))), 0) == 0:
                        parallel += 1
            compact = self._delta_span(p_bits[day], period)
            if d_bits is not None:
                compact += self._delta_span(d_bits[day], period)
            student_compact = (sum(self._delta_span(self.student_bits[s][day], period) for s in attendees) / len(attendees)) if attendees else 0.0
            pref = inst.teacher_pref.get((teacher, t), 0.0)
            score = (block + 4.0 * overlap - 0.8 * parallel + 0.6 * compact
                     + 2.5 * student_compact - 0.12 * len(self.occupied[t]) - 1.5 * pref
                     + self.rng.random() * 0.02)
            scored.append((score, t))
        scored.sort()
        return [t for _, t in scored]

    def _room_matching_possible(self, t):
        courses = self.occupied[t]
        if len(courses) < 2:
            return True
        available = self.available_room_masks[t]
        masks = {c: self.course_room_masks[c] & available for c in courses}
        if any(not mask for mask in masks.values()):
            return False
        order = sorted(courses, key=lambda c: masks[c].bit_count())
        used = 0
        for c in order:
            choice = masks[c] & ~used
            if not choice:
                break
            used |= choice & -choice
        else:
            return True
        # Non-recursive Kuhn matching, adapted from MIT-licensed source:
        # https://algorithm.tamnd.com/kuhn-algorithm/
        # The greedy pass above avoids invoking this fallback in easy slots.
        neighbors = []
        for c in order:
            mask = masks[c]
            choices = []
            while mask:
                bit = mask & -mask
                mask -= bit
                choices.append(bit.bit_length() - 1)
            neighbors.append(choices)
        return has_full_bipartite_matching(neighbors, len(self.rooms.rooms))

    def place(self, c, t):
        bit = 1 << t
        if not self.domains[c] & bit or len(self.occupied[t]) >= self.room_count[t]:
            return None
        if self.occupied[t] & self.adj[c]:
            return None
        self.phi[c] = t
        self.occupied[t].add(c)
        changes = {}
        valid = True
        for q in self.adj[c]:
            if q in self.phi:
                continue
            old = self.domains[q]
            new = old & ~bit
            if new != old:
                changes[q] = old
                self.domains[q] = new
                self._refresh(q)
                if not new:
                    valid = False
                    break
        if valid:
            for q, rel_masks in self.relations[c]:
                if q in self.phi:
                    if not rel_masks[t] & (1 << self.phi[q]):
                        valid = False
                        break
                    continue
                old = self.domains[q]
                new = old & rel_masks[t]
                if new != old:
                    changes.setdefault(q, old)
                    self.domains[q] = new
                    self._refresh(q)
                    if not new:
                        valid = False
                        break
        if valid:
            valid = self._room_matching_possible(t)
        if valid and self.propagator is not None:
            valid = self.propagator.push(c, t, len(self.phi))
        if not valid:
            self.occupied[t].remove(c)
            self.phi.pop(c)
            for q, old in changes.items():
                self.domains[q] = old
                self._refresh(q)
            self._bump_conflict(c, (q for q in changes if not self.domains[q] & ~(1 << t)))
            return None
        spd = self.inst.slots_per_day
        day, period = divmod(t, spd)
        period_bit = 1 << period
        self.prof_bits[self.inst.teacher[c]][day] |= period_bit
        department = self.inst.department[c]
        if department in self.dept_bits and self.inst.hard_group[c]:
            self.dept_bits[department][day] |= period_bit
        for student in self.student_attendees[c]:
            self.student_bits[student][day] |= period_bit
        return changes

    def unplace(self, c, t, changes):
        if self.propagator is not None:
            self.propagator.pop()
        self.phi.pop(c)
        self.occupied[t].remove(c)
        self._refresh(c)
        for q, old in changes.items():
            self.domains[q] = old
            self._refresh(q)
        day, period = divmod(t, self.inst.slots_per_day)
        bit = ~(1 << period)
        self.prof_bits[self.inst.teacher[c]][day] &= bit
        department = self.inst.department[c]
        if department in self.dept_bits and self.inst.hard_group[c]:
            self.dept_bits[department][day] &= bit
        for student in self.student_attendees[c]:
            self.student_bits[student][day] &= bit


def construct(inst, rooms, cfg, rng, adj, stats, deadline, seed_assignment=None, trace=None):
    state = _ConstructState(inst, rooms, rng, adj, stats, seed_assignment, cfg)
    def propagation_stats():
        p = state.propagator
        return {} if p is None else {'pupil_checks': p.checks, 'pupil_prunes': p.prunes, 'capacity_checks': p.matching_checks, 'capacity_prunes': p.matching_prunes, 'witness_recomputes': p.witness_recomputes, 'watch_skips': p.watch_skips, 'family_flow_checks': p.family_flow_checks}
    if state.initially_infeasible:
        if trace is not None:
            trace.update(reason='empty_initial_domain', depth=0, nodes=0, partial={})
        return None
    max_nodes = max(20000, 300 * len(inst.courses))
    root = state.choose()
    if root is None:
        if trace is not None:
            trace.update(reason='empty_root_domain', depth=0, nodes=0, partial={})
        return None
    best_depth = 0
    best_partial = {}
    stack = [{'course': root, 'options': state.ordered_times(root), 'next': 0, 'chosen': None, 'changes': None}]
    while stack and time.perf_counter() < deadline and state.nodes < max_nodes:
        frame = stack[-1]
        c = frame['course']
        if frame['chosen'] is not None:
            state.unplace(c, frame['chosen'], frame['changes'])
            frame['chosen'] = None
        if frame['next'] >= len(frame['options']):
            stack.pop()
            continue
        t = frame['options'][frame['next']]
        frame['next'] += 1
        state.nodes += 1
        changes = state.place(c, t)
        if changes is None:
            continue
        frame['chosen'] = t
        frame['changes'] = changes
        if trace is not None and len(state.phi) > best_depth:
            best_depth = len(state.phi)
            if best_depth == state.total_count or best_depth % 4 == 0:
                best_partial = dict(state.phi)
        if len(state.phi) == state.total_count:
            if trace is not None:
                trace.update(reason='complete', depth=state.total_count, nodes=state.nodes, partial=dict(state.phi), **propagation_stats())
            return dict(state.phi) if inst.links_ok(state.phi, partial=False) else None
        q = state.choose()
        if q is not None:
            stack.append({'course': q, 'options': state.ordered_times(q), 'next': 0, 'chosen': None, 'changes': None})
    if trace is not None:
        reason = 'time_limit' if time.perf_counter() >= deadline else ('node_limit' if state.nodes >= max_nodes else 'exhausted')
        trace.update(reason=reason, depth=best_depth, nodes=state.nodes, partial=best_partial, **propagation_stats())
    return None


def candidate_delta(inst, current, cand, moved, cfg, sc=None, attendees=None):
    moved = [c for c in moved if cand[c] != current['phi'][c]]
    if not moved:
        return -math.inf
    sc = sc if sc is not None else student_course_sets(inst, current['sectioning'])
    attendees = attendees if attendees is not None else course_students(inst, current['sectioning'])
    pupils = set().union(*(attendees[c] for c in moved))
    old_phi = current['phi']
    result = 0.0
    old_student = current['gaps']['student_by_id']
    for student in pupils:
        new_g = _gap_value([cand[c] for c in sc[student]], inst.slots_per_day)
        old_g = old_student[student]
        result -= cfg.w_student_gaps * (new_g - old_g)
        result -= cfg.w_student_sq * (new_g * new_g - old_g * old_g)
    if pupils:
        untouched_max = max((g for s, g in old_student.items() if s not in pupils), default=0)
        new_max = max(untouched_max, max((_gap_value([cand[c] for c in sc[s]], inst.slots_per_day) for s in pupils), default=0))
        result -= cfg.w_student_max * (new_max - current['gaps']['student_max'])
    profs = {inst.teacher[c] for c in moved}
    for p in profs:
        old_g = current['gaps']['teacher_by_id'][p]
        new_g = _gap_value([cand[c] for c in inst.prof_courses(p)], inst.slots_per_day)
        result -= cfg.w_teacher_gaps * (new_g - old_g)
        result -= cfg.w_teacher_sq * (new_g * new_g - old_g * old_g)
    if profs:
        untouched = max((g for p, g in current['gaps']['teacher_by_id'].items() if p not in profs), default=0)
        new_max = max(untouched, max((_gap_value([cand[c] for c in inst.prof_courses(p)], inst.slots_per_day) for p in profs), default=0))
        result -= cfg.w_teacher_max * (new_max - current['gaps']['teacher_max'])
    for c in moved:
        result += cfg.w_teacher_pref * (inst.teacher_pref.get((inst.teacher[c], cand[c]), 0.0) - inst.teacher_pref.get((inst.teacher[c], old_phi[c]), 0.0))
    return result


def _changed_times_feasible(inst, phi, adj, changes):
    changed = set(changes)
    for c, t in changes.items():
        if t not in inst.allowed_slots(c):
            return False
        for q in adj[c]:
            if changes.get(q, phi[q]) == t:
                return False
    for link in inst.links:
        if link.first not in changed and link.second not in changed:
            continue
        a = changes.get(link.first, phi[link.first])
        b = changes.get(link.second, phi[link.second])
        gap = b - a
        if gap < link.min_gap or (link.max_gap is not None and gap > link.max_gap):
            return False
        if link.same_day and a // inst.slots_per_day != b // inst.slots_per_day:
            return False
    for rel in inst.relations:
        if rel.first in changed or rel.second in changed:
            a = changes.get(rel.first, phi[rel.first])
            b = changes.get(rel.second, phi[rel.second])
            if not relation_ok(rel.kind, a, b, inst.slots_per_day):
                return False
    return True


def legal_relocation(inst, phi, adj, c, t):
    return c not in inst.lock_time and t != phi[c] and _changed_times_feasible(inst, phi, adj, {c: t})


def kempe_move(inst, phi, adj, c, t2):
    t1 = phi[c]
    if t1 == t2:
        return None
    target = {c}
    stack = [c]
    while stack:
        x = stack.pop()
        for y in adj[x]:
            if y not in target and phi[y] in {t1, t2}:
                target.add(y)
                stack.append(y)
    if any(x in inst.lock_time for x in target):
        return None
    changes = {x: t2 if phi[x] == t1 else t1 for x in target}
    if not _changed_times_feasible(inst, phi, adj, changes):
        return None
    cand = dict(phi)
    cand.update(changes)
    return cand


def targeted_courses(inst, ev, rng):
    out = set()
    if inst.students and ev['gaps']['student_by_id']:
        worst = sorted(ev['gaps']['student_by_id'], key=ev['gaps']['student_by_id'].get, reverse=True)[:8]
        sc = student_course_sets(inst, ev['sectioning'])
        for s in worst:
            out.update(sc.get(s, set()))
    worst_p = sorted(ev['gaps']['teacher_by_id'], key=ev['gaps']['teacher_by_id'].get, reverse=True)[:5]
    for p in worst_p:
        out.update(inst.prof_courses(p))
    if ev.get('sectioning'):
        assigned = ev['sectioning']['assignment']
        for r in inst.requests:
            if not r.required and r.family not in assigned.get(r.student, {}):
                for sec in inst.family_sections(r.family):
                    out.update(inst.section_courses(sec))
    sample = list(inst.courses)
    rng.shuffle(sample)
    out.update(sample[:20])
    return [c for c in out if c not in inst.lock_time]


def local_search(inst, rooms, start_ev, cfg, rng, adj, stats, deadline):
    current = start_ev
    best = start_ev
    tabu = {}
    it = 0
    while time.perf_counter() < deadline:
        it += 1
        sc = student_course_sets(inst, current['sectioning'])
        attendees = course_students(inst, current['sectioning'])
        courses = targeted_courses(inst, current, rng)
        if not courses:
            break
        candidates = []
        for _ in range(cfg.candidate_moves):
            typ = rng.random()
            if typ < 0.62:
                c = rng.choice(courses)
                ts = list(inst.allowed_slots(c))
                rng.shuffle(ts)
                for t in ts[:6]:
                    if legal_relocation(inst, current['phi'], adj, c, t):
                        cand = dict(current['phi'])
                        old = cand[c]
                        cand[c] = t
                        candidates.append((candidate_delta(inst, current, cand, [c], cfg, sc, attendees), ('move', c, old, t), cand))
                        break
            elif typ < 0.88 and len(courses) >= 2:
                a, b = rng.sample(courses, 2)
                if a in inst.lock_time or b in inst.lock_time or current['phi'][a] == current['phi'][b]:
                    continue
                cand = dict(current['phi'])
                cand[a], cand[b] = cand[b], cand[a]
                if _changed_times_feasible(inst, current['phi'], adj, {a: cand[a], b: cand[b]}):
                    candidates.append((candidate_delta(inst, current, cand, [a, b], cfg, sc, attendees), ('swap', a, b), cand))
            else:
                c = rng.choice(courses)
                t2 = rng.randrange(inst.T)
                cand = kempe_move(inst, current['phi'], adj, c, t2)
                if cand is not None:
                    candidates.append((candidate_delta(inst, current, cand, [x for x in inst.courses if cand[x] != current['phi'][x]], cfg, sc, attendees), ('kempe', c, current['phi'][c], t2), cand))
        if not candidates:
            break
        candidates.sort(key=lambda x: x[0], reverse=True)
        evaluated = []
        for _, token, cand in candidates[:cfg.exact_candidates]:
            if time.perf_counter() >= deadline:
                break
            ev = evaluate(inst, rooms, cand, cfg, stats, current['rho'])
            if ev is not None:
                evaluated.append((ev, token))
        if not evaluated:
            continue
        evaluated.sort(key=lambda x: x[0]['key'], reverse=True)
        choice = None
        for ev, token in evaluated:
            is_tabu = tabu.get(token, -1) > it
            if not is_tabu or ev['key'] > best['key']:
                choice = (ev, token)
                break
        if choice is None:
            choice = evaluated[0]
        current, token = choice
        if token[0] == 'move':
            _, c, old, new = token
            tabu[('move', c, new, old)] = it + cfg.tabu_tenure
        elif token[0] == 'swap':
            tabu[token] = it + cfg.tabu_tenure
        else:
            tabu[token] = it + cfg.tabu_tenure
        if current['key'] > best['key']:
            best = current
        if it % 5 == 0 and time.perf_counter() < deadline:
            current['local_iterations'] = it
            lns = lns_repair(inst, rooms, current, cfg, rng, adj, stats, deadline)
            if lns is not None:
                current = lns
                if current['key'] > best['key']:
                    best = current
    best['local_iterations'] = it
    return best


def lns_repair(inst, rooms, current, cfg, rng, adj, stats, deadline):
    pool = targeted_courses(inst, current, rng)
    if not pool:
        return None
    phi = current['phi']
    target = []
    mode = rng.randrange(4)
    if mode == 0:
        profs = sorted(inst.professors, key=lambda p: current['gaps']['teacher_by_id'].get(p, 0), reverse=True)
        if profs:
            p = rng.choice(profs[:min(5, len(profs))])
            by_day = defaultdict(list)
            for c in inst.prof_courses(p):
                by_day[phi[c] // inst.slots_per_day].append(c)
            target = max(by_day.values(), key=len, default=[])
    elif mode == 1 and inst.students:
        worst = sorted(current['gaps']['student_by_id'], key=current['gaps']['student_by_id'].get, reverse=True)
        if worst:
            student = rng.choice(worst[:min(10, len(worst))])
            target = list(student_course_sets(inst, current['sectioning']).get(student, set()))
    elif mode == 2 and inst.departments:
        dep = rng.choice(inst.departments)
        target = inst.dept_courses(dep)
    else:
        if inst.families:
            family = rng.choice(inst.families)
            target = [c for sec in inst.family_sections(family) for c in inst.section_courses(sec)]
    target = [c for c in target if c not in inst.lock_time]
    rng.shuffle(target)
    rng.shuffle(pool)
    size = min(len(pool), cfg.lns_size + min(6, current.get('local_iterations', 0) // 15))
    selected = list(dict.fromkeys(target + pool))[:size]
    base = dict(current['phi'])
    fixed = {c: t for c, t in base.items() if c not in selected}
    domains = {}
    for c in selected:
        vals = list(inst.allowed_slots(c))
        vals.sort(key=lambda t: (0 if t == base[c] else 1, sum(overlap_weight(inst, c, q, stats) for q, tq in fixed.items() if tq == t), -inst.teacher_pref.get((inst.teacher[c], t), 0.0)))
        domains[c] = vals[:min(6, len(vals))]
    order = sorted(selected, key=lambda c: len(domains[c]))
    best = None
    nodes = 0
    partial = dict(fixed)
    slot_courses = defaultdict(set)
    for c, t in fixed.items():
        slot_courses[t].add(c)
    def rec(i):
        nonlocal best, nodes
        if time.perf_counter() >= deadline or nodes >= cfg.lns_nodes:
            return
        nodes += 1
        if i == len(order):
            if not inst.links_ok(partial, partial=False):
                return
            ev = evaluate(inst, rooms, partial, cfg, stats, current['rho'])
            if ev is not None and (best is None or ev['key'] > best['key']):
                best = ev
            return
        c = order[i]
        for t in domains[c]:
            if slot_courses[t] & adj[c]:
                continue
            partial[c] = t
            slot_courses[t].add(c)
            if inst.links_ok(partial, partial=True):
                rec(i + 1)
            slot_courses[t].remove(c)
            partial.pop(c, None)
            if time.perf_counter() >= deadline or nodes >= cfg.lns_nodes:
                break
    rec(0)
    return best if best is not None and best['key'] >= current['key'] else None


class _BinaryRepairModel:
    """Small 0--1 model: optionally CP-SAT, otherwise SciPy/HiGHS MILP."""
    def __init__(self):
        self.cost = []
        self.rows = []

    def variable(self, cost=0.0):
        i = len(self.cost)
        self.cost.append(float(cost))
        return i

    def add(self, terms, lower=-math.inf, upper=math.inf):
        terms = [(j, float(v)) for j, v in terms if v]
        if not terms:
            return lower <= 0 <= upper
        self.rows.append((terms, lower, upper))
        return True

    def solve(self, seconds, backend='auto'):
        if seconds <= 0 or not self.cost:
            return None, 'SKIPPED'
        if backend != 'scipy':
            try:
                from ortools.sat.python import cp_model
                m = cp_model.CpModel()
                x = [m.NewBoolVar(f'v{i}') for i in range(len(self.cost))]
                for terms, low, high in self.rows:
                    expr = sum(int(round(a)) * x[j] for j, a in terms)
                    if math.isfinite(low):
                        m.Add(expr >= int(math.ceil(low - 1e-7)))
                    if math.isfinite(high):
                        m.Add(expr <= int(math.floor(high + 1e-7)))
                m.Minimize(sum(round(v * 1000) * x[j] for j, v in enumerate(self.cost)))
                solver = cp_model.CpSolver()
                solver.parameters.max_time_in_seconds = float(seconds)
                solver.parameters.num_search_workers = 1
                status = solver.Solve(m)
                if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                    return [int(solver.Value(v)) for v in x], 'CP_SAT_FEASIBLE'
                return None, 'CP_SAT_INFEASIBLE_LOCAL' if status == cp_model.INFEASIBLE else 'CP_SAT_UNKNOWN'
            except ImportError:
                if backend == 'cp-sat':
                    return None, 'CP_SAT_NOT_INSTALLED'
        rows, cols, vals, lows, highs = [], [], [], [], []
        for i, (terms, low, high) in enumerate(self.rows):
            for j, a in terms:
                rows.append(i)
                cols.append(j)
                vals.append(a)
            lows.append(low)
            highs.append(high)
        a = coo_matrix((vals, (rows, cols)), shape=(len(lows), len(self.cost))).tocsr()
        try:
            result = milp(np.asarray(self.cost), integrality=np.ones(len(self.cost), dtype=int),
                          bounds=Bounds(np.zeros(len(self.cost)), np.ones(len(self.cost))),
                          constraints=LinearConstraint(a, np.asarray(lows), np.asarray(highs)),
                          options={'time_limit': max(0.05, seconds), 'mip_rel_gap': 0.03})
        except (ValueError, RuntimeError):
            return None, 'SCIPY_ERROR'
        if result.x is None:
            return None, 'SCIPY_INFEASIBLE_LOCAL' if result.status == 2 else 'SCIPY_UNKNOWN'
        values = [int(v > 0.5) for v in result.x]
        # Numerical safety: only emit incumbents that pass all linear constraints.
        for terms, low, high in self.rows:
            v = sum(values[j] * a for j, a in terms)
            if v < low - 1e-5 or v > high + 1e-5:
                return None, 'SCIPY_NUMERICAL_REJECT'
        return values, 'SCIPY_FEASIBLE'


def _has_complete_matching(cost_matrix):
    """Whether a cost matrix has a full assignment using only zero-cost edges.
    Relies on SciPy's Jonker-Volgenant linear assignment implementation:
    https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.linear_sum_assignment.html
    """
    rows, cols = linear_sum_assignment(cost_matrix)
    return (len(rows) == cost_matrix.shape[0]
            and all(cost_matrix[i, j] == 0 for i, j in zip(rows, cols)))


def feasibility_prechecks(inst, rooms):
    """Sound necessary conditions; never mistake these for a complete feasibility proof."""
    issues = []
    by_time = defaultdict(list)
    for c, t in inst.lock_time.items():
        by_time[t].append(c)
    base = hard_adjacency(inst)
    for t, courses in by_time.items():
        for i, c in enumerate(courses):
            for d in courses[i + 1:]:
                if d in base[c]:
                    issues.append(f'locked time {t}: conflicting courses {c}, {d}')
        by_room = defaultdict(list)
        for c in courses:
            if c in inst.lock_room:
                by_room[inst.lock_room[c]].append(c)
        for room, cs in by_room.items():
            if len(cs) > 1:
                issues.append(f'locked time {t}: room {room} used by {cs[:3]}')
    possible = {}
    for c in inst.courses:
        # A flexible section need not be filled to its maximum capacity.
        minimum_size = (1 if inst.section_of[c] else
                        (len(inst._fixed_attendees[c]) if inst.group_of.get(c) else
                         max(inst.explicit_size[c], len(inst._fixed_attendees[c]))))
        available = []
        for t in inst.allowed_slots(c):
            if any(t in rooms.available[r] and rooms.capacity[r] >= minimum_size
                   and inst.required_equipment[c] <= rooms.equipment[r]
                   and (rooms.allowed_subjects[r] is None or inst.subject[c] in rooms.allowed_subjects[r])
                   and (c not in inst.lock_room or inst.lock_room[c] == r)
                   for r in rooms.rooms):
                available.append(t)
        possible[c] = available
        if not available:
            issues.append(f'{c}: no permitted time with even one suitable room')
    # Matching necessary for each teacher, fixed group and specialty section.
    for kind, groups in (('teacher', inst._prof_index), ('class', inst._dept_index),
                         ('fixed group', inst._group_index), ('specialty section', inst._section_index)):
        for name, courses in groups.items():
            courses = list(courses)
            if not courses:
                continue
            union = set().union(*(set(possible[c]) for c in courses))
            if len(courses) > len(union):
                issues.append(f'{kind} {name}: {len(courses)} lessons but only {len(union)} usable times')
                continue
            if len(courses) > inst.T:
                continue
            cost = np.full((len(courses), inst.T), 1e5)
            for i, c in enumerate(courses):
                for t in possible[c]:
                    cost[i, t] = 0
            if not _has_complete_matching(cost):
                issues.append(f'{kind} {name}: Hall/matching feasibility failure')
    req_by_family = Counter(r.family for r in inst.requests if r.required)
    for family, need in req_by_family.items():
        capacity = sum(inst.section_capacity[s] for s in inst.family_sections(family))
        if need > capacity:
            issues.append(f'family {family}: {need} compulsory requests exceed {capacity} places')
    # Check locked-time room matching with mandatory room compatibility.
    for t, courses in by_time.items():
        if courses:
            costs = np.full((len(courses), len(rooms.rooms)), 1e5)
            for i, c in enumerate(courses):
                for j, r in enumerate(rooms.rooms):
                    if t in possible[c] and t in rooms.available[r] and (c not in inst.lock_room or inst.lock_room[c] == r) and inst.required_equipment[c] <= rooms.equipment[r]:
                        size = (1 if inst.section_of[c] else max(inst.explicit_size[c], len(inst._fixed_attendees[c])))
                        if rooms.capacity[r] >= size and (rooms.allowed_subjects[r] is None or inst.subject[c] in rooms.allowed_subjects[r]):
                            costs[i, j] = 0
            if len(courses) > len(rooms.rooms):
                issues.append(f'locked slot {t}: more courses than rooms')
            else:
                if not _has_complete_matching(costs):
                    issues.append(f'locked slot {t}: no compatible room matching')
    return issues


def _pair_time_ok(inst, c, t, d, u):
    for link in inst.links:
        if (link.first, link.second) == (c, d):
            if u - t < link.min_gap or link.max_gap is not None and u - t > link.max_gap or link.same_day and t // inst.slots_per_day != u // inst.slots_per_day:
                return False
        if (link.first, link.second) == (d, c):
            if t - u < link.min_gap or link.max_gap is not None and t - u > link.max_gap or link.same_day and t // inst.slots_per_day != u // inst.slots_per_day:
                return False
    for rel in inst.relations:
        if (rel.first, rel.second) == (c, d) and not relation_ok(rel.kind, t, u, inst.slots_per_day):
            return False
        if (rel.first, rel.second) == (d, c) and not relation_ok(rel.kind, u, t, inst.slots_per_day):
            return False
    return True


def exact_repair_neighborhood(inst, rooms, partial, selected, student_ids, seconds, backend='auto', require_change=False, section_reservations=None):
    """Joint time/section 0-1 repair on selected courses and students.

    All remaining course times are fixed. A candidate must subsequently pass all
    section assignment, room matching, and independent validation.
    """
    selected = set(selected)
    student_ids = set(student_ids)
    partial = dict(partial)
    if not selected or not selected <= set(inst.courses) or set(inst.courses) != set(partial) | selected:
        return None, 'INVALID_NEIGHBORHOOD'
    fixed_times = {c: t for c, t in partial.items() if c not in selected}
    base_adj = hard_adjacency(inst)
    model = _BinaryRepairModel()
    time_vars = {}
    domain = {}
    fixed_by_slot = defaultdict(list)
    for c, t in fixed_times.items():
        fixed_by_slot[t].append(c)
    for c in sorted(selected):
        compatible_times = []
        min_size = 1 if inst.section_of[c] else max(inst.explicit_size[c], len(inst._fixed_attendees[c]))
        for t in sorted(inst.allowed_slots(c)):
            if any(d in base_adj[c] or not _pair_time_ok(inst, c, t, d, fixed_times[d]) for d in fixed_by_slot[t]):
                continue
            if any(not _pair_time_ok(inst, c, t, d, u) for d, u in fixed_times.items() if d not in fixed_by_slot[t]):
                continue
            if not any(t in rooms.available[r] and rooms.capacity[r] >= min_size
                       and inst.required_equipment[c] <= rooms.equipment[r]
                       and (rooms.allowed_subjects[r] is None or inst.subject[c] in rooms.allowed_subjects[r])
                       and (c not in inst.lock_room or inst.lock_room[c] == r)
                       for r in rooms.rooms):
                continue
            compatible_times.append(t)
        if not compatible_times:
            return None, 'EMPTY_REPAIR_DOMAIN'
        domain[c] = compatible_times
        entries = []
        for t in compatible_times:
            j = model.variable(0.0 if partial.get(c) == t else 1.0)
            time_vars[c, t] = j
            entries.append((j, 1))
        model.add(entries, 1, 1)
    if require_change and all(c in partial for c in selected):
        # On a failed *complete* coloring, the incumbent is known not to be
        # globally feasible.  The original zero-move optimum must be excluded.
        keep = [(time_vars[c, partial[c]], 1) for c in selected
                if (c, partial[c]) in time_vars]
        if len(keep) == len(selected):
            model.add(keep, upper=len(selected) - 1)
    for c in selected:
        for d in base_adj[c] & selected:
            if c < d:
                for t in set(domain[c]) & set(domain[d]):
                    model.add([(time_vars[c,t], 1), (time_vars[d,t], 1)], upper=1)
    ordered_selected = sorted(selected)
    for i, c in enumerate(ordered_selected):
        for d in ordered_selected[i + 1:]:
            if not any(x.first in (c,d) for x in inst.links) and not any(x.first in (c,d) for x in inst.relations):
                continue
            for t in domain[c]:
                for u in domain[d]:
                    if not _pair_time_ok(inst,c,t,d,u):
                        model.add([(time_vars[c,t], 1), (time_vars[d,u], 1)], upper=1)
    for t in range(inst.T):
        entries = [(j, 1) for (c, u), j in time_vars.items() if u == t]
        available = sum(t in rooms.available[r] for r in rooms.rooms)
        if not model.add(entries, upper=available - len(fixed_by_slot[t])):
            return None, 'ROOM_COUNT_PRECHECK'
    if student_ids:
        from_fixed = inst._fixed_courses
        req_by_student = defaultdict(list)
        for req in inst.requests:
            if req.student in student_ids:
                req_by_student[req.student].append(req)
        section_choice_vars = defaultdict(list)
        for student in sorted(student_ids):
            relevant_reqs = req_by_student[student]
            req_y = {}
            for req in relevant_reqs:
                entries = []
                for sec in inst.family_sections(req.family):
                    if req.locked_section and req.locked_section != sec:
                        continue
                    j = model.variable(-0.02 * req.weight if not req.required else 0)
                    req_y[req.family, sec] = j
                    section_choice_vars[sec].append(j)
                    entries.append((j, 1))
                if not model.add(entries, 1 if req.required else 0, 1):
                    return None, 'MISSING_REQUIRED_SECTION'
            fixed_sources = from_fixed.get(student, set())
            requested_families = {req.family for req in relevant_reqs}
            for dep in inst.dependencies:
                if dep.to_family not in requested_families:
                    continue
                target = [(j, 1) for (fam, sec), j in req_y.items() if fam == dep.to_family]
                if dep.from_course:
                    if dep.from_course in fixed_sources and dep.required:
                        model.add(target, 1, 1)
                elif dep.required:
                    source = [(j, -1) for (fam, sec), j in req_y.items() if fam == dep.from_family]
                    if source:
                        model.add(target + source, 0, math.inf)
            # One attendance indicator per (student, section, slot), not per
            # (student, section, lesson, slot).
            for t in range(inst.T):
                entries = []
                count_fixed = 0
                for c in fixed_sources:
                    if c in selected:
                        if (c, t) in time_vars:
                            entries.append((time_vars[c, t], 1))
                    elif fixed_times.get(c) == t:
                        count_fixed += 1
                for (fam, sec), y in req_y.items():
                    section_courses = inst.section_courses(sec)
                    if any(c not in selected and fixed_times.get(c) == t
                           for c in section_courses):
                        # At least one fixed lesson occupies this slot.
                        entries.append((y, 1))
                        continue
                    present = [(time_vars[c, t], 1) for c in section_courses
                               if c in selected and (c, t) in time_vars]
                    if not present:
                        continue
                    w = model.variable()
                    model.add([(w, 1), (y, -1)], upper=0)
                    model.add([(w, 1)] + [(j, -1) for j, _ in present], upper=0)
                    model.add([(w, 1), (y, -1)] +
                              [(j, -1) for j, _ in present], lower=-1)
                    entries.append((w, 1))
                if not model.add(entries, upper=1-count_fixed):
                    return None, 'FIXED_STUDENT_COLLISION'
        # This is necessary, but not a substitute for the global sectioning
        # MILP.  Nonselected pupils are deliberately NOT considered assigned.
        for sec, indices in section_choice_vars.items():
            reserved = (section_reservations or {}).get(sec, 0)
            if not model.add([(j, 1) for j in indices],
                             upper=inst.section_capacity[sec] - reserved):
                return None, 'SECTION_CAPACITY_EXHAUSTED' 
    values, status = model.solve(seconds, backend)
    if values is None:
        return None, status
    candidate = dict(fixed_times)
    for (c,t), idx in time_vars.items():
        if values[idx]:
            candidate[c] = t
    if len(candidate) != len(inst.courses):
        return None, 'INCOMPLETE_REPAIR'
    return candidate, status


def relaxed_compulsory_sectioning(inst, phi, seconds=0.5):
    """Maximum-cardinality compulsory assignment for conflict-directed LNS.

    This is a *diagnostic*, not a complete timetable validator: optional
    requests and dependencies are handled by the normal sectioning solver.
    It always admits an empty assignment, so an incumbent yields a meaningful
    list of unallocated compulsory requests even when the full MILP is infeasible.
    """
    reqs = [req for req in inst.requests if req.required]
    section_times = {sec: {phi[c] for c in inst.section_courses(sec)}
                     for sec in inst.sections}
    fixed_times = {student: {phi[c] for c in inst._fixed_courses[student]}
                   for student in inst.students}
    variables = []
    by_req = defaultdict(list)
    by_sec = defaultdict(list)
    by_pupil_time = defaultdict(list)
    for ri, req in enumerate(reqs):
        for sec in inst.family_sections(req.family):
            if req.locked_section and sec != req.locked_section:
                continue
            if section_times[sec] & fixed_times[req.student]:
                continue
            j = len(variables)
            variables.append((ri, req.student, req.family, sec))
            by_req[ri].append(j)
            by_sec[sec].append(j)
            for t in section_times[sec]:
                by_pupil_time[req.student, t].append(j)
    if not variables:
        return {'unmet': reqs, 'assignment': {}, 'loads': {},
                'fulfilled': 0, 'total': len(reqs), 'status': 'NO_CHOICES'}
    rows, cols, data, lows, highs = [], [], [], [], []
    def add(indices, cap):
        i = len(lows)
        lows.append(-math.inf)
        highs.append(float(cap))
        for j in indices:
            rows.append(i)
            cols.append(j)
            data.append(1.)
    for ri in range(len(reqs)):
        if by_req[ri]:
            add(by_req[ri], 1)
    for sec, indices in by_sec.items():
        add(indices, inst.section_capacity[sec])
    for indices in by_pupil_time.values():
        if len(indices) > 1:
            add(indices, 1)
    matrix = coo_matrix((data, (rows, cols)),
                        shape=(len(lows), len(variables))).tocsr()
    try:
        result = milp(-np.ones(len(variables)),
                      integrality=np.ones(len(variables), dtype=int),
                      bounds=Bounds(np.zeros(len(variables)), np.ones(len(variables))),
                      constraints=LinearConstraint(matrix, np.array(lows), np.array(highs)),
                      options={'time_limit': max(0.05, seconds), 'mip_rel_gap': 0.02})
    except (ValueError, RuntimeError):
        return None
    if result.x is None:
        return None
    assignment = defaultdict(dict)
    taken = set()
    loads = Counter()
    for idx, (ri, student, family, sec) in enumerate(variables):
        if result.x[idx] > 0.5:
            taken.add(ri)
            assignment[student][family] = sec
            loads[sec] += 1
    # Do not use a numerically invalid MILP incumbent to fix reservations.
    if any(sum(result.x[j] > 0.5 for j in by_req[i]) > 1 for i in by_req):
        return None
    if any(loads[q] > inst.section_capacity[q] for q in loads):
        return None
    return {'unmet': [req for i, req in enumerate(reqs) if i not in taken],
            'assignment': dict(assignment), 'loads': dict(loads),
            'fulfilled': len(taken), 'total': len(reqs),
            'status': ('OPTIMAL' if result.status == 0 else 'INCUMBENT')}


def compulsory_section_diagnostics(inst, phi, check_capacity=True):
    required = defaultdict(list)
    for req in inst.requests:
        if req.required:
            required[req.student].append(req)
    section_masks = {}
    for section in inst.sections:
        mask = 0
        for c in inst.section_courses(section):
            mask |= 1 << phi[c]
        section_masks[section] = mask
    pupils = []
    family_groups = defaultdict(Counter)
    zero_count = combination_failures = 0
    for student, reqs in required.items():
        occupied = 0
        for c in inst._fixed_courses[student]:
            occupied |= 1 << phi[c]
        domains = []
        for req in reqs:
            choices = tuple(q for q in inst.family_sections(req.family)
                            if (not req.locked_section or q == req.locked_section)
                            and not (section_masks[q] & occupied))
            domains.append((req, choices))
            family_groups[req.family][choices] += 1
        zeros = sum(not opts for _, opts in domains)
        zero_count += zeros
        compatible = not zeros
        if compatible:
            ordered = sorted(domains, key=lambda x: len(x[1]))
            def visit(i, bits):
                if i == len(ordered):
                    return True
                return any(not (section_masks[q] & bits)
                           and visit(i + 1, bits | section_masks[q])
                           for q in ordered[i][1])
            compatible = visit(0, occupied)
        if not compatible and not zeros:
            combination_failures += 1
        scarcity = sum(1 / max(1, len(qs)) for _, qs in domains)
        pupils.append((100 * zeros + (40 if not compatible else 0) + scarcity,
                       student, domains))
    pupils.sort(reverse=True)
    capacity_bad = set()
    if check_capacity:
        for family, groups in family_groups.items():
            if not _PupilFeasibilityPropagator._flow_feasible(
                    groups, inst.section_capacity):
                capacity_bad.add(family)
    score = 1000 * zero_count + 400 * combination_failures + 150 * len(capacity_bad)
    # Scarcity provides a weak gradient even if only global coupling is wrong.
    score += sum(rank[0] % 1 for rank in pupils)
    return {'score': score, 'zero_requests': zero_count,
            'combination_failures': combination_failures,
            'capacity_families': capacity_bad, 'pupils': pupils,
            'section_masks': section_masks}


def _conflict_guided_neighborhoods(inst, phi, diag, cfg, rng):
    """Choose movable blocking lessons, not whole arbitrary subject families."""
    limit = max(2, cfg.joint_lns_size)
    difficult = diag['pupils']
    relaxed = diag.get('relaxed') or {}
    unmet = relaxed.get('unmet', [])
    priority_students = {req.student for req in unmet}
    # Prioritise pupils actually rejected by the global relaxed MILP.
    if priority_students:
        difficult = sorted(difficult, key=lambda x: (
            x[1] in priority_students, x[0]), reverse=True)
    bad_families = diag['capacity_families']
    for _, pupil, domains in difficult[:max(3, cfg.joint_lns_students)]:
        all_options = []
        blockers = Counter()
        source_slots = defaultdict(list)
        for c in inst._fixed_courses[pupil]:
            source_slots[phi[c]].append(c)
        # A candidate section must be freed from all compulsory fixed lessons.
        for req, viable in sorted(domains, key=lambda x: len(x[1])):
            choices = [sec for sec in inst.family_sections(req.family)
                       if not req.locked_section or sec == req.locked_section]
            if viable and req.family not in bad_families:
                continue
            for sec in choices:
                for c in inst.section_courses(sec):
                    if phi[c] in source_slots:
                        if c not in inst.lock_time:
                            blockers[c] += 5
                        for d in source_slots[phi[c]]:
                            if d not in inst.lock_time:
                                blockers[d] += 2
            all_options.extend(choices)
        # If no single-family clash exists, look for collisions between
        # sections of distinct required families (the important 3-choice case).
        for i, (ri, _) in enumerate(domains):
            si = [q for q in inst.family_sections(ri.family)
                  if not ri.locked_section or ri.locked_section == q]
            for rj, _ in domains[i + 1:]:
                sj = [q for q in inst.family_sections(rj.family)
                      if not rj.locked_section or rj.locked_section == q]
                for qa in si:
                    for qb in sj:
                        if not diag['section_masks'][qa] & diag['section_masks'][qb]:
                            continue
                        a_by_time = defaultdict(list)
                        for c in inst.section_courses(qa):
                            a_by_time[phi[c]].append(c)
                        for c in inst.section_courses(qb):
                            for d in a_by_time.get(phi[c], ()):
                                if c not in inst.lock_time: blockers[c] += 2
                                if d not in inst.lock_time: blockers[d] += 2
        if not blockers and not bad_families and pupil not in priority_students:
            continue
        if pupil in priority_students:
            # Selected families may look locally compatible, yet all viable
            # combinations compete for seats already used by other pupils.
            for req in unmet:
                if req.student != pupil:
                    continue
                for sec in inst.family_sections(req.family):
                    if req.locked_section and sec != req.locked_section:
                        continue
                    for c in inst.section_courses(sec):
                        if c not in inst.lock_time:
                            blockers[c] += 3
                    # Include courses in the sections already allocated to
                    # this pupil: they may need to cease overlapping a
                    # newly freed section.
                    for other_sec in relaxed.get('assignment', {}).get(pupil, {}).values():
                        for c in inst.section_courses(other_sec):
                            if c not in inst.lock_time:
                                blockers[c] += 2

        # Include the two or three closest colleagues to the focus pupil.
        related = {pupil}
        families = {req.family for req, _ in domains}
        # Start with other unallocated pupils and occupants of the target
        # sections. These are the actual competitors for scarce section seats.
        assignment = relaxed.get('assignment', {})
        for req in unmet:
            if len(related) >= cfg.joint_lns_students:
                break
            if req.student != pupil and req.family in families:
                related.add(req.student)
        for _, another, opts in difficult:
            if len(related) >= max(1, cfg.joint_lns_students):
                break
            if another != pupil and any(r.family in families for r, _ in opts):
                related.add(another)

        ranked = sorted(blockers, key=lambda c: (-blockers[c],
                       -len(inst.allowed_slots(c)), rng.random()))
        selected = set(ranked[:limit])
        if not selected:
            # Capacity-only failure: free some lessons in bottleneck families.
            for req, _ in domains:
                if req.family in bad_families:
                    for sec in inst.family_sections(req.family):
                        for c in inst.section_courses(sec):
                            if c not in inst.lock_time and len(selected) < limit:
                                selected.add(c)
        if selected:
            yield selected, related


def _try_joint_repair(inst, rooms, phi, cfg, rng, stats, deadline, diagnostics):
    """Iterative joint LNS, accepting genuine improvements to pupil feasibility."""
    if not cfg.joint_lns_enabled:
        return None
    current = dict(phi)
    diag = compulsory_section_diagnostics(inst, current)
    diag['relaxed'] = relaxed_compulsory_sectioning(
        inst, current, min(.6, max(.1, deadline - time.perf_counter())))
    if diag['relaxed'] is not None:
        diag['score'] += 10000 * len(diag['relaxed']['unmet'])
        diagnostics['joint_initial_unmet'] = len(diag['relaxed']['unmet'])
    diagnostics['joint_initial_score'] = round(diag['score'], 2)
    diagnostics['joint_initial_zero_requests'] = diag['zero_requests']
    diagnostics['joint_initial_combination_failures'] = diag['combination_failures']
    diagnostics['joint_initial_capacity_families'] = len(diag['capacity_families'])
    best_score = diag['score']
    steps = 0
    while time.perf_counter() + .07 < deadline:
        improved = False
        for selected, students in _conflict_guided_neighborhoods(inst, current, diag, cfg, rng):
            left = deadline - time.perf_counter()
            if left < .07:
                break
            diagnostics['repair_attempts'] += 1
            steps += 1
            reservations = Counter()
            if diag.get('relaxed'):
                for pupil, chosen in diag['relaxed']['assignment'].items():
                    if pupil not in students:
                        reservations.update(chosen.values())
            cand, status = exact_repair_neighborhood(
                inst, rooms, current, selected, students,
                min(left, cfg.joint_lns_step_seconds), cfg.repair_backend,
                require_change=True, section_reservations=reservations)
            diagnostics['repair_statuses'][status] += 1
            if cand is None:
                continue
            # Reject invalid lesson colourings before expensive sectioning.
            if not hard_time_feasible(inst, cand, hard_adjacency(inst)):
                diagnostics['joint_invalid_candidate'] = diagnostics.get('joint_invalid_candidate', 0) + 1
                continue
            candidate_diag = compulsory_section_diagnostics(inst, cand)
            candidate_diag['relaxed'] = relaxed_compulsory_sectioning(
                inst, cand, min(.6, max(.1, deadline - time.perf_counter())))
            if candidate_diag['relaxed'] is None:
                continue
            candidate_diag['score'] += 10000 * len(candidate_diag['relaxed']['unmet'])
            if candidate_diag['score'] < best_score - 1e-6:
                current = cand
                diag = candidate_diag
                best_score = diag['score']
                improved = True
                diagnostics['joint_accepted_moves'] = diagnostics.get('joint_accepted_moves', 0) + 1
            # A candidate meeting the necessary tests may pass global sectioning.
            if (not candidate_diag['relaxed']['unmet']
                    and candidate_diag['zero_requests'] == 0
                    and candidate_diag['combination_failures'] == 0
                    and not candidate_diag['capacity_families']):
                ev = evaluate(inst, rooms, cand, cfg, stats)
                if ev is not None:
                    diagnostics['repair_success'] += 1
                    diagnostics['joint_final_score'] = round(candidate_diag['score'], 2)
                    diagnostics['joint_steps'] = steps
                    return ev
            if improved:
                break  # Recompute conflicts around the new incumbent.
        if not improved:
            break
    diagnostics['joint_final_score'] = round(best_score, 2)
    diagnostics['joint_steps'] = steps
    if diag.get('relaxed') is not None:
        diagnostics['joint_final_unmet'] = len(diag['relaxed']['unmet'])
    return None


def _try_partial_repair(inst, rooms, trace, cfg, rng, stats, deadline, diagnostics):
    partial = trace.get('partial') or {}
    missing = set(inst.courses) - set(partial)
    if not missing or len(missing) > cfg.repair_size:
        return None
    selected = set(missing)
    # Release a few assigned blockers; other lesson times remain fixed.
    adj = hard_adjacency(inst)
    if len(selected) < cfg.repair_size:
        blockers = Counter()
        for c in missing:
            for q in adj[c] & partial.keys():
                blockers[q] += 1
        for c, _ in blockers.most_common(cfg.repair_size - len(selected)):
            if c not in inst.lock_time:
                selected.add(c)
    rem = deadline - time.perf_counter()
    if rem < 0.06:
        return None
    diagnostics['repair_attempts'] += 1
    cand, status = exact_repair_neighborhood(inst, rooms, partial, selected, set(), min(rem, 2.0), cfg.repair_backend)
    diagnostics['repair_statuses'][status] += 1
    if cand is None:
        return None
    ev = evaluate(inst, rooms, cand, cfg, stats)
    if ev is not None:
        diagnostics['repair_success'] += 1
        return ev
    diagnostics['section_or_room_failures_after_repair'] += 1
    return _try_joint_repair(inst, rooms, cand, cfg, rng, stats, deadline, diagnostics)


def solve(inst, rooms, cfg):
    start = time.perf_counter()
    deadline = start + max(0.05, cfg.time_limit)
    rng = random.Random(cfg.seed)
    diagnostics = {
        'construction_failures': 0, 'section_failures': 0, 'room_failures': 0,
        'repair_attempts': 0, 'repair_success': 0, 'repair_statuses': Counter(),
        'deepest_partial': 0, 'section_or_room_failures_after_repair': 0,
        'attempt_log': [], 'precheck_issues': []}
    issues = feasibility_prechecks(inst, rooms)
    if issues:
        diagnostics['precheck_issues'] = issues[:30]
        return {'status': 'INFEASIBLE_PRECHECK', 'best': None,
                'seconds': time.perf_counter() - start, 'attempts': 0,
                'diagnostics': {**diagnostics, 'repair_statuses': {}}}
    base_adj = hard_adjacency(inst)
    stats = request_statistics(inst)
    best = None
    attempts = successful = 0
    construction_status = None
    recent_partials = []
    fully_colored = []
    strategy = cfg.seed_strategy
    if strategy == 'auto':
        strategy = 'optimized'
    # Keep the original construction allocation: repair draws from the reserved
    # quality-improvement budget only when no feasible timetable exists.
    reserved_quality = 0.0 if cfg.feasibility_only else cfg.local_seconds + cfg.room_day_seconds
    build_deadline = min(deadline, start + max(.25, cfg.time_limit - reserved_quality))
    # Allocate a genuine wall-time reserve for joint repair. Previously the
    # reserve was capped at 2 s, starving MILP neighborhoods even when the
    # user explicitly requested a longer repair phase.
    repair_reserve = min(max(0., cfg.repair_seconds), .5 * cfg.time_limit)
    failed_build_deadline = min(build_deadline, deadline - repair_reserve)
    max_starts = 1 if cfg.feasibility_only else cfg.max_feasible_starts
    while successful < max_starts and attempts < cfg.restarts and time.perf_counter() < (build_deadline if best is not None else failed_build_deadline):
        attempts += 1
        if strategy == 'optimized':
            # Unseeded attempts are introduced early: an optimised provisional
            # allocation is not evidence that its induced graph is colorable.
            variant = ('optimized', 'none', 'affinity', 'none', 'random')[((attempts - 1) % 5)]
        elif strategy == 'affinity':
            mode = attempts % 4
            variant = ('none' if mode == 0 else 'random' if mode == 3 else 'affinity')
        elif strategy == 'balanced':
            variant = 'none' if attempts % 3 == 0 else 'random'
        else:
            mode = attempts % 4
            variant = 'none' if mode == 0 else 'affinity' if mode == 2 else 'random'
        seed_start = time.perf_counter()
        seed_metrics = {}
        if variant == 'none':
            seed_assignment = None
        elif variant == 'optimized':
            seed_assignment = optimized_section_seed(
                inst, rng, cfg.optimized_seed_seconds,
                cfg.seed_lns, cfg.seed_lns_seconds, seed_metrics)
        else:
            seed_assignment = seed_section_assignment(inst, rng, variant)
        seed_elapsed = time.perf_counter() - seed_start
        if seed_assignment is None and variant != 'none':
            diagnostics['construction_failures'] += 1
            diagnostics['attempt_log'].append({'number': attempts, 'seed': variant, 'reason': 'seed_capacity_failed'})
            continue
        construct_adj = hard_adjacency(inst, seed_assignment)
        active_build_deadline = build_deadline if best is not None else failed_build_deadline
        remaining_build = max(0., active_build_deadline - time.perf_counter())
        policy = cfg.attempt_policy
        if policy == 'portfolio':
            policy = 'adaptive' if cfg.time_limit <= 14 else 'legacy'
        if policy == 'legacy':
            budget = min(remaining_build, max(3.5, 0.018 * len(inst.courses)))
        else:
            ladder = (1, 2, 4, 1.5, 3, 6)
            quantum = max(.7, .005 * len(inst.courses))
            budget = min(remaining_build, quantum * ladder[(attempts - 1) % len(ladder)])
        trace = {}
        attempt_start = time.perf_counter()
        phi = construct(inst, rooms, cfg, rng, construct_adj, stats,
                        min(active_build_deadline, attempt_start + budget), seed_assignment, trace)
        detail = {'number': attempts, 'seed': variant, 'reason': trace.get('reason', 'unknown'),
                  'depth': trace.get('depth', 0), 'nodes': trace.get('nodes', 0),
                  'seconds': round(time.perf_counter() - attempt_start, 3),
                  'seed_seconds': round(seed_elapsed, 3), **seed_metrics,
                  **{k: trace.get(k, 0) for k in ('pupil_checks', 'pupil_prunes', 'capacity_checks', 'capacity_prunes', 'witness_recomputes', 'watch_skips', 'family_flow_checks')}}
        diagnostics['deepest_partial'] = max(diagnostics['deepest_partial'], trace.get('depth', 0))
        if phi is None:
            diagnostics['construction_failures'] += 1
            if trace.get('partial'):
                recent_partials.append(trace)
                recent_partials.sort(key=lambda v: v.get('depth', 0), reverse=True)
                recent_partials = recent_partials[:3]
            diagnostics['attempt_log'].append(detail)
            continue
        fail = []
        ev = evaluate(inst, rooms, phi, cfg, stats, failure=fail)
        if ev is None:
            stage = fail[-1] if fail else 'unknown'
            # Do not consume the time reserved for joint repair by retrying
            # the same failed section MILP at greater length.
            retry_budget = min(2.5, max(cfg.section_seconds * 3, .8),
                               failed_build_deadline - time.perf_counter())
            if stage == 'section' and retry_budget >= .15:
                old_seconds = cfg.section_seconds
                cfg.section_seconds = retry_budget
                retry_fail = []
                try:
                    ev = evaluate(inst, rooms, phi, cfg, stats, failure=retry_fail)
                finally:
                    cfg.section_seconds = old_seconds
                if ev is not None:
                    diagnostics['section_retries_success'] = diagnostics.get('section_retries_success', 0) + 1
                    stage = 'recovered_section'
                else:
                    stage = retry_fail[-1] if retry_fail else stage
            if stage == 'section':
                diagnostics['section_failures'] += 1
            elif stage == 'room':
                diagnostics['room_failures'] += 1
            else:
                diagnostics['construction_failures'] += 1
            if ev is None:
                detail['reason'] = f'full_coloring_{stage}_failure'
                if len(fully_colored) < 4:
                    fully_colored.append(phi)
            else:
                detail['reason'] = 'valid_after_section_retry'
        else:
            detail['reason'] = 'valid'
        if ev is not None:
            successful += 1
            if best is None or ev['key'] > best['key']:
                best = ev
                construction_status = ('ITERATIVE_MRV_SECTION_RETRY'
                                       if detail['reason'] == 'valid_after_section_retry'
                                       else 'ITERATIVE_MRV')
        diagnostics['attempt_log'].append(detail)
        if len(diagnostics['attempt_log']) > 150:
            diagnostics['attempt_log'] = diagnostics['attempt_log'][:100] + diagnostics['attempt_log'][-50:]
    if best is None and cfg.repair_seconds > 0:
        # Use a bounded budget on conflict-guided joint time/section neighborhoods.
        repair_deadline = min(deadline, time.perf_counter() + cfg.repair_seconds)
        for phi in fully_colored:
            if time.perf_counter() >= repair_deadline:
                break
            ev = _try_joint_repair(inst, rooms, phi, cfg, rng, stats, repair_deadline, diagnostics)
            if ev is not None:
                best = ev
                construction_status = 'JOINT_EXACT_REPAIR'
                break
        if best is None:
            for trace in recent_partials:
                if time.perf_counter() >= repair_deadline:
                    break
                ev = _try_partial_repair(inst, rooms, trace, cfg, rng, stats, repair_deadline, diagnostics)
                if ev is not None:
                    best = ev
                    construction_status = 'PARTIAL_EXACT_REPAIR'
                    break
    diagnostics['repair_statuses'] = dict(diagnostics['repair_statuses'])
    if best is None:
        return {'status': 'UNKNOWN', 'best': None, 'seconds': time.perf_counter() - start,
                'attempts': attempts, 'feasible_starts': successful, 'diagnostics': diagnostics}
    initial_quality = best['quality']
    initial_gaps = dict(best['gaps'])
    initial_wish = best['wish_score']
    local_deadline = min(deadline, time.perf_counter() + cfg.local_seconds)
    if not cfg.feasibility_only and time.perf_counter() < local_deadline:
        best = local_search(inst, rooms, best, cfg, rng, base_adj, stats, local_deadline)
    swap_deadline = min(deadline, time.perf_counter() + max(0., cfg.student_swap_seconds))
    if not cfg.feasibility_only and best['sectioning'] and time.perf_counter() < swap_deadline:
        proposed_sectioning, num_swaps = improve_student_section_swaps(
            inst, best['phi'], best['sectioning'], cfg, swap_deadline)
        if proposed_sectioning is not None:
            updated = evaluate(inst, rooms, best['phi'], cfg, stats,
                               best['rho'], sectioning_override=proposed_sectioning)
            if updated is not None and updated['key'] > best['key']:
                updated['student_swaps'] = num_swaps
                best = updated
    rooms_deadline = min(deadline, time.perf_counter() + max(0., cfg.room_day_seconds * math.ceil(inst.T / inst.slots_per_day)))
    if not cfg.feasibility_only and cfg.room_day_seconds > 0 and time.perf_counter() < rooms_deadline:
        new_rho, room_attempted, room_accepted = optimize_rooms_week(inst, rooms, best, cfg, rooms_deadline)
        if new_rho != best['rho']:
            best = refresh_room_eval(inst, rooms, best, new_rho, cfg)
        best['room_days_tested'] = room_attempted
        best['room_days_improved'] = room_accepted
    best['initial_quality'] = initial_quality
    best['initial_student_gaps'] = initial_gaps['student_total']
    best['initial_student_max_gap'] = initial_gaps['student_max']
    best['initial_teacher_gaps'] = initial_gaps['teacher_total']
    best['initial_wish_score'] = initial_wish
    best['sectioning_optimal'] = True if not best['sectioning'] else best['sectioning']['optimal']
    best['construction_status'] = construction_status
    best['feasible_starts'] = successful
    return {'status': 'FEASIBLE', 'best': best, 'seconds': time.perf_counter() - start,
            'attempts': attempts, 'feasible_starts': successful, 'diagnostics': diagnostics}


def save_csv(inst, result, path):
    best = result.get('best')
    if not best:
        raise ValueError('no feasible timetable')
    phi, rho = best['phi'], best['rho']
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=['slot_index', 'timeslot', 'assignments'])
        w.writeheader()
        for t in range(inst.T):
            triples = sorted((inst.teacher[c], c, rho[c]) for c in inst.courses if phi[c] == t)
            w.writerow({'slot_index': t, 'timeslot': inst.slot_name(t), 'assignments': '; '.join(f'({p},{c},{r})' for p, c, r in triples)})


def save_student_csv(inst, result, path):
    best = result.get('best')
    if not best:
        raise ValueError('no feasible timetable')
    sc = student_course_sets(inst, best['sectioning'])
    phi, rho = best['phi'], best['rho']
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=['student', 'home_class', 'slot_index', 'timeslot', 'course', 'subject', 'professor', 'room', 'section'])
        w.writeheader()
        for s in inst.students:
            for c in sorted(sc.get(s, set()), key=lambda c: (phi[c], c)):
                w.writerow({'student': s, 'home_class': inst.home_class[s], 'slot_index': phi[c], 'timeslot': inst.slot_name(phi[c]), 'course': c, 'subject': inst.subject[c], 'professor': inst.teacher[c], 'room': rho[c], 'section': inst.section_of[c] or ''})


def print_summary(res):
    print(f"status={res['status']} seconds={res['seconds']:.3f} attempts={res.get('attempts', 0)} feasible_starts={res.get('feasible_starts', 0)}")
    if 'diagnostics' in res:
        d = res['diagnostics']
        print(f"diagnostics=build:{d.get('construction_failures',0)} section:{d.get('section_failures',0)} rooms:{d.get('room_failures',0)} repair:{d.get('repair_success',0)}/{d.get('repair_attempts',0)} deepest:{d.get('deepest_partial',0)}")
    b = res.get('best')
    if not b:
        return
    g = b['gaps']
    sec = b['sectioning']
    req_total = sum(1 for _ in sec['assignment'].values()) if sec else 0
    print(f"quality={b['quality']:.3f} initial_quality={b.get('initial_quality', b['quality']):.3f} wishes={b['wish_score']:.3f} initial_wishes={b.get('initial_wish_score', b['wish_score']):.3f} access={b['access_score']:.3f} student_gaps={g['student_total']} student_max_gap={g['student_max']} teacher_gaps={g['teacher_total']} teacher_max_gap={g['teacher_max']} room_changes={b['room_changes']} room_waste={b['room_waste']:.3f} sectioning_optimal={b.get('sectioning_optimal', False)} construction={b.get('construction_status', '')} local_iterations={b.get('local_iterations', 0)} student_swaps={b.get('student_swaps', 0)} assigned_students={req_total}")


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument('input')
    p.add_argument('output', nargs='?', default='timetable_output.csv')
    p.add_argument('--students-output')
    p.add_argument('--slots', type=int, default=40)
    p.add_argument('--slots-per-day', type=int, default=8)
    p.add_argument('--time-limit', type=float, default=15.0)
    p.add_argument('--local-seconds', type=float, default=6.0)
    p.add_argument('--section-seconds', type=float, default=1.0)
    p.add_argument('--restarts', type=int, default=120)
    p.add_argument('--candidate-moves', type=int, default=32)
    p.add_argument('--exact-candidates', type=int, default=6)
    p.add_argument('--tabu-tenure', type=int, default=12)
    p.add_argument('--lns-size', type=int, default=5)
    p.add_argument('--lns-nodes', type=int, default=500)
    p.add_argument('--seed', type=int)
    p.add_argument('--seed-strategy', choices=('auto', 'balanced', 'affinity', 'optimized', 'mixed'), default='auto')
    p.add_argument('--legacy-propagation', action='store_true', help='disable watched-witness incremental propagation')
    p.add_argument('--legacy-mrv', action='store_true', help='disable incremental MRV heap')
    p.add_argument('--no-seed-lns', action='store_true', help='disable v5.4 section-seed large neighborhoods')
    p.add_argument('--no-pupil-propagation', action='store_true', help='disable incremental compulsory student checks (baseline comparison)')
    p.add_argument('--propagation-match-interval', type=int, default=64, help='depth interval for compulsory section capacity matching; 0 disables it')
    p.add_argument('--propagation-match-limit', type=int, default=128, help='maximum flow checks per construction attempt to bound overhead')
    p.add_argument('--optimized-seed-seconds', type=float, default=0.7, help='single-pupil and pair-swap optimisation budget for an optimised seed')
    p.add_argument('--seed-lns-seconds', type=float, default=0.5, help='additional large-neighborhood section reassignment budget per optimised seed')
    p.add_argument('--student-swap-seconds', type=float, default=0.6)
    p.add_argument('--repair-seconds', type=float, default=3.0, help='total budget in seconds for bounded exact repair')
    p.add_argument('--repair-size', type=int, default=16, help='maximum courses in exact repair neighborhood')
    p.add_argument('--repair-students', type=int, default=8, help='maximum selected pupils in joint exact repair')
    p.add_argument('--repair-backend', choices=('auto','scipy','cp-sat'), default='auto')
    p.add_argument('--no-joint-lns', action='store_true', help='disable iterative conflict-guided joint repair')
    p.add_argument('--joint-lns-size', type=int, default=28, help='maximum lessons released in each joint repair')
    p.add_argument('--joint-lns-students', type=int, default=24, help='number of pupils considered in a joint repair')
    p.add_argument('--joint-lns-step-seconds', type=float, default=1.5, help='time limit for one joint MILP neighborhood')
    p.add_argument('--attempt-policy', choices=('portfolio','adaptive','legacy'), default='adaptive')
    p.add_argument('--feasibility-only', action='store_true', help='stop after the first validated feasible timetable')
    p.add_argument('--diagnostics', help='write JSON diagnostics to this file')
    p.add_argument('--max-feasible-starts', type=int, default=3)
    p.add_argument('--room-day-seconds', type=float, default=0.25)
    p.add_argument('--section-gap-weight', type=float, default=2.0)
    p.add_argument('--section-refine-rounds', type=int, default=3)
    p.add_argument('--w-optional', type=float, default=80.0)
    p.add_argument('--w-room-change', type=float, default=3.0)
    p.add_argument('--w-room-waste', type=float, default=2.0)
    p.add_argument('--w-room-balance', type=float, default=1.0)
    p.add_argument('--w-student-max', type=float, default=25.0)
    p.add_argument('--w-student-sq', type=float, default=2.5)
    p.add_argument('--w-student-gaps', type=float, default=0.75)
    p.add_argument('--w-teacher-max', type=float, default=12.0)
    p.add_argument('--w-teacher-sq', type=float, default=1.25)
    p.add_argument('--w-teacher-gaps', type=float, default=0.5)
    p.add_argument('--w-teacher-pref', type=float, default=4.0)
    p.add_argument('--w-daily', type=float, default=0.025)
    p.add_argument('--w-special-room', type=float, default=3.0)
    a = p.parse_args(argv)
    cfg = Config(
        time_limit=a.time_limit, local_seconds=a.local_seconds,
        section_seconds=a.section_seconds, restarts=a.restarts,
        candidate_moves=a.candidate_moves, exact_candidates=a.exact_candidates,
        tabu_tenure=a.tabu_tenure, lns_size=a.lns_size,
        lns_nodes=a.lns_nodes, seed=a.seed,
    )
    cfg.seed_strategy = a.seed_strategy
    cfg.joint_lns_enabled = not a.no_joint_lns
    cfg.joint_lns_size = max(1, a.joint_lns_size)
    cfg.joint_lns_students = max(1, a.joint_lns_students)
    cfg.joint_lns_step_seconds = max(0.05, a.joint_lns_step_seconds)
    cfg.pupil_propagation = not a.no_pupil_propagation
    cfg.incremental_propagation = not a.legacy_propagation
    cfg.incremental_mrv = not a.legacy_mrv
    cfg.seed_lns = not a.no_seed_lns
    cfg.seed_lns_seconds = max(0.0, a.seed_lns_seconds)
    cfg.propagation_match_interval = max(0, a.propagation_match_interval)
    cfg.optimized_seed_seconds = max(0.0, a.optimized_seed_seconds)
    cfg.propagation_match_limit = max(0, a.propagation_match_limit)
    cfg.student_swap_seconds = a.student_swap_seconds
    cfg.repair_seconds = max(0.0, a.repair_seconds)
    cfg.repair_size = max(1, a.repair_size)
    cfg.repair_students = max(1, a.repair_students)
    cfg.repair_backend = a.repair_backend
    cfg.attempt_policy = a.attempt_policy
    cfg.diagnostics = a.diagnostics
    cfg.feasibility_only = a.feasibility_only
    for key in ('max_feasible_starts', 'room_day_seconds', 'section_gap_weight', 'section_refine_rounds', 'w_optional', 'w_room_change', 'w_room_waste', 'w_room_balance', 'w_student_max', 'w_student_sq', 'w_student_gaps', 'w_teacher_max', 'w_teacher_sq', 'w_teacher_gaps', 'w_teacher_pref', 'w_daily', 'w_special_room'):
        setattr(cfg, key, getattr(a, key))
    try:
        inst, rooms = load_csv(a.input, a.slots, a.slots_per_day)
        res = solve(inst, rooms, cfg)
        print_summary(res)
        if cfg.diagnostics:
            with open(cfg.diagnostics, 'w', encoding='utf-8') as f:
                json.dump({'status': res['status'], 'seconds':res['seconds'], **res.get('diagnostics', {})}, f, indent=2, sort_keys=True)
        if res['best'] is None:
            return 2
        save_csv(inst, res, a.output)
        if a.students_output:
            save_student_csv(inst, res, a.students_output)
        return 0
    except (ValueError, OSError) as e:
        print(f'error={e}', file=sys.stderr)
        return 1

if __name__ == '__main__':
    raise SystemExit(main())
