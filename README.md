# Integrated-Project

Tool for generating school timetables from constraints. We provide a clean and efficient interface (and then we'll try to optimize the tables).



## VENV -- work in progress

See [here](https://blog.stephane-robert.info/docs/developper/programmation/python/uv/) for managing `uv`, which we use for virtual environments. 

For dependencies, see `pydeps`, add other to .toml file, ...

`graphviz` and `pydeps` must be installed on your system; then generate the .svg deps file with the command

``pydeps edt-main/code/main.py -o deps-graphs/main.svg``