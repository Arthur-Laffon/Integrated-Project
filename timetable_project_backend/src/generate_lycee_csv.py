from __future__ import annotations
import argparse
import csv
import math
import random
from collections import Counter, defaultdict

def curriculum(level, i):
    if level == '2nde':
        return [('FR', 4), ('MATH', 4), ('HG', 3), ('ENG', 3), ('L2', 2), ('PHYS', 3), ('SVT', 2), ('SES', 1), ('SNT', 1), ('EPS', 2), ('EMC', 1), ('AP', 4)]
    specs = ['NSI', 'MATHS_SPE', 'PHYS_SPE', 'SES_SPE', 'HGGSP']
    a, b, c = (specs[(i + j) % len(specs)] for j in range(3))
    if level == '1re':
        return [('FR', 4), ('MATH', 4), ('HG', 3), ('ENG', 2), ('L2', 2), ('EPS', 2), ('EMC', 1), ('ENSCI', 2), ('SES', 2), (a, 3), (b, 3), (c, 2)]
    return [('PHILO', 4), ('MATH', 3), ('HG', 3), ('ENG', 2), ('L2', 2), ('EPS', 2), ('EMC', 1), ('ENSCI', 2), ('SES', 2), (a, 2), (b, 2), (c, 2), ('AP', 2), ('ORAL', 1)]

def build(path, cohorts=12, seed=2026, teacher_load=16, professor_availability=0.8, reward_probability=0.0, link_probability=0.75, general_rooms=None, pc_rooms=None, lab_rooms=None, gym_rooms=None):
    rng = random.Random(seed)
    levels = ['2nde', '1re', 'Tle']
    groups = [f'{levels[i % 3]}{i // 3 + 1}' for i in range(cohorts)]
    cur = {}
    for i, g in enumerate(groups):
        level = '2nde' if g.startswith('2nde') else '1re' if g.startswith('1re') else 'Tle'
        cur[g] = curriculum(level, i)
    totals = defaultdict(int)
    for g in groups:
        for s, n in cur[g]:
            totals[s] += n
    pools = {}
    for s, n in totals.items():
        k = max(1, math.ceil(n / teacher_load))
        pools[s] = [f'{s}_P{i + 1:02d}' for i in range(k)]
    load = Counter()
    teacher = {}
    for g in groups:
        for s, n in cur[g]:
            pool = pools[s]
            m = min((load[p] for p in pool))
            cand = [p for p in pool if load[p] == m]
            p = rng.choice(cand)
            teacher[g, s] = p
            load[p] += n
    courses = []
    for g in groups:
        for s, n in cur[g]:
            for j in range(1, n + 1):
                eq = ''
                if s in {'SNT', 'NSI'}:
                    eq = 'computers'
                elif s == 'EPS':
                    eq = 'gym'
                elif s in {'PHYS', 'ENSCI'} and j == n or (s == 'SVT' and j == n):
                    eq = 'lab'
                courses.append({'id': f'{g}_{s}_{j}', 'department': g, 'professor': teacher[g, s], 'subject': s, 'required_equipment': eq})
    general_n = general_rooms if general_rooms is not None else cohorts + max(6, cohorts // 3)
    pc_n = pc_rooms if pc_rooms is not None else max(2, math.ceil(cohorts / 5))
    lab_n = lab_rooms if lab_rooms is not None else max(3, math.ceil(cohorts / 4))
    gym_n = gym_rooms if gym_rooms is not None else max(2, math.ceil(cohorts / 6))
    room_types = {'general': [f'R{i + 1:03d}' for i in range(general_n)], 'computers': [f'PC{i + 1}' for i in range(pc_n)], 'lab': [f'LAB{i + 1}' for i in range(lab_n)], 'gym': [f'GYM{i + 1}' for i in range(gym_n)]}
    used_g = defaultdict(set)
    used_p = defaultdict(set)
    used_type = defaultdict(Counter)
    ref = {}

    def scarcity(c):
        eq = c['required_equipment'] or 'general'
        return (len(room_types[eq]), -load[c['professor']], c['department'], c['subject'], c['id'])
    for c in sorted(courses, key=scarcity):
        eq = c['required_equipment'] or 'general'
        legal = [t for t in range(40) if t not in used_g[c['department']] and t not in used_p[c['professor']] and (used_type[t][eq] < len(room_types[eq]))]
        if not legal:
            raise RuntimeError('unable to construct a coherent synthetic instance with the selected resource counts')
        t = min(legal, key=lambda z: (sum(used_type[z].values()), rng.random()))
        ref[c['id']] = t
        used_g[c['department']].add(t)
        used_p[c['professor']].add(t)
        used_type[t][eq] += 1
    p_avail = {}
    for p in load:
        required = {ref[c['id']] for c in courses if c['professor'] == p}
        target = min(40, max(len(required) + 4, round(40 * professor_availability)))
        extra = list(set(range(40)) - required)
        rng.shuffle(extra)
        p_avail[p] = required | set(extra[:max(0, target - len(required))])
    room_rows = []
    for typ, rs in room_types.items():
        for r in rs:
            closed = set(rng.sample(range(40), k=rng.randint(0, 3)))
            av = set(range(40)) - closed
            eq = ''
            allow = '*'
            if typ == 'computers':
                eq, allow = ('computers', 'SNT;NSI')
            elif typ == 'lab':
                eq, allow = ('lab', 'PHYS;SVT;ENSCI;PHYS_SPE')
            elif typ == 'gym':
                eq, allow = ('gym', 'EPS')
            room_rows.append({'kind': 'room', 'id': r, 'available_slots': ';'.join(map(str, sorted(av))), 'equipment': eq, 'allowed_subjects': allow})
    by = defaultdict(list)
    for c in courses:
        by[c['department'], c['subject']].append(c)
    links = []
    for (g, s), xs in by.items():
        xs.sort(key=lambda c: int(c['id'].rsplit('_', 1)[1]))
        practical = [c for c in xs if c['required_equipment'] in {'lab', 'computers'}]
        if practical and len(xs) >= 2 and (rng.random() < link_probability):
            b = practical[-1]
            earlier = [a for a in xs if ref[a['id']] < ref[b['id']]]
            if earlier:
                a = max(earlier, key=lambda c: ref[c['id']])
                gap = ref[b['id']] - ref[a['id']]
                links.append({'kind': 'link', 'from_course': a['id'], 'to_course': b['id'], 'min_gap': '1', 'max_gap': str(max(gap, min(16, gap + 4))), 'same_day': 'true' if ref[a['id']] // 8 == ref[b['id']] // 8 else 'false'})
    rewards = []
    if reward_probability > 0:
        for d in groups:
            for c in courses:
                if c['department'] != d and rng.random() < reward_probability:
                    rewards.append({'kind': 'reward', 'department': d, 'target_course': c['id'], 'weight': str(rng.randint(1, 10))})
    cols = ['kind', 'id', 'department', 'professor', 'subject', 'available_slots', 'equipment', 'allowed_subjects', 'required_equipment', 'target_course', 'weight', 'from_course', 'to_course', 'min_gap', 'max_gap', 'same_day']
    rows = [dict(kind='course', **c) for c in courses]
    rows += [{'kind': 'professor', 'id': p, 'available_slots': ';'.join(map(str, sorted(av)))} for p, av in sorted(p_avail.items())]
    rows += room_rows
    rows += links
    rows += rewards
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    return {'cohorts': cohorts, 'sessions': len(courses), 'professors': len(p_avail), 'rooms': len(room_rows), 'links': len(links), 'rewards': len(rewards)}

def main():
    p = argparse.ArgumentParser()
    p.add_argument('output')
    p.add_argument('--cohorts', type=int, default=12)
    p.add_argument('--seed', type=int, default=2026)
    p.add_argument('--teacher-load', type=int, default=16)
    p.add_argument('--professor-availability', type=float, default=0.8)
    p.add_argument('--reward-probability', type=float, default=0.0)
    p.add_argument('--link-probability', type=float, default=0.75)
    p.add_argument('--general-rooms', type=int)
    p.add_argument('--pc-rooms', type=int)
    p.add_argument('--lab-rooms', type=int)
    p.add_argument('--gym-rooms', type=int)
    a = p.parse_args()
    info = build(a.output, a.cohorts, a.seed, a.teacher_load, a.professor_availability, a.reward_probability, a.link_probability, a.general_rooms, a.pc_rooms, a.lab_rooms, a.gym_rooms)
    print(' '.join((f'{k}={v}' for k, v in info.items())))
if __name__ == '__main__':
    main()
