# We assume that no 2 objects have the same name

ndays = 5
nhours = 4


class TimeSlot:
	"""For now, day is in (0, 4) and start is in [0, 3]
	priority goes from a scale from 0 to 2, from most (0)
	to least likable
	-> weight in an objective function (to maximize):
	2 - priority for each time this timeslot if used"""

	day: int
	start: int
	priority: int

	def __init__(self, day:int, start:int, priority:int=0):
		self.day = day
		self.start = start
		self.priority = priority

	def to_index(self):
		return self.day * nhours + self.start

	def __repr__(self):
		return f"day : {self.day}, start : {self.start}"


class Subject:
	name: str
	# both are soft
	prefered_time: list[TimeSlot]
	# ex for sports class, true
	nothing_after: bool

	# See Rooms
	special: bool
	allowed_rooms: list["Room"]

	def __init__(self, name, prefered_time=[], nothing_after=False):
		self.name = name
		self.prefered_time = prefered_time.copy()
		self.nothing_after = nothing_after

	def __eq__(self, other):
		if isinstance(other, self.__class__):
			return self.name == other.name
		else:
			return False

	def __hash__(self) -> int:
		return hash(self.name)

	def __repr__(self):
		return self.name


class StudentClass:
	"""name of the class
	size : nb of students
	course: for each subject, the number of hours to be done"""

	class_id: int
	name: str
	course: dict[Subject, int]
	size: int
	students: list["Student"]
	course: dict[Subject, int]
	conflict: list[
        "StudentClass"
    ]  # Les sous groupes sont des classes à part entière partageant des élèves
	# Pour chaque matière, son nb d'heures de cours

	def __init__(self, name, class_id = 0, course=dict(), size=20, students=[],conflict=[]):
		self.conflict = conflict.copy()
		self.class_id = class_id
		self.name = name
		self.size = size
		self.course = course
		self.students = students

	def __eq__(self, other):
		if isinstance(other, self.__class__):
			return self.name == other.name
		else:
			return False

	def __repr__(self) -> str:
		s = (
			self.name
			+ "\n"
			+ "Conflict : "
			+ ", ".join([i.name for i in self.conflict])
		)
		return s


class Room:
	name: str
	size: int

	# True if the room is only used by subjects that need special rooms
	# eg Physics practicals or music courses
	special: bool
	allowed_subjects: list[Subject]

	def __init__(self, name, size=20, skills=[]):
		self.name = name
		self.size = size
		self.skills = skills.copy()
		self.special = False
		self.allowed_subjects = []

	def __eq__(self, other):
		if isinstance(other, self.__class__):
			return self.name == other.name
		else:
			return False

	def __repr__(self):
		return f"name : {self.name}, size : {self.size}"


class Teacher:
	name: str
	skills: list[Subject]
	# list time priority (from best (0) to worst (2))
	slots: list[tuple[TimeSlot, int]]
	# teachers with whom he does not want to share a class with
	avoid_collegues: list[str]

	def __init__(
        self,
        name,
        skills=[],
        slots=[(TimeSlot(i, j), 0) for i in range(ndays) for j in range(nhours)],
        avoid=[],
    ):
		self.name = name
		self.skills = skills.copy()
		self.slots = slots
		self.avoid_collegues = avoid.copy()

	def __eq__(self, other):
		if isinstance(other, self.__class__):
			return self.name == other.name
		else:
			return False

	def __repr__(self):
		return f"name : {self.name}, skills : {self.skills}, slots : {self.slots}"


class Student:
    student_id: int
    name: str
    courses: list[StudentClass]

    def __init__(
        self,
        name,
        last_name,
        courses=[],
    ):
        self.name = name
        self.last_name = last_name
        self.courses = courses.copy()

    def __eq__(self, other):
        if isinstance(other, self.__class__):
            return (self.name == other.name) and (self.last_name == other.last_name)
        else:
            return False

    def __repr__(self):
        s = f"name : {self.name} {self.last_name} \n courses followed : "
        for topic in self.courses:
            s += f" {topic},"
        return s


class School:
	rooms: list[Room]
	teachers: list[Teacher]
	subjects: list[Subject]
	class_number: int
	classes: list[StudentClass]
	student_number: int
	students: list[Student]
	rooms: list[Room]
	teachers: list[Teacher]
	subjects: list[Subject]
	classes: list[StudentClass]

	def __init__(
        self,
        rooms=[],
        teachers=[],
        subjects=[],
        classes=[],
        students=[],
    ):
		self.rooms = rooms
		self.teachers = teachers
		self.subjects = subjects
		self.classes = classes
		self.class_number = len(classes)
		self.students = students
		self.student_number = len(students)

	def get(self, name):
		if name == "Professeurs":
			return self.teachers
		elif name == "Classes":
			return self.classes
		elif name == "Matières":
			return self.subjects
		elif name == "Salles":
			return self.rooms
		elif name == "Élèves":
			return self.students


class TimetableEntry:
    room: Room
    studentClass: StudentClass
    teacher: Teacher
    subject: Subject
    timeSlot: TimeSlot

    def __init__(self, room, studentClass, teacher, subject, timeSlot):
        self.room = room
        self.studentClass = studentClass
        self.teacher = teacher
        self.subject = subject
        self.timeSlot = timeSlot

    def __repr__(self):
        return f" {self.timeSlot} - {self.subject} - {self.teacher} - {self.studentClass} - {self.room} \n"


class Timetable:
    timetable: list[TimetableEntry]

    def __init__(self, timetable):
        self.timetable = timetable

    def get_tt_teacher(self, teacher: Teacher) -> "Timetable":
        return Timetable(
            [entry for entry in self.timetable if entry.teacher == teacher]
        )

    def get_tt_student_class(self, studentClass: StudentClass) -> "Timetable":
        return Timetable(
            [entry for entry in self.timetable if entry.studentClass == studentClass]
        )

    def get_tt_student(self, student: Student) -> "Timetable":
        return Timetable(
            [entry for entry in self.timetable if entry.studentClass in student.courses]
        )

    def get_tt_room(self, room: Room) -> "Timetable":
        return Timetable([entry for entry in self.timetable if entry.room == room])

    def show(self):
        """Affiche cet EDT à l'endroit assigné"""
        pass

    def __repr__(self):
        s = ""
        for t in self.timetable:
            s += f" {t} \n"
        return s
