import customtkinter as ctk
from tkinter import ttk
import argparse

# Configuration de l'interface
ctk.set_appearance_mode("light")
ctk.set_default_color_theme("blue")

# Constantes pour l'affichage
DAYS = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi"]
HOURS = ["8h-10h", "10h-12h", "13h-15h", "15h-17h"]


# ========== Fonction à appeler pour ouvrir une nouvelle fenêtre et afficher un emploi du temps ===========

def display(timetable, column_width=200, cell_height=150):
    app = TimetableApp(timetable, column_width, cell_height)
    app.mainloop()


class TimetableApp(ctk.CTk):
    def __init__(self, timetable, column_width=200, cell_height=150):
        super().__init__()
        self.title("Emploi du temps")
        self.geometry(str(6 * column_width) + "x" + str(6 * cell_height))
        self.original_timetable = timetable
        self.filtered_timetable = timetable
        self.selected_class = None
        self.selected_teacher = None
        self.COLUMN_WIDTH = column_width
        self.CELL_HEIGHT = cell_height
        self.create_widgets()

    def create_widgets(self):
        for entry in self.original_timetable.timetable:
            print(f"Test {type(entry)} : {entry}")
        # Menus déroulants
        class_names = list(
            {entry.studentClass.name for entry in self.original_timetable.timetable}
        )
        teacher_names = list(
            {entry.teacher.name for entry in self.original_timetable.timetable}
        )

        self.class_menu = ctk.CTkOptionMenu(
            self, values=["Toutes"] + class_names, command=self.filter_by_class
        )
        self.class_menu.grid(row=0, column=0, padx=10, pady=10)

        self.teacher_menu = ctk.CTkOptionMenu(
            self, values=["Tous"] + teacher_names, command=self.filter_by_teacher
        )
        self.teacher_menu.grid(row=0, column=1, padx=10, pady=10)

        self.grid_frame = ctk.CTkFrame(self)
        self.grid_frame.grid(row=1, column=0, columnspan=6, padx=10, pady=10)

        self.update_displayed_timetable()

    def filter_by_class(self, selected):
        self.selected_class = None if selected == "Toutes" else selected
        self.update_displayed_timetable()

    def filter_by_teacher(self, selected):
        self.selected_teacher = None if selected == "Tous" else selected
        self.update_displayed_timetable()

    def update_displayed_timetable(self):
        for widget in self.grid_frame.winfo_children():
            widget.destroy()

        # En-têtes
        for i, day in enumerate([""] + DAYS):
            label = ctk.CTkLabel(
                self.grid_frame, text=day, width=self.COLUMN_WIDTH * 0.8
            )
            label.grid(row=0, column=i, padx=5, pady=5)

        for j, hour in enumerate(HOURS):
            label = ctk.CTkLabel(self.grid_frame, text=hour, width=self.CELL_HEIGHT)
            label.grid(row=j + 1, column=0, padx=5, pady=5)

        # Filtrage
        filtered_entries = self.original_timetable.timetable
        if self.selected_class:
            filtered_entries = [
                e
                for e in filtered_entries
                if e.studentClass.name == self.selected_class
            ]
        if self.selected_teacher:
            filtered_entries = [
                e for e in filtered_entries if e.teacher.name == self.selected_teacher
            ]

        # Affichage
        # Crée une grille complète de cellules fixes
        for day in range(5):
            for start in range(4):
                cell_frame = ctk.CTkFrame(
                    self.grid_frame,
                    width=self.COLUMN_WIDTH * 0.8,
                    height=self.CELL_HEIGHT,
                    fg_color="white",
                    corner_radius=5,
                )
                cell_frame.grid_propagate(False)
                cell_frame.grid(row=start + 1, column=day + 1, padx=5, pady=5)

                # Par défaut, on place un label vide pour forcer la taille
                label = ctk.CTkLabel(
                    cell_frame, text="", height=self.CELL_HEIGHT, anchor="center"
                )
                label.pack(expand=True, fill="both")

        # Ensuite, on remplit les cellules avec les cours
        for entry in filtered_entries:
            day = entry.timeSlot.day
            start = entry.timeSlot.start
            info = f"{entry.subject.name}\n{entry.teacher.name}\n{entry.studentClass.name}\n{entry.room.name}"

            # Création d'une cellule fixe avec fond blanc
            cell_frame = ctk.CTkFrame(
                self.grid_frame,
                width=self.COLUMN_WIDTH * 0.8,
                height=self.CELL_HEIGHT,
                fg_color="white",  # Fond blanc visible
                corner_radius=5,
            )
            cell_frame.grid_propagate(False)  # Empêche le redimensionnement automatique
            cell_frame.grid(row=start + 1, column=day + 1, padx=5, pady=5)

            # Ajout du texte centré (même vide)
            label = ctk.CTkLabel(
                cell_frame,
                text=info,  # ou "" si vide
                justify="center",
                anchor="center",
                wraplength=self.COLUMN_WIDTH * 0.7,
                text_color="black",  # pour contraste sur fond blanc
            )
            label.pack(expand=True, fill="both")


# Quand on exécute ce fichier, ça ouvre l'affichage de la sample_timetable
if __name__ == "__main__":
    # Tu dois ici créer des objets Room, StudentClass, Teacher, Subject, TimeSlot, TimetableEntry
    # et les ajouter dans une instance de Timetable pour tester l'affichage.
    from api import (
        Timetable,
        TimetableEntry,
        Room,
        StudentClass,
        Teacher,
        Subject,
        TimeSlot,
    )
    from tests.sample_timetable import sample_timetable

    parser = argparse.ArgumentParser(
        description="Lance l'affichage de l'emploi du temps."
    )
    parser.add_argument(
        "--cell-height", type=int, default=150, help="Hauteur des cellules"
    )
    parser.add_argument(
        "--column-width", type=int, default=200, help="Largeur des colonnes"
    )
    args = parser.parse_args()

    display(sample_timetable, args.column_width, args.cell_height)
