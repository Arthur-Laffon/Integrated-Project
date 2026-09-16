import customtkinter as ctk


class CheckBoxDropdown(ctk.CTkFrame):
	"""
	Class to define scrollable Dropdown list with checkboxes and a search field 
	"""
	def __init__(self, master, values, width=240, height=260,text="Select options", **kwargs):
		super().__init__(master, **kwargs)

		self.values = values
		self.width = width
		self.height = height

		self.vars = {v: ctk.BooleanVar() for v in values}
		self.filtered_values = values.copy()
		self.checkboxes = []

		self.button = ctk.CTkButton(self, text=text, width=width, command=self.toggle_menu)
		self.button.pack()

		self.popup = None
		self.search_var = ctk.StringVar()
		self.active_index = 0


	###### Menu Gestion #########

	def toggle_menu(self):
		if self.popup and self.popup.winfo_exists():
			self.close_menu()
		else:
			self.open_menu()

	def open_menu(self):
		self.popup = ctk.CTkToplevel(self)
		self.popup.overrideredirect(True)
		self.popup.attributes("-topmost", True)

		x = self.winfo_rootx()
		y = self.winfo_rooty() + self.winfo_height()
		self.popup.geometry(f"{self.width}x{self.height}+{x}+{y}")

		container = ctk.CTkFrame(self.popup)
		container.pack(fill="both", expand=True, padx=4, pady=4)

		# Search bar
		self.search_var.set("")
		self.search_entry = ctk.CTkEntry(
			container, textvariable=self.search_var, placeholder_text="Search..."
		)
		self.search_entry.pack(fill="x", padx=6, pady=(6, 4))
		self.search_entry.bind("<KeyRelease>", self.filter_items)

		# Scroll area
		self.scroll = ctk.CTkScrollableFrame(container)
		self.scroll.pack(fill="both", expand=True, padx=4, pady=4)

		self.build_list()

		self.popup.bind("<FocusOut>", lambda _ : self.close_menu())
		self.popup.bind("<Escape>", lambda _ : self.close_menu())
		self.popup.bind("<Down>", self.key_down)
		self.popup.bind("<Up>", self.key_up)
		self.popup.bind("<Return>", self.key_toggle)

		self.popup.focus_force()
		self.search_entry.focus()

	def close_menu(self):
		if self.popup:
			self.popup.destroy()
			self.popup = None


	##### List Gestion ########

	def build_list(self):
		for w in self.scroll.winfo_children():
			w.destroy()

		self.checkboxes.clear()

		for _, value in enumerate(self.filtered_values):
			chk = ctk.CTkCheckBox(
				self.scroll,
				text=value,
				variable=self.vars[value],
				command=self.update_text
			)
			chk.pack(anchor="w", padx=8, pady=4, fill="x")
			self.checkboxes.append(chk)

		self.active_index = 0
		self.highlight_active()

	def filter_items(self, event=None):
		text = self.search_var.get().lower()

		if text:
			self.filtered_values = [v for v in self.values if text in v.lower()]
		else:
			self.filtered_values = self.values.copy()

		self.build_list()


	def highlight_active(self):
		for _, chk in enumerate(self.checkboxes):
			chk.configure(fg_color=("lightblue", "blue"))

	def key_down(self, event):
		if self.active_index < len(self.checkboxes) - 1:
			self.active_index += 1
			self.highlight_active()
			self.checkboxes[self.active_index].focus()

	def key_up(self, event):
		if self.active_index > 0:
			self.active_index -= 1
			self.highlight_active()
			self.checkboxes[self.active_index].focus()

	def key_toggle(self, event):
		if self.checkboxes:
			current = self.filtered_values[self.active_index]
			self.vars[current].set(not self.vars[current].get())
			self.update_text()

	def update_text(self):
		selected = [k for k, v in self.vars.items() if v.get()]
		self.button.configure(text=", ".join(selected) if selected else "Select options")

	def get_selected(self):
		return [k for k, v in self.vars.items() if v.get()]



if __name__ == "__main__":
	#minimal Test 
	ctk.set_appearance_mode("dark")
	ctk.set_default_color_theme("blue")

	app = ctk.CTk()
	app.geometry("450x350")

	items = [f"Option {i}" for i in range(1, 51)]

	dropdown = CheckBoxDropdown(app, items)
	dropdown.pack(pady=50)

	def show():
		print(dropdown.get_selected())

	ctk.CTkButton(app, text="Print Selection", command=show).pack()

	app.mainloop()
