from api import (
    Timetable,
    TimetableEntry,
    Room,
    StudentClass,
    Teacher,
    Subject,
    TimeSlot,
)

# Matières
math = Subject("Maths")
history = Subject("Histoire")
science = Subject("Sciences")

# Classes
class_A = StudentClass("Classe A", {math: 3, history: 2, science: 2})
class_B = StudentClass("Classe B", {math: 2, history: 3, science: 2})
class_C = StudentClass("Classe C", {math: 2, history: 2, science: 3})
classes = [class_A, class_B, class_C]

# Enseignants
teacher_1 = Teacher("Mme Dupont", [math])
teacher_2 = Teacher("M. Martin", [history])
teacher_3 = Teacher("Mme Leroy", [science])

# Salles
room_101 = Room("Salle 101", 30, [math])
room_102 = Room("Salle 102", 25, [history])
room_103 = Room("Salle 103", 20, [science])

# Créneaux horaires (5 jours × 4 créneaux)
slots = [TimeSlot(day, start) for day in range(5) for start in range(4)]

# Génération des entrées
entries = []
slot_index = [0 for _ in classes]


def add_course(student_class, subject, teacher, room, count):
    global slot_index
    class_index = classes.index(student_class)
    for _ in range(count):
        if slot_index[class_index] >= len(slots):
            break
        entries.append(
            TimetableEntry(
                room, student_class, teacher, subject, slots[slot_index[class_index]]
            )
        )
        slot_index[class_index] += 1


# Ajout des cours pour chaque classe
for day in range(5):
    # Classe A
    add_course(class_A, math, teacher_1, room_101, 1)
    add_course(class_A, history, teacher_2, room_102, 1)
    add_course(class_A, science, teacher_3, room_103, 1)

    # Classe B
    add_course(class_B, history, teacher_2, room_102, 1)
    add_course(class_B, science, teacher_3, room_103, 1)
    add_course(class_B, math, teacher_1, room_101, 1)

    # Classe C
    add_course(class_C, science, teacher_3, room_103, 1)
    add_course(class_C, math, teacher_1, room_101, 1)
    add_course(class_C, history, teacher_2, room_102, 1)

# Création de l'emploi du temps
sample_timetable = Timetable(entries)
