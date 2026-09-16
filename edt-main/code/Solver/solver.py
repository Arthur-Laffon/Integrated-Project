from api import *
from pychoco import Model
from itertools import product
def solve(school:School, debug = False):

    model = Model("EDT")
    
    clas_l = school.classes
    room_l = school.rooms
    subj_l = school.subjects
    teac_l = school.teachers
    times_l = [TimeSlot(i, j, p) for i in range(5) for j,p in enumerate([1, 2, 2, 0])]
    


    # nombre de classe
    nb_clas = len(clas_l)
    # nombre de salle
    nb_room = len(room_l)
    # nombre de matière
    nb_subj = len(subj_l)
    # nombre de prof
    nb_teac = len(teac_l)
    # nombre de crénaux horaire
    nb_time = len(times_l)



# on définit une variable par élément de la timetable
# tt[i][j][k][l][m] = true ssi 
# la classe i 
# a cours dans la salle j
# pour faire la matière k
# avec le prof l 
# au créneau m
    tt = []
    for i in range(nb_clas):
        tt.append([])
        for j in range(nb_room):
            tt[-1].append([])
            for k in range(nb_subj):
                tt[-1][-1].append([])
                for l in range(nb_teac):
                    tt[-1][-1][-1].append([])
                    for m in range(nb_time):
                        tt[-1][-1][-1][-1].append(model.boolvar())


    # on définit les contraintes
    # par défault on ne peut pas dédoubler les salles, les profs ou les classes
    for j, m in product(range(nb_room), range(nb_time)):  # pour les salles
        model.all_different_except_0([tt[i][j][k][l][m] for l, k, i in product(range(nb_teac), range(nb_subj), range(nb_clas))]).post()
        for i in range(nb_clas):
            if room_l[j].size < clas_l[i].size:
                model.all_equal([model.intvar(0)]+[tt[i][j][k][l][m] for l,k,m in product(range(nb_teac), range(nb_subj), range(nb_time))]).post()

    for l ,m in product(range(nb_teac), range(nb_time)):  # pour les profs
        model.all_different_except_0([tt[i][j][k][l][m] for j,k,i in product(range(nb_room), range(nb_subj), range(nb_clas))]).post()


    for i,m in product(range(nb_clas), range(nb_time)):  # pour les classes
        model.all_different_except_0([tt[i][j][k][l][m] for l, k, j in product(range(nb_teac), range(nb_subj), range(nb_room))] ).post()

    # on gère les conflits entre les sous groupes d'une classe
    for i1 in range(nb_clas):
        for i2,m in product([clas_l.index(g) for g in clas_l[i1].conflict], range(nb_time)):
            model.all_different_except_0([tt[i][j][k][l][m] for i,l,k,j in product((i1,i2),range(nb_teac),range(nb_subj),range(nb_room))]).post()


    # un prof ne peut pas enseigner en dehors de son champs de compétence
    for l,k in product(range(nb_teac), range(nb_subj)):
        if subj_l[k] not in teac_l[l].skills:
            model.all_equal([model.intvar(0)]+[tt[i][j][k][l][m] for j,m,i in product(range(nb_room), range(nb_time), range(nb_clas))]).post()

    # une classe a un certain nombre de cours de chaque matière par semaine
    for i, k in product(range(nb_clas), range(nb_subj)):
        vars = [tt[i][j][k][l][m] for j,m,l in product(range(nb_room), range(nb_time), range(nb_teac))]
        values = [0, 1]
        occs = [model.intvar((nb_room * nb_teac * nb_time) - clas_l[i].course[subj_l[k]]), model.intvar(clas_l[i].course[subj_l[k]])]
        model.global_cardinality(vars, values, occs, True).post()

    # Fonction objectif
    Obj = model.intvar(0,99999999)
    # Liste des variables contraintes qui contribuent à la fonction obj
    soft_constr = []
    # pour chacune de ces contraintes, un coeff associé dans X
    # -> Obj = <soft_constr . X>
    X = []

    # TODO : ajouter 300000 contraintes softs 
    # Obj va être la somme pondérée de ces contraintes
    def add_to_constr(new_constr, x, soft_c, soft_x):
        """Ajoute à soft_c les contraintes de new_constr avec
        pondération x"""
        new_constr_l = (new_constr)
        new_constr_x = [x]*len(new_constr_l)
        soft_c += new_constr_l
        soft_x += new_constr_x
        return
    
    # 1.Prendre les timeslot avec la meilleure priorité d'abord
    
    coeff_slot = [model.intvar(4-times_l[m].priority) for i in range(nb_clas)
                for j in range(nb_room) for k in range(nb_subj) for l in range(nb_teac)
            for m in range(nb_time) if tt[i][j][k][l][m]]
    
    add_to_constr(coeff_slot, 4, soft_constr, X)

    # 2.Pour chaque matière, prendre ses timeslot privilégiés
    # et c'est pas dans le même format que pour les profs :<<<<<<<
    prefered_slots_subj = [model.intvar(len([1 for i in range(nb_clas)
                                         for j in range(nb_room)
                                         for l in range(nb_teac)
                                         for m in range(nb_time)
                                         if tt[i][j][k][l][m] and
                                         times_l[m] in subj_l[l].prefered_time])) for k in range(nb_subj)]
    add_to_constr(prefered_slots_subj, 1, soft_constr, X)
    
    # +1 point par fois où on respecte la contrainte "rien après" 
    # (fin des cours, ou pause midi)
    nothing_after_subj = [model.intvar(len([1 for i in range(nb_clas)
                                        for j in range(nb_room)
                                        for l in range(nb_teac)
                                        for m in range(nb_time)
                                        if tt[i][j][k][l][m] and
                                        (times_l[m].start in [1, 3] or 
                                         not tt[i][j][k][l][m+1])]))]
    add_to_constr(nothing_after_subj, 1, soft_constr, X)
    # pause midi ou fin de journée ou
    # 3.Pour chaque prof, ses temps préférés (on ajoute pour les prios 0, sachant que être de prio
    # 0 ou 1 est une contrainte forte)
    prefered_slots_teac = [model.intvar(len([1 for i in range(nb_clas)
                                         for j in range(nb_room)
                                         for k in range(nb_subj)
                                         for m in range(nb_time)
                                         if tt[i][j][k][l][m] and
                                         (times_l[m], 0) in teac_l[l].slots])) for l in range(nb_teac)]
    add_to_constr(prefered_slots_teac, 2, soft_constr, X)
    # 4. Pour chaque classe, ne pas lui assigner 2 profs qui s'évitent
    col_to_avoid = [model.intvar(len([1 for i in range(nb_clas)
                                    for l1 in range(nb_teac)
                                    for l2 in range(nb_teac)
                                    if teac_l[l1] in teac_l[l2].avoid_collegues
                                    and (any(tt[i][j][k][l1][m] for j in range(nb_room) for k in range(nb_subj) for m in range(nb_time)))
                                    and (any(tt[i][j][k][l2][m] for j in range(nb_room) for k in range(nb_subj) for m in range(nb_time)))]))]
    add_to_constr(col_to_avoid, 1, soft_constr, X)

    model.scalar(soft_constr, X, "=", Obj).post()


    solver = model.get_solver()
    solver.show_statistics()
    solv = solver.find_optimal_solution(Obj,True,time_limit = "5m")

    if debug :
        print(
            "------------------------------------------------------------------------------------------------------------------------------------------------------------------"
        )
        print(
            "------------------------------------------------------------------------------------------------------------------------------------------------------------------"
        )
    attrib_l = []
    if solv != None:
        for i in range(nb_clas):
            if debug: print(f"Classe : {clas_l[i].name}")
            for u in range(5):
                if debug: s = f"jour {u+1} : "
                for v in range(int(nb_time / 5)):
                    if debug: s += f"crénau {v+1} :"
                    for l in range(nb_teac):
                        for j in range(nb_room):
                            for k in range(nb_subj):
                                if solv.get_int_val(tt[i][j][k][l][4 * u + v]) == 1:
                                    attrib_l.append(
                                        TimetableEntry(
                                            room_l[j],
                                            clas_l[i],
                                            teac_l[l],
                                            subj_l[k],
                                            TimeSlot(u, v)
                                        )
                                    )
                                    if debug: s += f" {subj_l[k].name} with {teac_l[l].name} in {room_l[j].name}"
                    if debug and s[-1] == ":":
                        s += "\t\t\t"
                    if debug: s += "\t"
                if debug: print(s)
            if debug: print(
                "------------------------------------------------------------------------------------------------------------------------------------------------------------------"
            )

        return Timetable(attrib_l)
    else:
        print("No solution found")
    if debug: 
        print(
        "------------------------------------------------------------------------------------------------------------------------------------------------------------------"
        )
        print(
            "------------------------------------------------------------------------------------------------------------------------------------------------------------------"
        )
