from __future__ import annotations
import argparse
import csv
import itertools
import math
import random
from collections import Counter, defaultdict

from generate_lycee_csv_legacy import build as legacy_build, equipment_for

SPECS = ('MATHS_SPE', 'PHYS_SPE', 'SES_SPE', 'NSI', 'HGGSP', 'SVT_SPE')
WEIGHTS = {'MATHS_SPE': 2.7, 'PHYS_SPE': 2.0, 'SES_SPE': 2.0, 'NSI': 0.7, 'HGGSP': 1.7, 'SVT_SPE': 1.7}
COLUMNS = ['kind', 'id', 'student_id', 'grade', 'home_class', 'group_id', 'group_type', 'parent_group', 'capacity', 'previous_specialities', 'lva', 'lvb', 'track', 'department', 'professor', 'subject', 'available_slots', 'equipment', 'allowed_subjects', 'required_equipment', 'room_type', 'student_count', 'section', 'family', 'section_capacity', 'hard_group', 'fixed_courses', 'required', 'weight', 'locked_section', 'slots', 'target_course', 'from_course', 'to_course', 'min_gap', 'max_gap', 'same_day', 'slot', 'room', 'relation', 'course', 'before', 'after', 'room_change_weight', 'max_room_changes_per_day', 'from_family', 'to_family']


def choose_pathway(rng, offered):
    triples = list(itertools.combinations(offered, 3))
    weights = []
    for tr in triples:
        w = math.prod(WEIGHTS[s] for s in tr)
        if {'MATHS_SPE', 'PHYS_SPE'} <= set(tr):
            w *= 1.8
        if {'HGGSP', 'SES_SPE'} <= set(tr):
            w *= 1.9
        if {'PHYS_SPE', 'SVT_SPE'} <= set(tr):
            w *= 1.5
        weights.append(w)
    return list(rng.choices(triples, weights=weights, k=1)[0])


def build(path, cohorts=9, seed=2026, class_min=28, class_max=34, section_capacity=30, teacher_load=18, professor_availability=0.9, option_probability=0.16, chronology_rate=0.0, room_weight_fraction=0.25, group_capacity=30, mode='french', specialities=None, language_diversity=0.05):
    if mode == 'legacy':
        return legacy_build(path, cohorts, seed, class_min, class_max, section_capacity, teacher_load, professor_availability, option_probability, chronology_rate, room_weight_fraction)
    rng = random.Random(seed)
    offered = tuple(specialities or ('MATHS_SPE','PHYS_SPE','SES_SPE','HGGSP','SVT_SPE'))
    if len(offered) < 3 or len(set(offered)) != len(offered) or any(x not in SPECS for x in offered):
        raise ValueError('specialities must list at least three distinct supported subjects')
    grades = ('2nde', '1re', 'Tle')
    homes = [f'{grades[i % 3]}{i // 3 + 1}' for i in range(cohorts)]
    students, home_students, profiles, student_specs, optional = [], defaultdict(list), {}, {}, {}
    for home in homes:
        grade = next(g for g in grades if home.startswith(g))
        for j in range(rng.randint(class_min, class_max)):
            s = f'{home}_S{j + 1:02d}'
            students.append(s)
            home_students[home].append(s)
            previous = choose_pathway(rng, offered) if grade in {'1re', 'Tle'} else []
            specs = list(previous)
            if grade == 'Tle':
                # A terminale pupil retains two of the three previously selected subjects.
                drop = rng.choices(previous, weights=[1 / WEIGHTS[x] for x in previous], k=1)[0]
                specs.remove(drop)
            lva = 'GER' if rng.random() < language_diversity / 3 else 'ENG'
            lvb = 'GER' if rng.random() < language_diversity else 'ESP'
            if lvb == lva:
                lvb = 'ITA'
            profiles[s] = {'grade': grade, 'home_class': home, 'lva': lva, 'lvb': lvb, 'previous_specialities': ';'.join(previous)}
            student_specs[s] = specs
            choices = []
            if rng.random() < option_probability:
                choices.append('LATIN')
            if rng.random() < option_probability * 0.8:
                choices.append('EURO')
            optional[s] = choices[:1]

    # Stable mixed-home-class tracks coordinate fixed group memberships without restricting personal specialty choices.
    grade_tracks = defaultdict(list)
    for grade in grades:
        population = [s for s in students if profiles[s]['grade'] == grade]
        rng.shuffle(population)
        count = max(1, math.ceil(len(population) / group_capacity))
        grade_tracks[grade] = [[] for _ in range(count)]
        for i, s in enumerate(population):
            track = i % count
            grade_tracks[grade][track].append(s)
            profiles[s]['track'] = f'{grade}_TRACK_{track+1:02d}'

    courses, units, groups, members, requests = [], [], {}, defaultdict(set), []
    def new_group(group, subject, kind, grade, pupils, cap=None, parent=''):
        if group in groups:
            raise ValueError(f'duplicate teaching group {group}')
        pupils = list(pupils)
        groups[group] = {'kind': 'group', 'id': group, 'grade': grade, 'subject': subject, 'group_type': kind, 'capacity': str(cap or max(1, len(pupils))), 'parent_group': parent}
        members[group].update(pupils)
        return group

    def new_unit(group, subject, count, *, equipment=None, dept='', family='', sec='', section_cap=0):
        ids = []
        for n in range(1, count + 1):
            cid = f'{group}_{subject}_{n}' if not sec else f'{sec}_{n}'
            ids.append(cid)
            courses.append({'kind':'course', 'id':cid, 'group_id':group, 'department':dept, 'subject':subject,
                            'required_equipment': equipment if equipment is not None else equipment_for(subject, n),
                            'section':sec, 'family':family, 'section_capacity':str(section_cap) if sec else '',
                            'student_count':str(len(members[group])) if not sec else '',
                            'hard_group':'true' if dept and not sec else 'false'})
        units.append((subject, ids, family))

    # Each administrative class retains a common-course group, but other lessons are independently grouped.
    for home, ss in home_students.items():
        grade = profiles[ss[0]]['grade']
        group = new_group(f'TC_{home}', 'CORE', 'common', grade, ss, parent=home)
        if grade == '2nde':
            core = [('FR',4),('MATH',4),('HG',3),('PHYS',2),('SVT',1),('SES',2),('SNT',2)]
        elif grade == '1re':
            core = [('FR',4),('HG',3)]
        else:
            core = [('PHILO',4),('HG',3)]
        for subj, hours in core:
            new_unit(group, subj, hours, dept=home)
        if grade == '2nde':
            shuffled = list(ss)
            rng.shuffle(shuffled)
            mid = (len(shuffled)+1)//2
            for letter, subset in (('A', shuffled[:mid]),('B', shuffled[mid:])):
                for subj in ('PHYS','SVT'):
                    g = new_group(f'LAB_{home}_{subj}_{letter}',subj,'practical',grade,subset, parent=home)
                    new_unit(g,subj,1,equipment='lab')

    def distribute(pool, cap):
        pool = list(pool)
        rng.shuffle(pool)
        n = max(1, math.ceil(len(pool)/cap))
        chunks = [[] for _ in range(n)]
        for idx,s in enumerate(pool):
            chunks[idx % n].append(s)
        return chunks

    # A stable pedagogical track is shared by EPS/science; language classes may subdivide it.
    # None of these tracks controls the student's speciality selection.
    for grade in grades:
        for track, pupils in enumerate(grade_tracks[grade], 1):
            for role, hours in (('LVA',3),('LVB',2 if grade != 'Tle' else 1)):
                by_language = defaultdict(list)
                for s in pupils:
                    by_language[profiles[s][role.lower()]].append(s)
                for language, subset in sorted(by_language.items()):
                    g = new_group(f'{grade}_TRACK_{track:02d}_{role}_{language}', language, role, grade, subset, cap=group_capacity)
                    new_unit(g, language, hours)
            g = new_group(f'{grade}_TRACK_{track:02d}_EPS', 'EPS','EPS',grade,pupils,cap=group_capacity)
            new_unit(g,'EPS',2)
            if grade in ('1re','Tle'):
                g = new_group(f'{grade}_TRACK_{track:02d}_ENSCI','ENSCI','science',grade,pupils,cap=group_capacity)
                new_unit(g,'ENSCI',2)

    by_speciality = defaultdict(list)
    for s, selected in student_specs.items():
        for subject in selected:
            by_speciality[(profiles[s]['grade'],subject)].append(s)
    for (grade, subj), population in sorted(by_speciality.items()):
        family = f'{grade}_{subj}'
        number = max(2 if grade == 'Tle' else 1, math.ceil(len(population) / section_capacity))
        hours = 4 if grade == '1re' else 6
        for j in range(number):
            sec = f'{family}_{j+1:02d}'
            new_group(sec, subj, 'speciality', grade, [], cap=section_capacity)
            new_unit(sec, subj, hours, family=family, sec=sec, section_cap=section_capacity)
        for s in population:
            requests.append({'kind':'request','student_id':s,'family':family,'required':'true','weight':'1'})

    by_optional = defaultdict(list)
    for s, chosen in optional.items():
        for subject in chosen:
            by_optional[(profiles[s]['grade'],subject)].append(s)
    for (grade,subj),population in sorted(by_optional.items()):
        if len(population) < 4:
            continue
        family = f'{grade}_OPT_{subj}'
        cap = min(26, section_capacity)
        for j in range(math.ceil(len(population)/cap)):
            sec = f'{family}_{j+1:02d}'
            new_group(sec, subj,'option',grade,[],cap=cap)
            new_unit(sec,subj,3 if subj=='LATIN' else 2,family=family,sec=sec,section_cap=cap)
        for s in population:
            requests.append({'kind':'request','student_id':s,'family':family,'required':'false','weight':str(rng.choice([1,1,2,2,3]))})

    # Group all permanent pupils explicitly, never infer language/EPS/practical attendance from home class.
    membership_rows = [{'kind':'membership','student_id':s,'group_id':g}
                       for g, pupils in groups_members_sorted(members) for s in pupils]

    subject_hours = Counter()
    max_parallel = Counter()
    for subj,ids,fam in units:
        subject_hours[subj] += len(ids)
        if fam:
            max_parallel[subj] = max(max_parallel[subj], sum(len(xids) > 0 for xsubj,xids,xfam in units if xsubj==subj and xfam==fam))
    pools = {subj: [f'{subj}_P{i+1:02d}' for i in range(max(1,math.ceil(hours/teacher_load),max_parallel[subj]))]
             for subj,hours in subject_hours.items()}
    load = Counter()
    used_in_family = defaultdict(set)
    by_id = {r['id']:r for r in courses}
    for subj,ids,fam in sorted(units,key=lambda u: (0 if u[2] else 1,-len(u[1]))):
        pool = pools[subj]
        candidates = [p for p in pool if not fam or p not in used_in_family[fam]]
        if not candidates:
            candidates=[f'{subj}_P{len(pool)+1:02d}']
            pool.extend(candidates)
        p = min(candidates,key=lambda q:(load[q],q))
        load[p] += len(ids)
        if fam:
            used_in_family[fam].add(p)
        for cid in ids:
            by_id[cid]['professor'] = p

    professor_rows,pref_rows=[],[]
    for p in sorted(load):
        target=min(40,max(load[p]+8,int(round(40*professor_availability))))
        available=set(rng.sample(range(40),target))
        professor_rows.append({'kind':'professor','id':p,'available_slots':';'.join(map(str,sorted(available))),
                               'room_change_weight':str(rng.choice((3,5,8)) if rng.random()<room_weight_fraction else 1)})
        preferred=rng.randrange(5)
        avoid=rng.choice([d for d in range(5) if d!=preferred])
        pref_rows.extend([{'kind':'preference','professor':p,'slots':';'.join(str(preferred*8+t) for t in range(8)),'weight':'1.5'},
                          {'kind':'preference','professor':p,'slots':';'.join(str(avoid*8+t) for t in range(4)),'weight':'-2.5'}])

    rooms=[]
    general_n = cohorts+max(4,cohorts//2)
    lab_n=max(3, math.ceil(cohorts/3))
    pc_n=max(2,math.ceil(cohorts/4))
    gym_n=max(2,math.ceil(cohorts/4))
    for i in range(general_n):
        rooms.append({'kind':'room','id':f'R{i+1:03d}','available_slots':'*','capacity':str(max(class_max,group_capacity)+8),'room_type':'general','allowed_subjects':'*'})
    for i in range(lab_n):
        rooms.append({'kind':'room','id':f'LAB{i+1}','available_slots':'*','capacity':str(max(class_max,group_capacity)+4),'room_type':'lab',
                      'equipment':'lab','allowed_subjects':'PHYS;SVT;ENSCI;PHYS_SPE;SVT_SPE'})
    for i in range(pc_n):
        rooms.append({'kind':'room','id':f'PC{i+1}','available_slots':'*','capacity':str(max(class_max,group_capacity)+4),'room_type':'computer',
                      'equipment':'computers','allowed_subjects':'NSI;SNT'})
    for i in range(gym_n):
        rooms.append({'kind':'room','id':f'GYM{i+1}','available_slots':'*','capacity':'70','room_type':'gym','equipment':'gym','allowed_subjects':'EPS'})

    students_rows = [{'kind':'student','id':s,**profiles[s]} for s in students]
    relations=[]
    for subj,ids,fam in units:
        if len(ids)>=3 and rng.random()<chronology_rate:
            relations.append({'kind':'relation','relation':'BETWEEN','course':ids[1],'before':ids[0],'after':ids[2]})
    rows = courses+list(groups.values())+membership_rows+students_rows+requests+professor_rows+pref_rows+rooms+relations
    with open(path,'w',newline='',encoding='utf-8') as f:
        writer=csv.DictWriter(f,fieldnames=COLUMNS,extrasaction='raise');writer.writeheader();writer.writerows(rows)
    all_first=[tuple(sorted(student_specs[s])) for s in students if profiles[s]['grade']=='1re']
    mixed=sum(len({profiles[s]['home_class'] for s in pupils})>1 for group,pupils in members.items() if groups[group]['group_type'] not in {'common','practical','speciality','option'})
    return {'mode':'french','cohorts':cohorts,'students':len(students),'sessions':len(courses),'professors':len(load),'rooms':len(rooms),
            'fixed_teaching_groups':sum(bool(members[g]) for g in groups),'mixed_home_groups':mixed,
            'distinct_premiere_triples':len(set(all_first)), 'offered_specialities':len(offered), 'required_requests':sum(r['required']=='true' for r in requests),
            'optional_requests':sum(r['required']=='false' for r in requests)}


def groups_members_sorted(members):
    return ((group, sorted(pupils)) for group,pupils in sorted(members.items()) if pupils)


def main():
    p=argparse.ArgumentParser(description='Synthetic French lycée generator with individual pathways and explicit groups')
    p.add_argument('output')
    p.add_argument('--cohorts',type=int,default=9)
    p.add_argument('--seed',type=int,default=2026)
    p.add_argument('--class-min',type=int,default=28)
    p.add_argument('--class-max',type=int,default=34)
    p.add_argument('--section-capacity',type=int,default=30)
    p.add_argument('--group-capacity',type=int,default=30)
    p.add_argument('--teacher-load',type=int,default=18)
    p.add_argument('--professor-availability',type=float,default=0.9)
    p.add_argument('--option-probability',type=float,default=0.16)
    p.add_argument('--chronology-rate',type=float,default=0)
    p.add_argument('--room-weight-fraction',type=float,default=0.25)
    p.add_argument('--mode',choices=('french','legacy'),default='french')
    p.add_argument('--specialities',default='MATHS_SPE;PHYS_SPE;SES_SPE;HGGSP;SVT_SPE')
    p.add_argument('--language-diversity',type=float,default=0.05)
    a=p.parse_args()
    info=build(a.output,a.cohorts,a.seed,a.class_min,a.class_max,a.section_capacity,a.teacher_load,a.professor_availability,a.option_probability,a.chronology_rate,a.room_weight_fraction,a.group_capacity,a.mode,tuple(x.strip() for x in a.specialities.split(';') if x.strip()),a.language_diversity)
    print(' '.join(f'{k}={v}' for k,v in info.items()))

if __name__=='__main__':
    main()
