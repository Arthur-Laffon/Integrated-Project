"""Build French-lycée test inputs *from* a known valid timetable.

This is a constructive / planted-witness generator, not a solver.  The timetable
and mandatory sectioning are formed first, and only then are teacher availability,
rooms, and the public constraints CSV written.  The unmodified independent
validator is run by default and the generator fails closed on any error.

The planted timetable is NOT encoded as lock constraints in the input, so a
solver still needs to discover a timetable and section assignments itself.
See PLANTED_FEASIBILITY_ASSUMPTIONS.md for the deliberately favourable design.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from generate_lycee_csv import COLUMNS, WEIGHTS, choose_pathway
from validate_timetable_csv import validate

N_SLOTS = 40
SLOTS_PER_DAY = 8
GRADES = ('2nde', '1re', 'Tle')


@dataclass
class TeachingUnit:
    subject: str
    group: str
    courses: tuple[str, ...]
    slots: tuple[int, ...]


def build(out_dir: Path, cohorts: int = 12, specialties: int = 5,
          seed: int = 2026, class_size: int = 30, section_capacity: int = 30,
          group_capacity: int = 30, teacher_load: int = 18,
          teacher_availability: float = 0.90,
          chronology_rate: float = 0.0) -> dict:
    if cohorts < 3 or specialties not in (4, 5, 6):
        raise ValueError('cohorts must be >= 3 and specialties must be 4, 5 or 6')
    if not (12 <= class_size <= group_capacity <= 40):
        raise ValueError('require 12 <= class_size <= group_capacity <= 40')
    if not (12 <= section_capacity <= 40) or teacher_load < 6:
        raise ValueError('section capacity must be 12..40; teacher load >= 6')
    if not (0.50 <= teacher_availability <= 1.0):
        raise ValueError('teacher availability must be 0.50..1.0')
    if not (0.0 <= chronology_rate <= 1.0):
        raise ValueError('chronology rate must be 0..1')

    rng = random.Random(seed)
    offered = ('MATHS_SPE', 'PHYS_SPE', 'SES_SPE', 'HGGSP', 'SVT_SPE', 'NSI')[:specialties]
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    prefix = f'planted_{cohorts}c_{specialties}spec_seed{seed}'
    input_path = out_dir / f'{prefix}_input.csv'
    timetable_path = out_dir / f'{prefix}_witness_timetable.csv'
    student_path = out_dir / f'{prefix}_witness_students.csv'
    metadata_path = out_dir / f'{prefix}_manifest.json'

    rows = []
    units: list[TeachingUnit] = []
    phi: dict[str, int] = {}
    equipment_by_course: dict[str, str] = {}
    grade_homes = defaultdict(list)
    home_students = defaultdict(list)
    grade_students = defaultdict(list)
    profiles = {}
    requests = []
    planted_choices = defaultdict(dict)
    section_members = defaultdict(list)
    members = defaultdict(list)

    def add_group(group, subject, kind, grade, students, *, capacity=None, parent=''):
        rows.append({'kind': 'group', 'id': group, 'subject': subject,
                     'group_type': kind, 'grade': grade,
                     'capacity': str(capacity if capacity is not None else max(1, len(students))),
                     'parent_group': parent})
        members[group].extend(students)

    def add_unit(group, subject, slots, *, department='', family='',
                 section='', section_cap=None, equipment=''):
        slots = tuple(slots)
        equipment_by_hour = (tuple(equipment) if not isinstance(equipment, str)
                             else (equipment,) * len(slots))
        if len(equipment_by_hour) != len(slots):
            raise ValueError('equipment list must have one entry per scheduled hour')
        if len(set(slots)) != len(slots) or any(t < 0 or t >= N_SLOTS for t in slots):
            raise AssertionError(f'invalid slots {group}/{subject}: {slots}')
        course_ids = []
        for k, (t, equipment_at_hour) in enumerate(zip(slots, equipment_by_hour), 1):
            cid = f'{group}_{subject}_{k:02d}' if not section else f'{section}_{k:02d}'
            if cid in phi:
                raise AssertionError(f'duplicate course ID: {cid}')
            course_ids.append(cid)
            phi[cid] = t
            equipment_by_course[cid] = equipment_at_hour
            rows.append({'kind': 'course', 'id': cid, 'group_id': group,
                         'subject': subject, 'department': department,
                         'hard_group': str(bool(department)).lower(),
                         'section': section, 'family': family,
                         'section_capacity': str(section_cap) if section else '',
                         'required_equipment': equipment_at_hour,
                         'student_count': ''})
        units.append(TeachingUnit(subject, group, tuple(course_ids), slots))

    # Population: exactly class_size pupils per home class; grade-balanced.
    for i in range(cohorts):
        grade = GRADES[i % 3]
        home = f'{grade}{i // 3 + 1:02d}'
        grade_homes[grade].append(home)
        for j in range(class_size):
            student = f'{home}_S{j + 1:02d}'
            home_students[home].append(student)
            grade_students[grade].append(student)
            lva = 'ENG' if rng.random() < 0.90 else 'GER'
            lvb = 'ESP' if rng.random() < 0.88 else 'ITA'
            profiles[student] = {'kind': 'student', 'id': student, 'grade': grade,
                                 'home_class': home, 'lva': lva, 'lvb': lvb}

    # Fixed courses use grade-wide reserved windows.  Within a home class they
    # never overlap, but multiple distinct homes can hold courses in parallel.
    core = {
        '2nde': [('FR', 4), ('MATH', 4), ('HG', 3), ('PHYS', 2),
                 ('SVT', 1), ('SES', 2), ('SNT', 2)],
        '1re': [('FR', 4), ('HG', 3)],
        'Tle': [('PHILO', 4), ('HG', 3)]}
    for grade, homes in grade_homes.items():
        for home in homes:
            group = f'TC_{home}'
            add_group(group, 'CORE', 'common', grade, home_students[home], parent=home)
            current = 0
            for subject, count in core[grade]:
                add_unit(group, subject, range(current, current + count),
                         department=home, equipment='computers' if subject == 'SNT' else '')
                current += count
            if grade == '2nde':
                subset = list(home_students[home])
                rng.shuffle(subset)
                half = (len(subset) + 1) // 2
                for lab_name, pupils in (('A', subset[:half]), ('B', subset[half:])):
                    for subject, slot in (('PHYS', 18), ('SVT', 19)):
                        lab = f'LAB_{home}_{subject}_{lab_name}'
                        add_group(lab, subject, 'practical', grade, pupils,
                                  capacity=group_capacity, parent=home)
                        add_unit(lab, subject, [slot], equipment='lab')

    # Mixed-home-class fixed teaching groups.  Each track has its own randomly
    # permuted reserved window, reducing gym peaks while preserving no-overlap.
    for grade in GRADES:
        pupils = list(grade_students[grade])
        rng.shuffle(pupils)
        n_tracks = math.ceil(len(pupils) / group_capacity)
        tracks = [[] for _ in range(n_tracks)]
        for j, s in enumerate(pupils):
            tracks[j % n_tracks].append(s)
        for track_index, track in enumerate(tracks, 1):
            track_name = f'{grade}_TRACK_{track_index:02d}'
            reserve = list(range(20, 27) if grade == '2nde' else range(7, 16))
            rng.shuffle(reserve)
            take = iter(reserve)
            allocations = {
                'LVA': [next(take) for _ in range(3)],
                'LVB': [next(take) for _ in range(1 if grade == 'Tle' else 2)],
                'EPS': [next(take) for _ in range(2)]}
            if grade != '2nde':
                allocations['ENSCI'] = [next(take) for _ in range(2)]
            for role in ('LVA', 'LVB'):
                language_groups = defaultdict(list)
                for s in track:
                    language_groups[profiles[s][role.lower()]].append(s)
                for language, attendees in sorted(language_groups.items()):
                    group = f'{track_name}_{role}_{language}'
                    add_group(group, language, role, grade, attendees,
                              capacity=group_capacity)
                    add_unit(group, language, allocations[role])
            group = f'{track_name}_EPS'
            add_group(group, 'EPS', 'EPS', grade, track, capacity=group_capacity)
            add_unit(group, 'EPS', allocations['EPS'], equipment='gym')
            if grade != '2nde':
                group = f'{track_name}_ENSCI'
                add_group(group, 'ENSCI', 'science', grade, track, capacity=group_capacity)
                add_unit(group, 'ENSCI', allocations['ENSCI'])
            for s in track:
                profiles[s]['track'] = track_name

    # Entire grade-subject families share a common scheduling block.  1re
    # uses 5 distinct 4-slot blocks.  Tle uses four 6-slot blocks, allowing
    # five offered specialties by making the last two share a block and
    # explicitly forbidding pupils from requesting those two simultaneously.
    term_colors = {subject: min(i, 3) for i, subject in enumerate(offered)}
    sections_by_family = defaultdict(list)
    chosen_subjects = {}
    for grade in ('1re', 'Tle'):
        for s in grade_students[grade]:
            if grade == '1re':
                selected = tuple(choose_pathway(rng, offered))
                profiles[s]['previous_specialities'] = ';'.join(selected)
            else:
                pairs = [(a, b) for i, a in enumerate(offered)
                         for b in offered[i + 1:] if term_colors[a] != term_colors[b]]
                weights = [WEIGHTS[a] * WEIGHTS[b] for a, b in pairs]
                selected = tuple(rng.choices(pairs, weights=weights, k=1)[0])
                extra = rng.choice([sub for sub in offered if sub not in selected])
                profiles[s]['previous_specialities'] = ';'.join((*selected, extra))
            chosen_subjects[s] = selected

        by_subject = defaultdict(list)
        for s in grade_students[grade]:
            for subject in chosen_subjects[s]:
                by_subject[subject].append(s)
        for i, subject in enumerate(offered):
            population = by_subject[subject]
            if not population:
                continue
            family = f'{grade}_{subject}'
            number = math.ceil(len(population) / section_capacity)
            for k in range(number):
                section = f'{family}_{k + 1:02d}'
                sections_by_family[family].append(section)
                add_group(section, subject, 'speciality', grade, [],
                          capacity=section_capacity)
                color = i if grade == '1re' else term_colors[subject]
                hours = 4 if grade == '1re' else 6
                slots = range(16 + color * hours, 16 + (color + 1) * hours)
                # Physics has one practical hour requiring a lab.
                equipment = (('lab',) + ('',) * (hours - 1)
                             if subject == 'PHYS_SPE' else
                             'computers' if subject == 'NSI' else '')
                add_unit(section, subject, slots, family=family, section=section,
                         section_cap=section_capacity, equipment=equipment)
            shuffled = list(population)
            rng.shuffle(shuffled)
            for k, s in enumerate(shuffled):
                sec = sections_by_family[family][k % number]
                planted_choices[s][family] = sec
                section_members[sec].append(s)
                requests.append({'kind': 'request', 'student_id': s,
                                 'family': family, 'required': 'true', 'weight': '1'})

    # Teachers are allocated AFTER the planted times: subject-compatible,
    # no overlapping lessons, load <= teacher_load.  Availability is sampled
    # around their planted commitments, never the reverse.
    professor_slots = defaultdict(set)
    professor_hours = Counter()
    professor_by_subject = defaultdict(list)
    teacher_of_course = {}
    for unit in sorted(units, key=lambda u: (-len(u.slots), u.subject, u.group)):
        candidates = [p for p in professor_by_subject[unit.subject]
                      if professor_hours[p] + len(unit.slots) <= teacher_load
                      and not professor_slots[p].intersection(unit.slots)]
        if candidates:
            professor = min(candidates, key=lambda p: (professor_hours[p], p))
        else:
            professor = f'{unit.subject}_P{len(professor_by_subject[unit.subject]) + 1:03d}'
            professor_by_subject[unit.subject].append(professor)
        professor_slots[professor].update(unit.slots)
        professor_hours[professor] += len(unit.slots)
        for cid in unit.courses:
            teacher_of_course[cid] = professor
    for row in rows:
        if row.get('kind') == 'course':
            row['professor'] = teacher_of_course[row['id']]
    for professor, used in sorted(professor_slots.items()):
        goal = max(len(used), int(round(N_SLOTS * teacher_availability)))
        free = sorted(set(range(N_SLOTS)) - used)
        available = sorted(used | set(rng.sample(free, goal - len(used))))
        rows.append({'kind': 'professor', 'id': professor,
                     'available_slots': ';'.join(map(str, available)),
                     'room_change_weight': '1'})

    # Room inventory is derived from peak demand, with one spare of each type.
    # These generous resources are intentional and recorded in the manifest.
    by_kind_slot = defaultdict(list)
    for cid, equipment in equipment_by_course.items():
        kind = {'': 'general', 'lab': 'lab', 'computers': 'computer', 'gym': 'gym'}[equipment]
        by_kind_slot[kind, phi[cid]].append(cid)
    rooms_by_kind = {}
    room_of_course = {}
    for kind in ('general', 'lab', 'computer', 'gym'):
        peak = max((len(by_kind_slot[kind, t]) for t in range(N_SLOTS)), default=0)
        count = peak + (1 if peak else 0)
        rooms_by_kind[kind] = [f'{kind.upper()}_{k + 1:03d}' for k in range(count)]
        for room in rooms_by_kind[kind]:
            rows.append({'kind': 'room', 'id': room, 'capacity': str(max(40, section_capacity)),
                         'room_type': kind, 'equipment':
                         {'general': '', 'lab': 'lab', 'computer': 'computers', 'gym': 'gym'}[kind],
                         'available_slots': '*', 'allowed_subjects': '*'})
        for t in range(N_SLOTS):
            for j, cid in enumerate(sorted(by_kind_slot[kind, t])):
                room_of_course[cid] = rooms_by_kind[kind][j]
    assert set(phi) == set(teacher_of_course) == set(room_of_course)

    # A small optional quantity of chronological links; only constraints
    # known to be satisfied by the certificate are included.
    for unit in units:
        ordered = sorted(unit.courses, key=phi.__getitem__)
        for a, b in zip(ordered, ordered[1:]):
            if rng.random() < chronology_rate:
                rows.append({'kind': 'link', 'from_course': a, 'to_course': b,
                             'min_gap': '1'})
    for group, students in members.items():
        for s in students:
            rows.append({'kind': 'membership', 'student_id': s, 'group_id': group})
    rows.extend(profiles.values())
    rows.extend(requests)
    with input_path.open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    # Produce an independent, portable ground-truth certificate (not passed
    # to the solver).  Determine fixed attendance from group membership rather
    # than by trusting the solver's inferred attendee sets.
    course_by_group = defaultdict(list)
    section_courses = defaultdict(list)
    courses_by_home_without_group = defaultdict(list)
    course_rows = [r for r in rows if r['kind'] == 'course']
    for r in course_rows:
        if r.get('section'):
            section_courses[r['section']].append(r['id'])
        elif r.get('group_id'):
            course_by_group[r['group_id']].append(r['id'])
        elif r.get('department') and r.get('hard_group') == 'true':
            courses_by_home_without_group[r['department']].append(r['id'])
    fixed_by_student = defaultdict(set)
    for group, students in members.items():
        for s in students:
            fixed_by_student[s].update(course_by_group[group])
    for s, p in profiles.items():
        fixed_by_student[s].update(courses_by_home_without_group[p['home_class']])

    with timetable_path.open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=['slot_index', 'timeslot', 'assignments'])
        writer.writeheader()
        for t in range(N_SLOTS):
            triples = sorted((teacher_of_course[c], c, room_of_course[c])
                             for c in phi if phi[c] == t)
            writer.writerow({'slot_index': t, 'timeslot': str(t),
                             'assignments': '; '.join(f'({p},{c},{room})' for p, c, room in triples)})
    with student_path.open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=['student', 'home_class', 'slot_index',
                                               'timeslot', 'course', 'subject',
                                               'professor', 'room', 'section'])
        writer.writeheader()
        subject_by_course = {r['id']: r['subject'] for r in course_rows}
        section_of_course = {r['id']: r.get('section', '') for r in course_rows}
        for s in sorted(profiles):
            attended = set(fixed_by_student[s])
            for sec in planted_choices[s].values():
                attended.update(section_courses[sec])
            for cid in sorted(attended, key=lambda c: (phi[c], c)):
                writer.writerow({'student': s, 'home_class': profiles[s]['home_class'],
                                 'slot_index': phi[cid], 'timeslot': str(phi[cid]),
                                 'course': cid, 'subject': subject_by_course[cid],
                                 'professor': teacher_of_course[cid],
                                 'room': room_of_course[cid],
                                 'section': section_of_course[cid]})

    report = validate(input_path, timetable_path, ROOT / 'timetable_csv.py',
                      student_path, N_SLOTS, SLOTS_PER_DAY)
    if not report['valid']:
        raise AssertionError(f'planted witness is invalid: {report["errors"][:12]}')
    result = {'case': prefix, 'status': 'PLANTED_FEASIBLE', 'seed': seed,
              'cohorts': cohorts, 'specialties': specialties,
              'students': len(profiles), 'lessons': len(phi),
              'mandatory_requests': len(requests),
              'professors': len(professor_slots),
              'teacher_max_load': max(professor_hours.values()),
              'rooms': {kind: len(rooms) for kind, rooms in rooms_by_kind.items()},
              'teacher_availability_fraction': teacher_availability,
              'effective_teacher_availability_fraction': round(sum(max(len(used), int(round(N_SLOTS * teacher_availability))) for used in professor_slots.values()) / (N_SLOTS * len(professor_slots)), 4),
              'offered_specialties': list(offered),
              'terminal_specialty_blocks': {subject: term_colors[subject] for subject in offered},
              'class_size': class_size, 'group_capacity': group_capacity,
              'section_capacity': section_capacity,
              'chronology_rate': chronology_rate,
              'validation': {'valid': report['valid'],
                             'courses': report['courses'],
                             'required_requests': report['required_requests'],
                             'errors': report['errors']},
              'files': {'input': input_path.name,
                        'witness_timetable': timetable_path.name,
                        'witness_students': student_path.name}}
    result['sha256'] = {key: hashlib.sha256(path.read_bytes()).hexdigest()
                        for key, path in (('input', input_path),
                                          ('witness_timetable', timetable_path),
                                          ('witness_students', student_path))}
    metadata_path.write_text(json.dumps(result, indent=2), encoding='utf-8')
    return result


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output-dir', type=Path, default=ROOT / 'benchmarks' / 'planted')
    p.add_argument('--cohorts', type=int, nargs='+', default=[9, 12, 18, 24, 33])
    p.add_argument('--specialties', type=int, nargs='+', choices=[4, 5, 6], default=[4, 5, 6])
    p.add_argument('--seed', type=int, default=2026)
    p.add_argument('--class-size', type=int, default=30)
    p.add_argument('--section-capacity', type=int, default=30)
    p.add_argument('--group-capacity', type=int, default=30)
    p.add_argument('--teacher-load', type=int, default=18)
    p.add_argument('--teacher-availability', type=float, default=0.90)
    p.add_argument('--chronology-rate', type=float, default=0.0)
    a = p.parse_args(argv)
    for cohorts in a.cohorts:
        for specialties in a.specialties:
            result = build(a.output_dir, cohorts, specialties, a.seed,
                           a.class_size, a.section_capacity, a.group_capacity,
                           a.teacher_load, a.teacher_availability,
                           a.chronology_rate)
            print(f"{result['case']:32s} students={result['students']:4d} "
                  f"lessons={result['lessons']:4d} mandatory={result['mandatory_requests']:4d} "
                  f"witness_valid={result['validation']['valid']}", flush=True)


if __name__ == '__main__':
    main()
