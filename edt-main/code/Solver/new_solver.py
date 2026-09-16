from api import *
from constraints import *
from pychoco import Model

def solve(school:School, debug = False):
    
    # nombre de niveaux de priorité pour les contraintes soft 
    # pour les relaxer au fur et à mesure (pourra être modifié)
    # les n° de priorité vont donc de 0 (plus important) 
    # à nb_layers-1 (moins important) 
    nb_layers = 3
    nb_models = nb_layers+1

    # Tous ces modèles ont la même structure de variables
    models = [Model(f"EDT_{i}") for i in range(nb_models)]
    
    classes_l = school.classes
    rooms_l = school.rooms
    subjects_l = school.subjects
    teachers_l = school.teachers
    number_days = 5
    
    slots_per_day = 4
    slot_priority = [1,0,0,2]
    times_l = [TimeSlot(i, j, p) for i in range(number_days) for j,p in enumerate(slot_priority)]
    
    nb_classes = len(classes_l)
    nb_rooms = len(rooms_l)
    nb_subjects = len(subjects_l)
    nb_teachers = len(teachers_l)
    nb_timeSlots = len(times_l)
    
    vars = [[]]*nb_models
    for i in range(nb_models):
        vars[i] = [[[[models[i].intvar(0, nb_timeSlots, f"time_{c}_{r}_{s}_{t}") 
                for t in range(nb_teachers)] for s in range(nb_subjects)]
            for r in range(nb_rooms)] for c in range(nb_classes)]
    
    # nouveau modèle pour le solveur:
    # pour le solveur k, si tt = vars[k]
    # i∈[|1, nb_timeSlots|]
    # tt[c][r][s][t] = i <=>
    # la classe <c> a cours de <s> dans la salle <r> avec le prof <t> à l'horaire <i>. 
    # tt[c][r][s][t] = 0 <=> pas cours à ce moment, 
    # à cet endroit et avec ce prof pour cette classe.

    # Pour ça, on crée plusieurs modèles avec 
    # chacun où moins de contraintes soft sont imposées 
    
    # Contraintes inviolables
    hard_constraints = [get_hard_constraints(school, models[i], vars[i]) for i in range(nb_models)]
    
    # Contraintes moins importantes:
    # soft_constraints[i][j] : contraines à priorité j pour le modèle i
    # sachant que le modèle i considèrera comme hard les
    # contraintes soft de priorité <= nb_layers - i - 1
    soft_constraints = [get_soft_constraints(school, nb_layers, models[i], vars[i]) for i in range(nb_models)]
    
    # Contraintes qui seront encodées dans la fonction d'optimisation
    # Tout comme les hard_constraints, nb_layers copies des mêmes choses pour chaque solveur
    opt_constraints = [[]]*nb_models
        
    # Pour chaque modèle et chaque sc que le modèle considère comme sc,
    # une variable booléene indiquant si la sc est satisfaite
    satisfied_sc = [[]]*nb_models
    
    for i in range(nb_models):
        for hc in hard_constraints[i]: hc.post()
        for j in range(nb_layers-i):
            for sc in soft_constraints[i][j]: sc.post()
        satisfied_sc[i] = [sc.reify() for j in range(i)
                           for sc in soft_constraints[i][nb_layers-j-1]]
    
    Objs = [models[i].intvar(0, 9999999) for i in range(nb_models)]
    coeffs = [[1]*len(opt_constraints[i]) for i in range(nb_models)]
    # on pourra modifier les coeffs
    for i in range(nb_models):
        models[i].scalar(opt_constraints[i], coeffs[i], "=", Objs[i])
    
    constraint_level=0
    cont = True # Pour sortir de la boucle
    while cont and constraint_level<=nb_layers:
    
        solver = models[constraint_level].get_solver()
        solver.show_statistics()
        solv = solver.find_optimal_solution(Objs[constraint_level], True, time_limit = "5m")

        if debug :
            print(
                "------------------------------------------------------------------------------------------------------------------------------------------------------------------"
            )
            print(
                "------------------------------------------------------------------------------------------------------------------------------------------------------------------"
            )
        attrib_l = []
        if solv != None:
            cont = False
            if debug: print(f"Nombre de contraintes non satisfaites : {len([b for b in satisfied_sc[constraint_level] if b])}")
            for i in range(nb_classes):
                if debug: print(f"Classe : {classes_l[i].name}")
                for u in range(5):
                    if debug: s = f"jour {u+1} : "
                    for v in range(int(nb_timeSlots / 5)):
                        if debug: s += f"crénau {v+1} :"
                        for l in range(nb_teachers):
                            for j in range(nb_rooms):
                                for k in range(nb_subjects):
                                    if solv.get_int_val(vars[constraint_level][i][j][k][l]) == 4 * u + v-1:
                                        attrib_l.append(
                                            TimetableEntry(
                                                rooms_l[j],
                                                classes_l[i],
                                                teachers_l[l],
                                                subjects_l[k],
                                                TimeSlot(u, v)
                                            )
                                        )
                                        if debug: s += f" {subjects_l[k].name} with {teachers_l[l].name} in {rooms_l[j].name}"
                        if debug and s[-1] == ":":
                            s += "\t\t\t"
                        if debug: s += "\t"
                    if debug: print(s)
                if debug: print(
                    "------------------------------------------------------------------------------------------------------------------------------------------------------------------"
                )

            return Timetable(attrib_l)
        else:
            print(f"No solution found at level {constraint_level}")
            constraint_level += 1
        if debug:
            print(
                "------------------------------------------------------------------------------------------------------------------------------------------------------------------"
            )
            print(
                "------------------------------------------------------------------------------------------------------------------------------------------------------------------"
            )
