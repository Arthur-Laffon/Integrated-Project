# Integrated-Project

Tool for generating school timetables from constraints. We provide a clean and efficient interface (and then we'll try to optimize the tables).



## VENV -- work in progress + requirements

See [here](https://blog.stephane-robert.info/docs/developper/programmation/python/uv/) for managing `uv`, which we use for virtual environments. 


## Dependency graph

For dependencies, see `pydeps`, add other to .toml file, ...

`graphviz` and `pydeps` must be installed on your system; then generate the .svg deps file with the command

``pydeps the/main/file.py -o deps-graphs/main.svg``


## Pipelines

see [here for gitlab](https://docs.gitlab.com/ci/pipelines/), [here for github](https://blog.stephane-robert.info/docs/pipeline-cicd/github/fondations/)