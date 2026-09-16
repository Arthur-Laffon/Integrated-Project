import ctypes

try:  # permets de se mettre en plein écran, sur tous les ordis
	ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
	pass

import tkinter as tk
import customtkinter as ctk
from CTkMessagebox import CTkMessagebox

import api
import save_load as save_load
import Solver.solver as solver
import Interface.consultation as consultation

# --- CONFIGURATION GLOBALE DE L'APPLICATION ---
ctk.set_appearance_mode("Light")
ctk.set_default_color_theme("blue")

class TabView(ctk.CTkFrame):
	"""
	Onglet de gestion d’un type d’entité (ex : Professeurs...).
	- Affiche la liste des éléments du type.
	- Permet d’ajouter/supprimer un élément.
	"""

	def __init__(self, master, tab_name, app):
		super().__init__(master)

		self.app = app
		self.tab_name = tab_name
		self.items = app.school.get(tab_name)
		self.selected_item = None

		self._create_layout()
		self._create_left_panel()
		self._create_right_panel()

		self.item_frames = {}
		self.item_btn = {}
		self.update_items_list()

	# --- CONFIGURATION GÉNÉRALE ---
	def _create_layout(self):
		self.left_frame = ctk.CTkFrame(self, width=int(self.winfo_screenwidth() * 0.20), fg_color="#85C1E9")
		self.left_frame.pack(side="left", fill="y")
		self.left_frame.pack_propagate(False)

		self.right_frame = ctk.CTkScrollableFrame(self)
		self.right_frame.pack(side="left", fill="both", expand=True)

	# --- CONFIGURATION DU PANNEL GAUCHE ---
	def _filter_left_list(self):
		query = self.left_search_entry.get().strip().lower()

		for name, frame in self.item_frames.items():
			show = (query in name.lower()) if query else True
			if show:
				if not frame.winfo_ismapped():
					frame.pack(fill="x", pady=2, padx=2)
			else:
				if frame.winfo_ismapped():
					frame.pack_forget()

	def _create_left_panel(self):
		label_text = (
			f"Créer un {self.tab_name[:-1].lower()}" if self.tab_name == "Professeurs"
			else f"Créer une {self.tab_name[:-1].lower()}"
		)
		ctk.CTkLabel(self.left_frame, text=label_text, font=ctk.CTkFont(size=18, weight="bold")).pack(
			pady=(self.app.sy(20), self.app.sy(5))
		)

		placeholder = (
			f"Nom du {self.tab_name[:-1].lower()}" if self.tab_name == "Professeurs"
			else f"Nom de la {self.tab_name[:-1].lower()}"
		)
		self.entry = ctk.CTkEntry(self.left_frame, placeholder_text=placeholder)
		self.entry.pack(pady=self.app.sy(5), padx=self.app.sx(10))

		self.add_btn = ctk.CTkButton(self.left_frame, text="Ajouter", command=self._on_add_item)
		self.add_btn.pack(pady=self.app.sy(5), padx=self.app.sx(10))

		self.error_label = ctk.CTkLabel(self.left_frame, text="", text_color="red")
		self.error_label.pack(padx=self.app.sx(10))

		self.entry.bind("<Return>", lambda e: self._on_add_item())
		self.entry.bind("<KP_Enter>", lambda e: self._on_add_item())

		scroll_label = (
			f"Tous les {self.tab_name.lower()}" if self.tab_name == "Professeurs"
			else f"Toutes les {self.tab_name.lower()}"
		)
		ctk.CTkLabel(self.left_frame, text=f"{scroll_label} :", font=ctk.CTkFont(size=self.app.s(16), weight="bold")).pack()

		search_row = ctk.CTkFrame(self.left_frame, fg_color="transparent")
		search_row.pack(fill="x", padx=self.app.sx(10), pady=(self.app.sy(8), self.app.sy(4)))

		ctk.CTkLabel(search_row, text="Rechercher :", font=ctk.CTkFont(size=self.app.s(14), weight="bold"))\
			.pack(side="left", padx=(0, self.app.sx(8)))

		self.left_search_entry = ctk.CTkEntry(search_row, placeholder_text="Tapez pour filtrer…")
		self.left_search_entry.pack(side="left", fill="x", expand=True)

		self.left_search_entry.bind("<KeyRelease>", lambda e: self._filter_left_list())

		self.scrollable_frame = ctk.CTkScrollableFrame(self.left_frame, width=int(self.winfo_screenwidth() * 0.25))
		self.scrollable_frame.pack(fill="both", expand=True, pady=self.app.sy(5), padx=self.app.sx(5))

	def _create_button(self, name):
		frame_item = ctk.CTkFrame(self.scrollable_frame)
		frame_item.pack(fill="x", pady=2, padx=2)

		btn = ctk.CTkButton(frame_item, text=name, corner_radius=0)
		btn.pack(side="left", fill="x", expand=True)
		btn.bind("<Button-1>", lambda e, n=name: self._show_item_details(n))
		if name == self.selected_item:
			btn.configure(fg_color=btn.cget("hover_color"))

		del_btn = ctk.CTkButton(
			frame_item,
			text="❌",
			width=self.app.sx(25),
			fg_color="red",
			corner_radius=0,
			command=lambda n=name: self._on_delete_item(n),
		)
		del_btn.pack(side="right")

		self.item_frames[name] = frame_item
		self.item_btn[name] = btn

	def _on_add_item(self):
		name = self.entry.get().strip()
		if not name:
			self._show_error("Veuillez entrer un nom qui n'est pas vide")
			return
		if name in [elt.name for elt in self.items]:
			self._show_error("Veuillez entrer un nom qui n'est pas encore utilisé")
			return

		if self.tab_name == "Professeurs":
			self.items.append(api.Teacher(name))
		if self.tab_name == "Classes":
			self.items.append(api.StudentClass(name))
		if self.tab_name == "Matières":
			self.items.append(api.Subject(name))
		if self.tab_name == "Salles":
			self.items.append(api.Room(name))
		self.entry.delete(0, "end")
		self._create_button(name)
		if hasattr(self, "left_search_entry"):
			self._filter_left_list()
		self.app.mark_dirty()

	def _on_delete_item(self, name):
		for elt in list(self.items):
			if elt.name == name:
				self.items.remove(elt)
				del self.item_frames[name]
				del self.item_btn[name]
				self.update_items_list()
				if hasattr(self, "left_search_entry"):
					self._filter_left_list()
				self.app.mark_dirty()
				break

		if name == self.selected_item:
			self.selected_item = None
			for widget in self.right_frame.winfo_children():
				widget.destroy()

	def update_items_list(self):
		for widget in self.scrollable_frame.winfo_children():
			widget.destroy()
		for item in self.items:
			self._create_button(item.name)

	def _show_item_details(self, name):
		if self.selected_item != name and self.selected_item is not None:
			self.item_btn[self.selected_item].configure(fg_color=['#3B8ED0', '#1F6AA5'])

		self.item_btn[name].configure(fg_color=self.item_btn[name].cget("hover_color"))
		self.selected_item = name

		for widget in self.right_frame.winfo_children():
			widget.destroy()

		ctk.CTkLabel(self.right_frame, text=f"Contraintes de {name}", font=ctk.CTkFont(size=20)).pack(
			pady=self.app.sy(20), padx=self.app.sx(20)
		)

		if self.tab_name == "Professeurs":
			self._teacher_panel(name)
		elif self.tab_name == "Classes":
			self._studentclass_panel(name)
		elif self.tab_name == "Salles":
			self._room_panel(name)

	def _show_error(self, message, duration=3000):
		self.error_label.configure(text=message)
		self.after(duration, lambda: self.error_label.configure(text=""))

	# --- CONFIGURATION DU PANNEL DROIT ---
	def _create_right_panel(self):
		for widget in self.right_frame.winfo_children():
			widget.destroy()

		default_texts = {
			"Classes": "Veuillez sélectionner une classe",
			"Professeurs": "Veuillez sélectionner un professeur",
			"Salles": "Veuillez sélectionner une salle",
			"Matières": "Veuillez sélectionner une matière",
		}

		ctk.CTkLabel(
			self.right_frame,
			text=default_texts.get(self.tab_name, ""),
			font=ctk.CTkFont(size=self.app.s(20)),
		).pack(pady=self.app.sy(50), padx=self.app.sx(20))

	# --- OUTILS : GRILLE PLANNING (GÉNÉRIQUE) ---
	def _schedule_refresh_cell(self, r: int, c: int):
		if self.schedules_tab[r][c].get():
			self.schedule_btns[r][c].configure(text="✓", fg_color=["#3B8ED0", "#1F6AA5"])
		else:
			self.schedule_btns[r][c].configure(text="—", fg_color=["#CFCFCF", "#4A4A4A"])

	def _schedule_toggle_live(self, r: int, c: int, set_cell):
		new_val = not self.schedules_tab[r][c].get()
		self.schedules_tab[r][c].set(new_val)
		self._schedule_refresh_cell(r, c)
		set_cell(c, r, new_val)
		self.app.mark_dirty()

	def _build_schedule_grid(self, parent, title, days, hours, get_cell, set_cell):
		ctk.CTkLabel(
			parent,
			text=title,
			font=ctk.CTkFont(size=self.app.s(20), weight="bold"),
		).pack(pady=(self.app.sy(20), self.app.sy(10)))

		grid = ctk.CTkFrame(parent, corner_radius=self.app.s(12))
		grid.pack(padx=self.app.sx(20), pady=self.app.sy(10), fill="x")

		rows = len(hours)
		cols = len(days)

		self.schedules_tab = [[tk.BooleanVar() for _ in range(cols)] for _ in range(rows)]
		self.schedule_btns = [[None for _ in range(cols)] for _ in range(rows)]

		ctk.CTkLabel(grid, text="", width=self.app.sx(90)).grid(row=0, column=0, padx=self.app.sx(6), pady=self.app.sy(6))
		for col, d in enumerate(days, start=1):
			ctk.CTkLabel(grid, text=d, font=ctk.CTkFont(size=self.app.s(14), weight="bold")) \
				.grid(row=0, column=col, padx=self.app.sx(6), pady=self.app.sy(6), sticky="nsew")

		for r, h in enumerate(hours):
			ctk.CTkLabel(grid, text=h, font=ctk.CTkFont(size=self.app.s(14), weight="bold")) \
				.grid(row=r + 1, column=0, padx=self.app.sx(6), pady=self.app.sy(6), sticky="w")

			for c in range(cols):
				self.schedules_tab[r][c].set(bool(get_cell(c, r)))

				btn = ctk.CTkButton(
					grid,
					text="",
					width=self.app.sx(52),
					height=self.app.sy(34),
					corner_radius=self.app.s(10),
					command=lambda rr=r, cc=c: self._schedule_toggle_live(rr, cc, set_cell),
				)
				btn.grid(row=r + 1, column=c + 1, padx=self.app.sx(6), pady=self.app.sy(6), sticky="nsew")

				self.schedule_btns[r][c] = btn
				self._schedule_refresh_cell(r, c)

		for c in range(cols + 1):
			grid.grid_columnconfigure(c, weight=1)

	# --- OUTILS : MATIÈRES (PROFS) ---
	def _refresh_subject_chips(self):
		for w in getattr(self, "selected_chip_widgets", []):
			try:
				w.destroy()
			except:
				pass
		self.selected_chip_widgets = []

		selected = [s for s, v in self.subject_vars.items() if v.get()]
		selected.sort(key=lambda s: s.name.lower())

		if not selected:
			lbl = ctk.CTkLabel(self.subject_chips_flow, text="(aucune matière sélectionnée)")
			lbl.pack(anchor="w")
			self.selected_chip_widgets.append(lbl)
			return

		max_cols = 4
		r = c = 0
		for subject in selected:
			chip = ctk.CTkFrame(self.subject_chips_flow, corner_radius=999)
			chip.grid(row=r, column=c, padx=self.app.sx(4), pady=self.app.sy(4), sticky="w")
			self.selected_chip_widgets.append(chip)

			ctk.CTkLabel(chip, text=subject.name, padx=self.app.sx(10)).pack(side="left", pady=self.app.sy(6))

			x = ctk.CTkButton(
				chip, text="✕",
				width=self.app.sx(28),
				height=self.app.sy(24),
				corner_radius=999,
				command=lambda s=subject: self._unselect_subject(s)
			)
			x.pack(side="right", padx=self.app.sx(6), pady=self.app.sy(4))
			self.selected_chip_widgets.append(x)

			c += 1
			if c >= max_cols:
				c = 0
				r += 1

	def _unselect_subject(self, subject):
		if subject in self.subject_vars:
			self.subject_vars[subject].set(False)
			self._teacher_apply_subjects_live(self.current_teacher)

	def _filter_subjects_list(self):
		query = self.subject_search_entry.get().strip().lower()
		for subject, row in self.subject_checks.items():
			show = (query in subject.name.strip().lower()) if query else True
			if show:
				if not row.winfo_ismapped():
					row.pack(fill="x", pady=self.app.sy(4), padx=self.app.sx(5))
			else:
				if row.winfo_ismapped():
					row.pack_forget()

	def _teacher_apply_subjects_live(self, teacher):
		teacher.skills = [s for s, v in self.subject_vars.items() if v.get()]
		self._refresh_subject_chips()
		self.app.mark_dirty()

	# --- OUTILS : MATIÈRES (CLASSES) ---
	def _student_apply_course_live(self, studentclass):
		studentclass.course.clear()
		for subject, controls in self.class_widgets.items():
			if controls["var"].get():
				raw = controls["hours"].get().strip()
				try:
					nb = int(raw) if raw != "" else 0
				except:
					nb = 0
				studentclass.course[subject] = nb
		self.app.mark_dirty()
		self._refresh_class_chips()

	def _refresh_class_chips(self):
		for w in getattr(self, "class_chip_widgets", []):
			try:
				w.destroy()
			except:
				pass
		self.class_chip_widgets = []

		selected = [s for s, ctrl in self.class_widgets.items() if ctrl["var"].get()]
		selected.sort(key=lambda s: s.name.lower())

		if not selected:
			lbl = ctk.CTkLabel(self.class_chips_flow, text="(aucune matière sélectionnée)")
			lbl.pack(anchor="w")
			self.class_chip_widgets.append(lbl)
			return

		max_cols = 4
		r = c = 0
		for subject in selected:
			try:
				hours = int(self.class_widgets[subject]["hours"].get().strip() or "0")
			except:
				hours = 0

			chip = ctk.CTkFrame(self.class_chips_flow, corner_radius=999)
			chip.grid(row=r, column=c, padx=self.app.sx(4), pady=self.app.sy(4), sticky="w")
			self.class_chip_widgets.append(chip)

			ctk.CTkLabel(chip, text=f"{subject.name} · {hours}h", padx=self.app.sx(10)).pack(side="left", pady=self.app.sy(6))

			x = ctk.CTkButton(
				chip, text="✕",
				width=self.app.sx(28),
				height=self.app.sy(24),
				corner_radius=999,
				command=lambda s=subject: self._class_unselect_subject(s)
			)
			x.pack(side="right", padx=self.app.sx(6), pady=self.app.sy(4))
			self.class_chip_widgets.append(x)

			c += 1
			if c >= max_cols:
				c = 0
				r += 1

	def _class_unselect_subject(self, subject):
		if subject in self.class_widgets:
			self.class_widgets[subject]["var"].set(False)
			e = self.class_widgets[subject]["hours"]
			e.configure(state="disabled")
			e.delete(0, "end")
			e.insert(0, "0")
			self._student_apply_course_live(self.current_class)

	def _filter_class_subjects_list(self):
		query = self.class_search_entry.get().strip().lower()
		for subject, row in self.class_rows.items():
			show = (query in subject.name.lower()) if query else True
			if show:
				if not row.winfo_ismapped():
					row.pack(fill="x", pady=self.app.sy(4), padx=self.app.sx(5))
			else:
				if row.winfo_ismapped():
					row.pack_forget()

	# --- PANELS : PROFESSEURS ---
	def _teacher_panel(self, name):
		teacher = None
		for elt in self.app.school.teachers:
			if elt.name == name:
				teacher = elt
				break
		if teacher is None:
			return
		self.current_teacher = teacher

		ctk.CTkLabel(
			self.right_frame,
			text="Matières enseignées :",
			font=ctk.CTkFont(size=self.app.s(20), weight="bold"),
		).pack(pady=(self.app.sy(10), self.app.sy(6)))

		self.subject_vars = {}
		self.subject_checks = {}
		self.selected_chip_widgets = []

		search_row = ctk.CTkFrame(self.right_frame, fg_color="transparent")
		search_row.pack(fill="x", padx=self.app.sx(15), pady=self.app.sy(5))

		ctk.CTkLabel(search_row, text="Rechercher :", font=ctk.CTkFont(size=self.app.s(14))).pack(
			side="left", padx=(0, self.app.sx(8))
		)

		self.subject_search_entry = ctk.CTkEntry(search_row, placeholder_text="ex: maths, histoire…")
		self.subject_search_entry.pack(side="left", fill="x", expand=True)
		self.subject_search_entry.bind("<KeyRelease>", lambda e: self._filter_subjects_list())

		chips_box = ctk.CTkFrame(self.right_frame, corner_radius=self.app.s(12))
		chips_box.pack(fill="x", padx=self.app.sx(15), pady=(self.app.sy(8), self.app.sy(8)))

		ctk.CTkLabel(chips_box, text="Sélection :", font=ctk.CTkFont(size=self.app.s(14), weight="bold")).pack(
			anchor="w", padx=self.app.sx(10), pady=(self.app.sy(8), self.app.sy(4))
		)

		self.subject_chips_flow = ctk.CTkFrame(chips_box, fg_color="transparent")
		self.subject_chips_flow.pack(fill="x", padx=self.app.sx(10), pady=(0, self.app.sy(10)))

		list_box = ctk.CTkScrollableFrame(self.right_frame, corner_radius=self.app.s(12), height=self.app.sy(220))
		list_box.pack(fill="both", expand=False, padx=self.app.sx(15), pady=self.app.sy(8))

		for subject in self.app.school.subjects:
			var = tk.BooleanVar(value=(subject in teacher.skills))
			self.subject_vars[subject] = var

			row = ctk.CTkFrame(list_box, fg_color="transparent")
			row.pack(fill="x", pady=self.app.sy(4), padx=self.app.sx(5))

			ctk.CTkCheckBox(
				row,
				text=subject.name,
				variable=var,
				command=lambda t=teacher: self._teacher_apply_subjects_live(t)
			).pack(anchor="w", padx=self.app.sx(6), pady=self.app.sy(4))

			self.subject_checks[subject] = row

		self._refresh_subject_chips()

		days = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi"]
		hours = ["8-10h", "10-12h", "13-15h", "15-17h"]

		def get_cell(day, slot):
			return any(val == 0 for time, val in getattr(teacher, "slots", []) if time.day == day and time.start == slot)

		def set_cell(day, slot, is_available: bool):
			if not hasattr(teacher, "slots") or len(teacher.slots) != 20:
				teacher.slots = [(api.TimeSlot(d, s), 0) for d in range(5) for s in range(4)]
			idx = 4 * day + slot
			teacher.slots[idx] = (api.TimeSlot(day, slot), 0 if is_available else 2)

		self._build_schedule_grid(self.right_frame, "Emploi du temps :", days, hours, get_cell, set_cell)

	# --- PANELS : SALLES ---
	def _room_panel(self, name):
		room = None
		for elt in self.app.school.rooms:
			if elt.name == name:
				room = elt
				break
		if room is None:
			return

		days = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi"]
		hours = ["8-10h", "10-12h", "13-15h", "15-17h"]

		def get_cell(day, slot):
			return any(val == 0 for time, val in getattr(room, "slots", []) if time.day == day and time.start == slot)

		def set_cell(day, slot, is_available: bool):
			if not hasattr(room, "slots") or len(room.slots) != 20:
				room.slots = [(api.TimeSlot(d, s), 0) for d in range(5) for s in range(4)]
			idx = 4 * day + slot
			room.slots[idx] = (api.TimeSlot(day, slot), 0 if is_available else 2)

		self._build_schedule_grid(self.right_frame, "Disponibilités de la salle :", days, hours, get_cell, set_cell)

	# --- PANELS : CLASSES ---
	def _studentclass_panel(self, name):
		studentclass = None
		for elt in self.app.school.classes:
			if elt.name == name:
				studentclass = elt
				break
		if studentclass is None:
			return

		self.current_class = studentclass

		ctk.CTkLabel(
			self.right_frame,
			text="Matières à enseigner :",
			font=ctk.CTkFont(size=self.app.s(20), weight="bold"),
		).pack(pady=(self.app.sy(10), self.app.sy(6)))

		self.class_widgets = {}
		self.class_rows = {}
		self.class_chip_widgets = []

		search_row = ctk.CTkFrame(self.right_frame, fg_color="transparent")
		search_row.pack(fill="x", padx=self.app.sx(15), pady=self.app.sy(5))

		ctk.CTkLabel(search_row, text="Rechercher :", font=ctk.CTkFont(size=self.app.s(14))).pack(
			side="left", padx=(0, self.app.sx(8))
		)

		self.class_search_entry = ctk.CTkEntry(search_row, placeholder_text="ex: maths, histoire…")
		self.class_search_entry.pack(side="left", fill="x", expand=True)
		self.class_search_entry.bind("<KeyRelease>", lambda e: self._filter_class_subjects_list())

		chips_box = ctk.CTkFrame(self.right_frame, corner_radius=self.app.s(12))
		chips_box.pack(fill="x", padx=self.app.sx(15), pady=(self.app.sy(8), self.app.sy(8)))

		ctk.CTkLabel(chips_box, text="Sélection :", font=ctk.CTkFont(size=self.app.s(14), weight="bold")).pack(
			anchor="w", padx=self.app.sx(10), pady=(self.app.sy(8), self.app.sy(4))
		)

		self.class_chips_flow = ctk.CTkFrame(chips_box, fg_color="transparent")
		self.class_chips_flow.pack(fill="x", padx=self.app.sx(10), pady=(0, self.app.sy(10)))

		list_box = ctk.CTkScrollableFrame(self.right_frame, corner_radius=self.app.s(12), height=self.app.sy(260))
		list_box.pack(fill="both", expand=False, padx=self.app.sx(15), pady=self.app.sy(8))

		for subject in self.app.school.subjects:
			row = ctk.CTkFrame(list_box, fg_color="transparent")
			row.pack(fill="x", pady=self.app.sy(4), padx=self.app.sx(5))

			var = tk.BooleanVar(value=(subject in studentclass.course))

			chk = ctk.CTkCheckBox(row, text=subject.name, variable=var)
			chk.pack(side="left", padx=self.app.sx(6), pady=self.app.sy(6))

			ctk.CTkLabel(row, text="heures", width=self.app.sx(60)).pack(side="right", pady=self.app.sy(6))

			hours_entry = ctk.CTkEntry(row, width=self.app.sx(70))
			hours_entry.pack(side="right", padx=self.app.sx(6), pady=self.app.sy(6))

			if subject in studentclass.course:
				hours_entry.insert(0, str(studentclass.course[subject]))
				hours_entry.configure(state="normal")
			else:
				hours_entry.insert(0, "0")
				hours_entry.configure(state="disabled")

			def toggle_hours(v=var, e=hours_entry, sc=studentclass):
				if v.get():
					e.configure(state="normal")
					if e.get().strip() == "":
						e.insert(0, "0")
				else:
					e.configure(state="disabled")
					e.delete(0, "end")
					e.insert(0, "0")
				self._student_apply_course_live(sc)

			chk.configure(command=toggle_hours)
			hours_entry.bind("<KeyRelease>", lambda ev, sc=studentclass: self._student_apply_course_live(sc))

			self.class_widgets[subject] = {"var": var, "hours": hours_entry}
			self.class_rows[subject] = row

		self._refresh_class_chips()


class EDTApp(ctk.CTk):
	def __init__(self):
		super().__init__()

		self.school = api.School()

		self.base_width = 1920
		self.base_height = 1080
		screen_w = self.winfo_screenwidth()
		screen_h = self.winfo_screenheight()
		scale_x = screen_w / self.base_width
		scale_y = screen_h / self.base_height
		scale = min(scale_x, scale_y)

		self.s = lambda px: max(1, int(px * scale))
		self.sx = lambda px: max(1, int(px * scale_x))
		self.sy = lambda px: max(1, int(px * scale_y))

		self.title("Gestionnaire d'Emploi du Temps")
		self.attributes("-fullscreen", True)
		self.bind("<Escape>", lambda e: self.safe_quit())

		self.dirty = False

		self.load()
		self.selected_tab = None
		self._create_tabs()
		self._set_save_state(needs_save=False)

	# --- ÉTAT SAUVEGARDE ---
	def mark_dirty(self):
		if not self.dirty:
			self.dirty = True
			self._set_save_state(needs_save=True)

	def _set_save_state(self, needs_save: bool):
		if needs_save:
			text = "Enregistrer ●"
			fg = "#3B8ED0"
			hover = "#1F6AA5"
			border = "#1F6AA5"
			text_color = "white"
			state = "normal"
		else:
			text = "Enregistré ✓"
			fg = "#D5D8DC"
			hover = "#D5D8DC"
			border = "#ABB2B9"
			text_color = "#1C2833"
			state = "disabled"

		self.save_btn.configure(
			text=text,
			fg_color=fg,
			hover_color=hover,
			border_color=border,
			text_color=text_color,
			state=state
		)

	# --- UI PRINCIPALE ---
	def _create_tabs(self):
		self.tab_tools_frame = ctk.CTkFrame(self)
		self.tab_tools_frame.pack(fill="x")
		self.tab_tools_frame.configure(fg_color="#ABB2B9", bg_color="#ABB2B9")

		self.tab_buttons_frame = ctk.CTkFrame(self)
		self.tab_buttons_frame.pack(fill="x")

		self.content_frame = ctk.CTkFrame(self)
		self.content_frame.pack(fill="both", expand=True)

		self.tabs = {}
		self.tabs_btn = {}

		tab_names = ["Classes", "Professeurs", "Salles", "Matières"]
		for name in tab_names:
			btn = ctk.CTkButton(
				self.tab_buttons_frame,
				text=name,
				fg_color=['#3B8ED0', '#1F6AA5'],
				font=ctk.CTkFont(size=self.s(20)),
				command=lambda n=name: self._select_button(n),
				corner_radius=0,
				border_width=self.s(2),
				border_color="#2E86C1",
			)
			btn.pack(side="left", fill="x", expand=True)

			tab_frame = TabView(self.content_frame, name, self)
			self.tabs[name] = tab_frame
			self.tabs_btn[name] = btn

		# --- BOUTONS EN HAUT (DROITE) ---
		self.quit_btn = ctk.CTkButton(
			self.tab_tools_frame,
			text="Quitter",
			fg_color="#E74C3C",
			hover_color="#C0392B",
			text_color="white",
			font=ctk.CTkFont(size=self.s(18), weight="bold"),
			command=self.safe_quit,
			corner_radius=0,
			height=self.sy(20),
			border_width=self.s(2),
			border_color="#922B21"
		)
		self.quit_btn.pack(side="right", fill="x")

		self.edt_btn = ctk.CTkButton(
			self.tab_tools_frame,
			text="Générer l’EDT",
			fg_color="#5DADE2",
			hover_color="#3498DB",
			text_color="white",
			font=ctk.CTkFont(size=self.s(18), weight="bold"),
			command=self.compute_edt,
			corner_radius=0,
			height=self.sy(20),
			border_width=self.s(2),
			border_color="#21618C"
		)
		self.edt_btn.pack(side="right", fill="x")

		self.save_btn = ctk.CTkButton(
			self.tab_tools_frame,
			text="Enregistré ✓",
			fg_color="#D5D8DC",
			hover_color="#D5D8DC",
			text_color="#1C2833",
			font=ctk.CTkFont(size=self.s(18), weight="bold"),
			command=self.save,
			corner_radius=self.s(0),
			height=self.sy(20),
			border_width=self.s(2),
			border_color="#D5D8DC",
		)
		self.save_btn.pack(side="right", fill="x")

		self.show_tab(tab_names[0])

	def show_tab(self, tab_name):
		for tab in self.tabs.values():
			tab.pack_forget()
		self.tabs[tab_name].pack(fill="both", expand=True)

	# --- ACTIONS ---
	def safe_quit(self):
		if not self.dirty:
			self.after(100, self.destroy)
			return

		msg = CTkMessagebox(
			title="Enregistrer à la fermeture",
			message="Voulez-vous enregistrer avant de quitter ?",
			icon="question",
			option_1="Annuler",
			option_2="Non",
			option_3="Oui",
			width=480
		)
		response = msg.get()
		if response == "Oui":
			self.save()
			self.after(100, self.destroy)
		elif response == "Non":
			self.after(100, self.destroy)

	def save(self):
		save_load.store(self.school)
		self.dirty = False
		self._set_save_state(needs_save=False)

	# --- DONNÉES ---
	def load(self):
		data_loaded = save_load.load()
		if data_loaded is not None:
			self.school = data_loaded

	def compute_edt(self):
		timetable = solver.solve(self.school)
		if timetable is not None:
			consultation.display(timetable)
		else:
			print("No solution found")

	def _select_button(self, name):
		if self.selected_tab != name and self.selected_tab is not None:
			self.tabs_btn[self.selected_tab].configure(
				fg_color=['#3B8ED0', '#1F6AA5'],
				border_color="#2E86C1"
			)

		self.tabs_btn[name].configure(
			fg_color=self.tabs_btn[name].cget("hover_color"),
			border_color=self.tabs_btn[name].cget("hover_color")
		)
		self.selected_tab = name
		self.show_tab(name)


# --- LANCEMENT DU PROGRAMME ---
if __name__ == "__main__":
	appedt = EDTApp()
	appedt.mainloop()