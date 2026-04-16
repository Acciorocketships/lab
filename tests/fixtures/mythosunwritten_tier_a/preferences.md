# Preferences

- as simple and readable as possible
- as concise as possible
- keep things organised by function. ideally that will make the code modular so we can swap pieces in/out and they all work with each other
- if there are bunch of exceptions and corner cases then it probably means the code needs to be refactored, there is probably a more elegant way to represent things that doesn’t require handling so many corner cases.
- no command line arguments, instead define the config overrides in a run script
- no thin wrappers (e.g. unnecessary abstractions or dataclasses that make it hard to follow the code, one line wrappers especially when they are only used in one place, etc)
- make it general so it maximises reusability in the future (while not sacrificing simplicity or making the code longer)
- each function should have a short docstring explaining what it does / where it fits in the overall pipeline / why it is needed / where it is called
- make it easy for a human to understand. this means a simple control flow, an architecture that can easily be described at a high level, and not too many classes to understand (we don’t want to unnecessarily create 5 different inheritances just to solve a simple problem).
- put ugly but generally reusable functions in a helpers file.
- if a file is named after a class, that class should be the first thing after the imports
- make it a python package. the src folder should have all of the code related to the package. there should also be a separate scripts folder where all of the experiments are kept. they should just import and use the main package. there should also be a tests folder and a data folder. the data folder should include any input or output data, and shouldn’t be included in git. use a a conda env for env control.
- write tests as you go and periodically run them to make sure nothing has broken.
- maintain a readme that explains the overall pipeline of the project, and then each component in more detail.
- if there is domain-specific code, that code should be separated from the core code (ideally in a separate folder). the core code should be architected in a way that it works with any application. that way if we need to add a new application we don’t have to touch the core code.

