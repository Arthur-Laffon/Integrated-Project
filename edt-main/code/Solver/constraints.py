from api import *
from pychoco import Model

# Concatène toutes les listes imbriquées en une seule liste
def concat(l):
    acc = []
    if type(l) != list:
        return [l]
    for i in l:
        i = concat(i)
        for j in i:
            acc.append(j)
    return acc

def nonzero(n): return 0 if n==0 else 1

# tt : liste des variables (importantes) du modèle
def get_hard_constraints(school:School, model:Model, tt):
    
    number_days = 5
    slots_per_day = 4
    
    nb_classes = len(school.classes)
    nb_rooms = len(school.rooms)
    nb_subjects = len(school.subjects)
    nb_teachers = len(school.teachers)
    nb_timeSlots = number_days*slots_per_day
    
    
    # une salle ne peut pas être utilisée par 2 classes en même temps
    no_double_rooms = [model.all_different_except_0(
        [
            tt[i][j][k][l] for l in range(nb_teachers)
            for k in range(nb_subjects) for i in range(nb_classes)
        ]
    ) for j in range(nb_rooms)]
    
    # un prof ne peut pas enseigner à 2 classes en même temps
    no_double_teachers = [model.all_different_except_0(
        [
            tt[i][j][k][l] for j in range(nb_rooms)
            for k in range(nb_subjects) for i in range(nb_classes)
        ]
    ) for l in range(nb_teachers)]
    
    # une classe ne peut pas être utilisée 2 fois en même temps
    no_double_classes = [model.all_different_except_0(
        [
            tt[i][j][k][l] for j in range(nb_rooms)
            for k in range(nb_subjects) for l in range(nb_teachers)
        ]
    ) for i in range(nb_classes)]
    
    # 2 groupes ayant une instersection non vide
    # ne peuvent pas avoir cours en même temps
    no_group_conflicts = [model.all_different_except_0(
            [tt[i1][j][k][l] for j in range(nb_rooms) 
             for l in range(nb_teachers) for k in range(nb_subjects)]+
            [tt[i2][j][k][l] for j in range(nb_rooms) 
             for l in range(nb_teachers) for k in range(nb_subjects)]
    ) for i1 in range(nb_classes) for i2 in [school.classes.index(g) for g in school.classes[i1].conflict]]
    
    # un prof est limité à ses matières
    teachers_limited_to_skills = [model.all_equal(
        [tt[i][j][k][l] for j in range(nb_rooms) 
         for i in range(nb_classes)]+[model.intvar(0,None)]
    ) for l in range(nb_teachers) for k in range(nb_subjects)
        if school.subjects[k] not in school.teachers[l].skills]
    
    # une salle est limitée à ses matières
    rooms_limited_to_skills = [model.all_equal(
        [tt[i][j][k][l] for i in range(nb_classes) 
         for l in range(nb_teachers)]+[model.intvar(0, None)]
    ) for j in range(nb_rooms) for k in range(nb_subjects)
        if school.subjects[k] not in school.rooms[j].skills 
        and school.rooms[j].skills != []]
    
    # chaque classe a un certain nombre de cours de chaque matière
    courses_per_classes = [model.count(0, [tt[i][j][k][l] for j in range(nb_rooms)
        for l in range(nb_teachers)], model.intvar(nb_rooms*nb_teachers - 
                                school.classes[i].course[school.subjects[k]], None)) 
        for i in range(nb_classes) for k in range(nb_subjects)]
    
    
    return (no_double_rooms+no_double_classes+no_double_teachers+
        no_group_conflicts+teachers_limited_to_skills+
        rooms_limited_to_skills+courses_per_classes)
    
def get_soft_constraints(school:School, nb_layers:int, model:Model, tt):
    
    number_days = 5
    slots_per_day = 4
    
    nb_classes = len(school.classes)
    nb_rooms = len(school.rooms)
    nb_subjects = len(school.subjects)
    nb_teachers = len(school.teachers)
    nb_timeSlots = number_days*slots_per_day
    
    # Chaque matière doit être réalisé dans un des crénaux recommandés
    # prio : 1
    subj_prefered_time = 1, [model.element(tt[i][j][k][l],
        list(map(lambda ts: ts.to_index(), school.subjects[k].prefered_time))+[0],
        model.intvar(0, nb_timeSlots))
        for i in range(nb_classes) for j in range(nb_rooms)
        for k in range(nb_subjects) for l in range(nb_teachers)]
    
    # Chaque prof veut avoir ses cours dans ses crénaux préférés
    # prio : 2
    teacher_prefered_time = 2,[model.element(
        tt[i][j][k][l], list(map(lambda t: t[0].to_index(), 
                             filter(lambda t: t[1]==0, school.teachers[l].slots)))+[0],
        model.intvar(0, nb_timeSlots)) for i in range(nb_classes) 
            for j in range(nb_rooms) for k in range(nb_subjects) 
            for l in range(nb_teachers)]
    
    # Aucun prof ne veut de cours dans ses crénaux détestés
    # prio : 0
    teacher_least_prefered_time = 0,[model.element(
        tt[i][j][k][l], list(map(lambda t: t[0].to_index(), 
                             filter(lambda t: t[1]<2, school.teachers[l].slots)))+[0],
        model.intvar(0, nb_timeSlots)) for i in range(nb_classes) 
            for j in range(nb_rooms) for k in range(nb_subjects) 
            for l in range(nb_teachers)]
    
    
    res = [teacher_least_prefered_time[1], subj_prefered_time[1], teacher_prefered_time[1]]
    
    return res


