from __future__ import annotations
import argparse
import csv
import importlib.util
import math
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path


def load_schema(path):
    spec = importlib.util.spec_from_file_location('timetable_schema', path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def parse_output(path, T):
    phi, rho, prof = {}, {}, {}
    errors = []
    seen = set()
    pattern = re.compile(r'^\(([^,]+),([^,]+),([^,]+)\)$')
    with open(path, newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames or not {'slot_index', 'assignments'} <= set(reader.fieldnames):
            return phi, rho, prof, seen, ['missing slot_index/assignments columns']
        for n, row in enumerate(reader, 2):
            try:
                t = int((row.get('slot_index') or '').strip())
            except ValueError:
                errors.append(f'row {n}: invalid slot index')
                continue
            if t not in range(T):
                errors.append(f'row {n}: slot outside range')
                continue
            if t in seen:
                errors.append(f'row {n}: repeated slot {t}')
            seen.add(t)
            for item in (row.get('assignments') or '').split(';'):
                item = item.strip()
                if not item:
                    continue
                m = pattern.fullmatch(item)
                if m is None:
                    errors.append(f'row {n}: malformed tuple {item}')
                    continue
                p, c, room = [x.strip() for x in m.groups()]
                if c in phi:
                    errors.append(f'course {c} scheduled more than once')
                else:
                    phi[c], rho[c], prof[c] = t, room, p
    return phi, rho, prof, seen, errors


def parse_student_output(path, inst, phi, rho):
    errors = []
    student_courses = defaultdict(set)
    chosen = defaultdict(dict)
    with open(path, newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        columns = {'student', 'course', 'section', 'slot_index', 'professor', 'room'}
        if not reader.fieldnames or not columns <= set(reader.fieldnames):
            return student_courses, chosen, ['missing student timetable columns']
        for n, row in enumerate(reader, 2):
            s, c = (row.get('student') or '').strip(), (row.get('course') or '').strip()
            sec = (row.get('section') or '').strip()
            if s not in inst.home_class:
                errors.append(f'row {n}: unknown student {s}')
                continue
            if c not in inst.department:
                errors.append(f'row {n}: unknown course {c}')
                continue
            if c in student_courses[s]:
                errors.append(f'row {n}: duplicate course {s},{c}')
            student_courses[s].add(c)
            if (row.get('home_class') or '').strip() != inst.home_class[s]:
                errors.append(f'row {n}: incorrect home class')
            if c in phi:
                try:
                    out_time = int((row.get('slot_index') or '').strip())
                except ValueError:
                    out_time = -1
                if out_time != phi[c] or (row.get('professor') or '').strip() != inst.teacher[c] or (row.get('room') or '').strip() != rho[c]:
                    errors.append(f'row {n}: lesson details inconsistent with master timetable')
            if sec != (inst.section_of[c] or ''):
                errors.append(f'row {n}: wrong section for {c}')
            if sec:
                fam = inst.section_family[sec]
                if fam in chosen[s] and chosen[s][fam] != sec:
                    errors.append(f'{s}: conflicting sections in {fam}')
                chosen[s][fam] = sec
    return student_courses, chosen, errors


def gaps(slots, day_length):
    groups = defaultdict(set)
    for t in slots:
        groups[t // day_length].add(t % day_length)
    return sum(max(v) - min(v) + 1 - len(v) for v in groups.values() if v)


def validate(constraints, timetable, solver_path, student_output=None, slots=40, slots_per_day=8):
    schema = load_schema(solver_path)
    inst, rooms = schema.load_csv(constraints, slots, slots_per_day)
    phi, rho, prof, seen, errors = parse_output(timetable, slots)
    expected = set(inst.department)
    if set(phi) != expected:
        errors.append(f'lesson set mismatch; missing={sorted(expected - set(phi))[:10]} unexpected={sorted(set(phi) - expected)[:10]}')
    if seen != set(range(slots)):
        errors.append('missing or duplicate slot rows')
    teacher_slots = defaultdict(list)
    cohort_slots = defaultdict(list)
    section_slots = defaultdict(list)
    room_slots = defaultdict(list)
    # Parse independent group membership from the input CSV, rather than trusting
    # the solver's cached pupil-to-course relation.
    with open(constraints, newline='', encoding='utf-8-sig') as f:
        raw_input = list(csv.DictReader(f))
    group_course = defaultdict(set)
    groups_meta = {r.get('id','').strip():r for r in raw_input if r.get('kind','').strip().lower()=='group'}
    for r in raw_input:
        if r.get('kind','').strip().lower() == 'course' and r.get('group_id','').strip() and not r.get('section','').strip():
            group_course[r['group_id'].strip()].add(r.get('id','').strip())
    course_by_student = {s: set(inst.extra_fixed_courses.get(s, set())) for s in inst.students}
    member_count = Counter()
    roles_by_student = defaultdict(lambda: defaultdict(set))
    for r in raw_input:
        if r.get('kind','').strip().lower() != 'membership':
            continue
        student,group = r.get('student_id','').strip(),r.get('group_id','').strip()
        if student not in course_by_student or group not in groups_meta:
            errors.append(f'unknown membership {student},{group}')
            continue
        member_count[group] += 1
        course_by_student[student].update(group_course[group])
        typ = groups_meta[group].get('group_type','').strip()
        if typ in {'LVA','LVB','EPS'}:
            roles_by_student[student][typ].add(group)
    for s in inst.students:
        for c in inst.department:
            if (not inst.group_of.get(c) and inst.department[c] and inst.department[c] == inst.home_class[s]
                    and inst.hard_group[c] and not inst.section_of[c]):
                course_by_student[s].add(c)
    for group,n in member_count.items():
        declared = groups_meta[group].get('capacity','').strip()
        if declared and n > int(declared):
            errors.append(f'fixed group {group}: capacity exceeded')
    if groups_meta:
        for student,profile in inst.student_profile.items():
            for typ in ('LVA','LVB','EPS'):
                if profile.get('grade') and len(roles_by_student[student][typ]) != 1:
                    errors.append(f'{student}: expected exactly one {typ} group')

    for c, t in phi.items():
        if c not in expected:
            continue
        p, r = inst.teacher[c], rho[c]
        if prof[c] != p:
            errors.append(f'{c}: wrong professor')
        if t not in inst.prof_avail[p]:
            errors.append(f'{c}: professor unavailable')
        if c in inst.lock_time and t != inst.lock_time[c]:
            errors.append(f'{c}: time lock violated')
        if c in inst.lock_room and r != inst.lock_room[c]:
            errors.append(f'{c}: room lock violated')
        teacher_slots[p, t].append(c)
        if inst.hard_group[c] and inst.department[c]:
            cohort_slots[inst.department[c], t].append(c)
        if inst.section_of[c]:
            section_slots[inst.section_of[c], t].append(c)
        if r not in rooms.equipment:
            errors.append(f'{c}: unknown room {r}')
            continue
        room_slots[r, t].append(c)
        if t not in rooms.available[r]:
            errors.append(f'{c}: room not available')
        if not inst.required_equipment[c] <= rooms.equipment[r]:
            errors.append(f'{c}: missing room equipment')
        subjects = rooms.allowed_subjects[r]
        if subjects is not None and inst.subject[c] not in subjects:
            errors.append(f'{c}: room disallows subject')
    for label, groups in [('teacher', teacher_slots), ('home class', cohort_slots), ('section', section_slots), ('room', room_slots)]:
        for key, cs in groups.items():
            if len(cs) > 1:
                errors.append(f'{label} collision {key}: {cs[:5]}')
    for rel in inst.links:
        if rel.first in phi and rel.second in phi:
            first, last = phi[rel.first], phi[rel.second]
            dist = last - first
            if dist < rel.min_gap or (rel.max_gap is not None and dist > rel.max_gap) or (rel.same_day and first // slots_per_day != last // slots_per_day):
                errors.append(f'chronological link violated: {rel.first}->{rel.second}')
    for rel in getattr(inst, 'relations', ()):
        if rel.first not in phi or rel.second not in phi:
            continue
        a, b = phi[rel.first], phi[rel.second]
        valid = {'SAME_DAY': a // slots_per_day == b // slots_per_day, 'DIFFERENT_DAY': a // slots_per_day != b // slots_per_day, 'CONSECUTIVE': b == a + 1 and a // slots_per_day == b // slots_per_day, 'SAME_SLOT': a == b}[rel.kind]
        if not valid:
            errors.append(f'{rel.kind} violated {rel.first},{rel.second}')
    if inst.students and not student_output:
        errors.append('individual student CSV required for independent student validation')
    if student_output:
        listed, chosen, student_errors = parse_student_output(student_output, inst, phi, rho)
        errors.extend(student_errors)
        permitted = {(r.student, r.family): r for r in inst.requests}
        section_loads = Counter()
        for student, families in chosen.items():
            for family, sec in families.items():
                if (student, family) not in permitted:
                    errors.append(f'{student}: no request for {family}')
                section_loads[sec] += 1
                course_by_student[student].update(c for c in inst.department if inst.section_of[c] == sec)
        if groups_meta:
            # Specialty count is a path-level check, independent of which section is chosen.
            for student, profile in inst.student_profile.items():
                grade = profile.get('grade','')
                required_specialties = {r.family for r in inst.requests if r.student == student and r.required
                                        and r.family.startswith(f'{grade}_') and not '_OPT_' in r.family}
                if grade == '1re' and len(required_specialties) != 3:
                    errors.append(f'{student}: expected 3 compulsory specialties, found {len(required_specialties)}')
                if grade == 'Tle':
                    if len(required_specialties) != 2:
                        errors.append(f'{student}: expected 2 compulsory specialties, found {len(required_specialties)}')
                    previous = set((profile.get('previous_specialities') or '').split(';')) - {''}
                    if previous and (len(previous) != 3 or any(family[4:] not in previous for family in required_specialties)):
                        errors.append(f'{student}: terminale specialties not retained from previous three')
        for dep in getattr(inst, 'dependencies', ()):
            for student in inst.students:
                enrolled = course_by_student[student]
                active = (dep.from_course in enrolled) if dep.from_course else (dep.from_family in chosen[student])
                if active and dep.required and dep.to_family not in chosen[student]:
                    errors.append(f'{student}: mandatory linked family {dep.to_family} missing')
        for student, family in getattr(inst, 'synthetic_requests', ()):
            if family not in chosen[student]:
                continue
            eligible = any((d.from_course in course_by_student[student] if d.from_course else d.from_family in chosen[student]) for d in inst.dependencies if d.to_family == family)
            if not eligible:
                errors.append(f'{student}: linked family {family} selected without prerequisite')
        for req in inst.requests:
            sec = chosen[req.student].get(req.family)
            if req.required and not sec:
                errors.append(f'{req.student}: required request missing: {req.family}')
            if req.locked_section and sec != req.locked_section:
                errors.append(f'{req.student}: section lock violated')
        for sec, count in section_loads.items():
            if count > inst.section_capacity[sec]:
                errors.append(f'{sec}: too many pupils {count}>{inst.section_capacity[sec]}')
        for student in inst.students:
            if listed.get(student, set()) != course_by_student[student]:
                errors.append(f'{student}: student output course list mismatch')
            times = [phi[c] for c in course_by_student[student] if c in phi]
            if len(times) != len(set(times)):
                errors.append(f'{student}: overlapping lessons')
    else:
        section_loads = Counter()
        chosen = {}
    for c, t in phi.items():
        if c not in expected or rho[c] not in rooms.equipment:
            continue
        size = inst.explicit_size[c]
        if inst.group_of.get(c) and not inst.section_of[c]:
            size = sum(c in cs for cs in course_by_student.values())
        if inst.section_of[c]:
            size = section_loads[inst.section_of[c]]
        elif size == 0 and inst.students:
            size = sum(c in cs for cs in course_by_student.values())
        if size > rooms.capacity[rho[c]]:
            errors.append(f'{c}: room over capacity {size}>{rooms.capacity[rho[c]]}')
    room_change_count = 0
    room_change_weighted = 0.0
    professor_change_days = Counter()
    for professor in set(inst.teacher.values()):
        for d in range(math.ceil(slots / slots_per_day)):
            seq = sorted((phi[c], rho[c]) for c in inst.department if c in phi and inst.teacher[c] == professor and phi[c] // slots_per_day == d)
            for (ta, ra), (tb, rb) in zip(seq, seq[1:]):
                if ra != rb:
                    room_change_count += 1
                    professor_change_days[professor, d] += 1
                    room_change_weighted += getattr(inst, 'prof_room_weight', {}).get(professor, 1.0) * (1 if tb == ta + 1 else 0.25)
    for p, limit in getattr(inst, 'prof_room_max', {}).items():
        for d in range(math.ceil(slots / slots_per_day)):
            if professor_change_days[p, d] > limit:
                errors.append(f'professor {p}: day {d} room-change limit exceeded')
    student_gaps = {s: gaps([phi[c] for c in cs if c in phi], slots_per_day) for s, cs in course_by_student.items()}
    teacher_gaps = {p: gaps([phi[c] for c in inst.department if c in phi and inst.teacher[c] == p], slots_per_day) for p in set(inst.teacher.values())}
    original_optional = [r for r in inst.requests if not r.required and (r.student, r.family) not in getattr(inst, 'synthetic_requests', frozenset())]
    weighted_possible = sum(r.weight for r in original_optional)
    weighted_gained = sum(r.weight for r in original_optional if chosen.get(r.student, {}).get(r.family))
    optional_n = len(original_optional)
    optional_satisfied = sum(1 for r in original_optional if chosen.get(r.student, {}).get(r.family))
    linked_optional_activated = 0
    linked_optional_satisfied = 0
    linked_optional_possible_weight = 0.0
    linked_optional_gained_weight = 0.0
    hard_links_activated = 0
    for dep in getattr(inst, 'dependencies', ()):
        for student in inst.students:
            active = (dep.from_course in course_by_student[student]) if dep.from_course else (dep.from_family in chosen[student])
            if not active:
                continue
            enrolled = dep.to_family in chosen[student]
            if dep.required:
                hard_links_activated += 1
            else:
                linked_optional_activated += 1
                linked_optional_possible_weight += dep.weight
                if enrolled:
                    linked_optional_satisfied += 1
                    linked_optional_gained_weight += dep.weight
    capacity_slack = []
    for c in inst.department:
        if c not in phi or rho.get(c) not in rooms.capacity:
            continue
        n = section_loads[inst.section_of[c]] if inst.section_of[c] else ((sum(c in cs for cs in course_by_student.values())) if inst.group_of.get(c) else (inst.explicit_size[c] or sum(c in cs for cs in course_by_student.values())))
        if rooms.capacity[rho[c]] < 10**8:
            capacity_slack.append(rooms.capacity[rho[c]] - n)
    return {'valid': not errors, 'errors': errors, 'courses': len(expected), 'students': len(inst.students), 'required_requests': sum(r.required for r in inst.requests), 'optional_requests': optional_n, 'optional_satisfied': optional_satisfied, 'optional_satisfaction_fraction': optional_satisfied / optional_n if optional_n else 1.0, 'optional_weight_score': weighted_gained, 'optional_weight_fraction': weighted_gained / weighted_possible if weighted_possible else 1.0, 'student_gaps': sum(student_gaps.values()), 'student_gaps_per_student': sum(student_gaps.values()) / len(student_gaps) if student_gaps else 0, 'student_max_gap': max(student_gaps.values(), default=0), 'teacher_gaps': sum(teacher_gaps.values()), 'teacher_max_gap': max(teacher_gaps.values(), default=0), 'room_changes': room_change_count, 'weighted_room_change_cost': room_change_weighted, 'min_capacity_slack': min(capacity_slack) if capacity_slack else None, 'time_locks': len(inst.lock_time), 'room_locks': len(inst.lock_room), 'relation_count': len(getattr(inst, 'relations', ())) + len(inst.links), 'dependency_count': len(getattr(inst, 'dependencies', ())), 'hard_links_activated': hard_links_activated, 'linked_optional_activated': linked_optional_activated, 'linked_optional_satisfied': linked_optional_satisfied, 'linked_optional_weight_score': linked_optional_gained_weight, 'linked_optional_weight_fraction': linked_optional_gained_weight / linked_optional_possible_weight if linked_optional_possible_weight else 1.0, 'explicit_groups': len(groups_meta), 'mixed_home_groups': sum(len({inst.home_class[s] for s in inst.group_members.get(g, ())}) > 1 for g in groups_meta), 'sectioning_optimal': 'unknown'}


def write_report(path, result):
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['metric', 'value'])
        for k, value in result.items():
            if k != 'errors':
                w.writerow([k, value])
        for n, e in enumerate(result['errors'], 1):
            w.writerow([f'error_{n}', e])


def main():
    p = argparse.ArgumentParser()
    p.add_argument('constraints')
    p.add_argument('output')
    p.add_argument('--solver', default=str(Path(__file__).with_name('timetable_csv.py')))
    p.add_argument('--students-output')
    p.add_argument('--slots', type=int, default=40)
    p.add_argument('--slots-per-day', type=int, default=8)
    p.add_argument('--report')
    a = p.parse_args()
    result = validate(a.constraints, a.output, a.solver, a.students_output, a.slots, a.slots_per_day)
    for k, value in result.items():
        if k != 'errors':
            print(f'{k}={value}')
    for error in result['errors']:
        print(f'error={error}')
    if a.report:
        write_report(a.report, result)
    raise SystemExit(0 if result['valid'] else 2)


if __name__ == '__main__':
    main()
