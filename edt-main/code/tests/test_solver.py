from api import *
from Solver.new_solver import *

room_l = [Room(f"Room {i}") for i in range(1, 10)]
room_l[7] = Room("Room 8", 19)

subj_l = [
    Subject("Mat"),
    Subject("Inf"),
    Subject("Fra"),
    Subject("Ang"),
    Subject("EPS"),
    Subject("LV2"),
    Subject("Ma2"),
    Subject("In2"),
]
base_course = {i:1 for i in subj_l}
# on défini notre établissement
clas_l = [
    StudentClass("2nde 1", course=base_course.copy(), size=18),
    StudentClass("2nde 2", course=base_course.copy(), size=18),
    StudentClass("2nde 3", course=base_course.copy(), size=18),
    StudentClass("1ère 1", course=base_course.copy(), size=20),
    StudentClass("1ère 2", course=base_course.copy(), size=18),
    StudentClass("1ère 3", course=base_course.copy(), size=18),
    StudentClass("Term 1", course=base_course.copy(), size=18),
    StudentClass("Term 2", course=base_course.copy(), size=18),
    StudentClass("Term 3", course=base_course.copy(), size=18),
    StudentClass("Espagnol Term", course={i:0 for i in subj_l}, size=20),
    StudentClass("Italien Term", course={i:0 for i in subj_l}, size=19),
    StudentClass("Allemand Term", course={i:0 for i in subj_l}, size=15),
]

clas_l[8].course[subj_l[-1]]=2
clas_l[6].course[subj_l[5]]=0
clas_l[7].course[subj_l[5]]=0
clas_l[8].course[subj_l[5]]=0
clas_l[9].course[subj_l[5]]=2
clas_l[10].course[subj_l[5]]=2
clas_l[11].course[subj_l[5]]=2

clas_l[6].conflict.append(clas_l[9])
clas_l[6].conflict.append(clas_l[10])

clas_l[7].conflict.append(clas_l[9])
clas_l[7].conflict.append(clas_l[10])

clas_l[8].conflict.append(clas_l[9])
clas_l[8].conflict.append(clas_l[11])


teac_l = [
    Teacher("Pr.M", [subj_l[0], subj_l[1], subj_l[6]]),
    Teacher("Pr.I", [subj_l[0], subj_l[1], subj_l[7]]),
    Teacher("Pr.F", [subj_l[2]]),
    Teacher("Pr.A", [subj_l[3]]),
    Teacher("Pr.E", [subj_l[4]]),
    Teacher("Pr.L", [subj_l[5]]),
]

for t in teac_l: print(t)

school = School(room_l,teac_l,subj_l,clas_l,[])

solve(school, True)

