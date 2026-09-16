from api import *
from Interface.interface import *
from Solver.solver import *

from tkinter import *
from tkinter.ttk import *


def main():
    appedt = EDTApp()				# Create the main window        
    appedt.mainloop()           # Run the Tkinter event loop

if __name__ == "__main__":
    main()
    save_load.load()