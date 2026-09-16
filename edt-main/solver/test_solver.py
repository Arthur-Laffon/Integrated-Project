from pychoco import Model
model = Model("EDT_basic")

coursesL3 = ["PROG", "ALGO", "THPROG", "FDI", "ALGEBRE", "TP PROG", "TD ALGO", "TD THPROG", "TD FDI", "TD ALGEBRE"]
coursesM1 = ["TD CS", "CAP", "TD Opt", "TD SV", "TP CAP", "PDAP", "Res", "SV", "TD PDAP", "SIESTE", "IP", "QCS", "Opt", "TD QCS", "CS", "Res"]
rooms = ["B1", "B2"]
# for each course, a couple (day, n°hour) (day in [|1, 5|], hour in [|1, 4|]) and a room
# TODO

solver = model.get_solver()
solver.show_statistics()
solv = solver.find_solution()
#solv.get_int_val(...)