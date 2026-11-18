"""Convert legacy data"""
import argparse
import csv
from collections import defaultdict


def flatten(source, target):
    with open(source, newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        fields = list(reader.fieldnames or [])
        rows = list(reader)
    if 'fixed_courses' not in fields:
        fields.append('fixed_courses')
    by_group = defaultdict(set)
    for r in rows:
        if r.get('kind') == 'course' and r.get('group_id') and not r.get('section'):
            by_group[r['group_id']].add(r['id'])
    additions = defaultdict(set)
    for r in rows:
        if r.get('kind') == 'membership':
            additions[r['student_id']].update(by_group.get(r['group_id'], ()))
    flat = []
    for r in rows:
        if r.get('kind') in {'group','membership'}:
            continue
        r['group_id'] = ''
        if r.get('kind') == 'student':
            fixed = set(x for x in (r.get('fixed_courses') or '').split(';') if x)
            fixed.update(additions[r['id']])
            r['fixed_courses'] = ';'.join(sorted(fixed))
        flat.append(r)
    with open(target,'w',newline='',encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(flat)
    return {'students':sum(r.get('kind')=='student' for r in flat),'fixed_enrolments':sum(map(len,additions.values()))}


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('source');p.add_argument('target')
    a=p.parse_args()
    print(flatten(a.source,a.target))
