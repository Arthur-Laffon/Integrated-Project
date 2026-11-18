from __future__ import annotations
import argparse
import csv
import math
import random
from collections import Counter, defaultdict

SPECS = ['MATHS_SPE', 'PHYS_SPE', 'SES_SPE', 'NSI', 'HGGSP', 'SVT_SPE']


def common_curriculum(level):
    if level == '2nde':
        return [('FR', 4), ('MATH', 4), ('HG', 3), ('ENG', 3), ('L2', 2), ('PHYS', 3), ('SVT', 2), ('SES', 2), ('SNT', 2), ('EPS', 2), ('EMC', 1)]
    if level == '1re':
        return [('FR', 4), ('HG', 3), ('ENG', 3), ('L2', 2), ('EPS', 2), ('ENSCI', 2), ('EMC', 1)]
    return [('PHILO', 4), ('HG', 3), ('ENG', 3), ('L2', 2), ('EPS', 2), ('ENSCI', 2), ('EMC', 1)]


def equipment_for(subject, session):
    if subject in {'NSI', 'SNT'}:
        return 'computers'
    if subject == 'EPS':
        return 'gym'
    if subject in {'PHYS', 'SVT', 'ENSCI', 'PHYS_SPE', 'SVT_SPE'} and session == 1:
        return 'lab'
    return ''


def choose_specs(rng, level):
    blocks = [
        [('MATHS_SPE', 1.7), ('HGGSP', 1.0)],
        [('PHYS_SPE', 1.35), ('SES_SPE', 1.2)],
        [('NSI', 0.8), ('SVT_SPE', 1.1)],
    ]
    chosen = []
    for block in blocks:
        names = [x for x, _ in block]
        weights = [w for _, w in block]
        chosen.append(rng.choices(names, weights=weights, k=1)[0])
    if level == '1re':
        return chosen
    drop = rng.randrange(3)
    return [x for i, x in enumerate(chosen) if i != drop]


def build(path, cohorts=9, seed=2026, class_min=28, class_max=34, section_capacity=30, teacher_load=18, professor_availability=0.9, option_probability=0.16, chronology_rate=0.0, room_weight_fraction=0.25):
    rng = random.Random(seed)
    levels = ['2nde', '1re', 'Tle']
    groups = [f'{levels[i % 3]}{i // 3 + 1}' for i in range(cohorts)]
    students = []
    home_students = defaultdict(list)
    student_specs = {}
    optional = {}
    for g in groups:
        n = rng.randint(class_min, class_max)
        level = '2nde' if g.startswith('2nde') else '1re' if g.startswith('1re') else 'Tle'
        for j in range(1, n + 1):
            s = f'{g}_S{j:02d}'
            students.append(s)
            home_students[g].append(s)
            if level in {'1re', 'Tle'}:
                student_specs[s] = choose_specs(rng, level)
            else:
                student_specs[s] = []
            opts = []
            if rng.random() < option_probability:
                opts.append('LATIN')
            if rng.random() < option_probability * 0.8:
                opts.append('EURO')
            optional[s] = opts[:1]
    units = []
    courses = []
    for g in groups:
        level = '2nde' if g.startswith('2nde') else '1re' if g.startswith('1re') else 'Tle'
        for subj, hours in common_curriculum(level):
            ids = []
            for h in range(1, hours + 1):
                cid = f'{g}_{subj}_{h}'
                ids.append(cid)
                courses.append({'id': cid, 'department': g, 'subject': subj, 'required_equipment': equipment_for(subj, h), 'student_count': str(len(home_students[g])), 'hard_group': 'true'})
            units.append((subj, ids))
    by_level_spec = defaultdict(list)
    for s, specs in student_specs.items():
        level = '1re' if s.startswith('1re') else 'Tle' if s.startswith('Tle') else ''
        for sp in specs:
            by_level_spec[level, sp].append(s)
    requests = []
    for (level, sp), ss in sorted(by_level_spec.items()):
        family = f'{level}_{sp}'
        nsec = max(1, math.ceil(len(ss) / section_capacity))
        hours = 4 if level == '1re' else 6
        for k in range(nsec):
            sec = f'{family}_{chr(65 + k)}'
            ids = []
            for h in range(1, hours + 1):
                cid = f'{sec}_{h}'
                ids.append(cid)
                courses.append({'id': cid, 'department': '', 'subject': sp, 'required_equipment': equipment_for(sp, h), 'section': sec, 'family': family, 'section_capacity': str(section_capacity), 'hard_group': 'false'})
            units.append((sp, ids))
        for s in ss:
            requests.append({'kind': 'request', 'student_id': s, 'family': family, 'required': 'true', 'weight': '1'})
    by_level_opt = defaultdict(list)
    for s, opts in optional.items():
        level = '2nde' if s.startswith('2nde') else '1re' if s.startswith('1re') else 'Tle'
        for op in opts:
            by_level_opt[level, op].append(s)
    for (level, op), ss in sorted(by_level_opt.items()):
        if len(ss) < 4:
            continue
        family = f'{level}_OPT_{op}'
        opt_cap = min(section_capacity, 26)
        nsec = max(1, math.ceil(len(ss) / opt_cap))
        for k in range(nsec):
            sec = f'{family}_{chr(65 + k)}'
            ids = []
            for h in range(1, 3):
                cid = f'{sec}_{h}'
                ids.append(cid)
                courses.append({'id': cid, 'department': '', 'subject': op, 'required_equipment': '', 'section': sec, 'family': family, 'section_capacity': str(opt_cap), 'hard_group': 'false'})
            units.append((op, ids))
        for s in ss:
            requests.append({'kind': 'request', 'student_id': s, 'family': family, 'required': 'false', 'weight': str(rng.choice([1, 1, 2, 2, 3]))})
    by_id = {c['id']: c for c in courses}
    subject_hours = Counter()
    max_parallel = Counter()
    family_unit_count = Counter()
    for subj, ids in units:
        subject_hours[subj] += len(ids)
        fam = by_id[ids[0]].get('family', '')
        if fam:
            family_unit_count[subj, fam] += 1
    for (subj, fam), n in family_unit_count.items():
        max_parallel[subj] = max(max_parallel[subj], n)
    pools = {}
    for subj, hours in subject_hours.items():
        k = max(1, math.ceil(hours / teacher_load), max_parallel[subj])
        pools[subj] = [f'{subj}_P{i + 1:02d}' for i in range(k)]
    loads = Counter()
    used_family = defaultdict(set)
    ordered_units = sorted(units, key=lambda x: (0 if by_id[x[1][0]].get('family', '') else 1, -len(x[1])))
    for subj, ids in ordered_units:
        fam = by_id[ids[0]].get('family', '')
        pool = pools[subj]
        cand = [p for p in pool if not fam or p not in used_family[fam]]
        if not cand:
            pnew = f'{subj}_P{len(pool) + 1:02d}'
            pool.append(pnew)
            cand = [pnew]
        p = min(cand, key=lambda x: (loads[x], x))
        loads[p] += len(ids)
        if fam:
            used_family[fam].add(p)
        for cid in ids:
            by_id[cid]['professor'] = p
    prof_avail = {}
    pref_rows = []
    for p in sorted(loads):
        target = max(loads[p] + 8, int(round(40 * professor_availability)))
        target = min(40, target)
        avail = set(rng.sample(range(40), target))
        prof_avail[p] = avail
        prefer_day = rng.randrange(5)
        avoid_day = rng.randrange(5)
        while avoid_day == prefer_day:
            avoid_day = rng.randrange(5)
        pref_rows.append({'kind': 'preference', 'professor': p, 'slots': ';'.join(str(8 * prefer_day + x) for x in range(8)), 'weight': '1.5'})
        half = rng.choice([(0, 4), (4, 8)])
        pref_rows.append({'kind': 'preference', 'professor': p, 'slots': ';'.join(str(8 * avoid_day + x) for x in range(*half)), 'weight': '-2.5'})
    general_n = cohorts + max(4, cohorts // 2)
    lab_n = max(3, math.ceil(cohorts / 3))
    pc_n = max(2, math.ceil(cohorts / 4))
    gym_n = max(2, math.ceil(cohorts / 4))
    room_rows = []
    for i in range(general_n):
        cap = rng.randint(max(class_max, 34), max(class_max + 8, 42))
        room_rows.append({'kind': 'room', 'id': f'R{i + 1:03d}', 'available_slots': '*', 'capacity': str(cap), 'room_type': 'general', 'allowed_subjects': '*'})
    for i in range(lab_n):
        room_rows.append({'kind': 'room', 'id': f'LAB{i + 1}', 'available_slots': '*', 'capacity': str(rng.randint(max(class_max, section_capacity), max(class_max, section_capacity) + 4)), 'room_type': 'lab', 'equipment': 'lab', 'allowed_subjects': 'PHYS;SVT;ENSCI;PHYS_SPE;SVT_SPE'})
    for i in range(pc_n):
        room_rows.append({'kind': 'room', 'id': f'PC{i + 1}', 'available_slots': '*', 'capacity': str(rng.randint(max(class_max, section_capacity), max(class_max, section_capacity) + 4)), 'room_type': 'computer', 'equipment': 'computers', 'allowed_subjects': 'NSI;SNT'})
    for i in range(gym_n):
        room_rows.append({'kind': 'room', 'id': f'GYM{i + 1}', 'available_slots': '*', 'capacity': '70', 'room_type': 'gym', 'equipment': 'gym', 'allowed_subjects': 'EPS'})
    student_rows = [{'kind': 'student', 'id': s, 'home_class': next(g for g, ss in home_students.items() if s in ss)} for s in students]
    professor_rows = [{'kind': 'professor', 'id': p, 'available_slots': ';'.join(map(str, sorted(a))), 'room_change_weight': str(rng.choice((3, 5, 8)) if rng.random() < room_weight_fraction else 1)} for p, a in sorted(prof_avail.items())]
    chronology_rows = []
    for subj, ids in units:
        if len(ids) >= 3 and rng.random() < chronology_rate:
            chronology_rows.append({'kind': 'relation', 'relation': 'BETWEEN', 'course': ids[1], 'before': ids[0], 'after': ids[2]})
            if len(ids) >= 4 and rng.random() < 0.4:
                chronology_rows.append({'kind': 'relation', 'relation': 'BETWEEN', 'course': ids[3], 'before': ids[0], 'after': ids[2]})
    cols = ['from_family', 'to_family', 'relation', 'course', 'before', 'after', 'room_change_weight', 'max_room_changes_per_day', 'kind', 'id', 'department', 'professor', 'subject', 'available_slots', 'equipment', 'allowed_subjects', 'required_equipment', 'capacity', 'room_type', 'student_count', 'section', 'family', 'section_capacity', 'hard_group', 'student_id', 'home_class', 'fixed_courses', 'required', 'weight', 'locked_section', 'slots', 'target_course', 'from_course', 'to_course', 'min_gap', 'max_gap', 'same_day', 'slot', 'room']
    rows = [dict(kind='course', **c) for c in courses] + professor_rows + room_rows + student_rows + requests + pref_rows + chronology_rows
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    return {'cohorts': cohorts, 'students': len(students), 'sessions': len(courses), 'professors': len(prof_avail), 'rooms': len(room_rows), 'required_requests': sum(1 for r in requests if r['required'] == 'true'), 'optional_requests': sum(1 for r in requests if r['required'] == 'false'), 'sections': len({c.get('section') for c in courses if c.get('section')}), 'chronology_relations': len(chronology_rows)}


def main():
    p = argparse.ArgumentParser()
    p.add_argument('output')
    p.add_argument('--cohorts', type=int, default=9)
    p.add_argument('--seed', type=int, default=2026)
    p.add_argument('--class-min', type=int, default=28)
    p.add_argument('--class-max', type=int, default=34)
    p.add_argument('--section-capacity', type=int, default=30)
    p.add_argument('--teacher-load', type=int, default=18)
    p.add_argument('--professor-availability', type=float, default=0.9)
    p.add_argument('--option-probability', type=float, default=0.16)
    p.add_argument('--chronology-rate', type=float, default=0.0)
    p.add_argument('--room-weight-fraction', type=float, default=0.25)
    a = p.parse_args()
    info = build(a.output, a.cohorts, a.seed, a.class_min, a.class_max, a.section_capacity, a.teacher_load, a.professor_availability, a.option_probability, a.chronology_rate, a.room_weight_fraction)
    print(' '.join(f'{k}={v}' for k, v in info.items()))

if __name__ == '__main__':
    main()
