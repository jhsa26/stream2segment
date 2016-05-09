# stream2segment

A python project to download seismic waveforms related to events

## Installation (tested on Ubuntu14.04 - Ubuntu 12.10)

This program has been written on Mac OS El Capitan, but a fresh installation test could be done on Ubuntu only. Mac users can safely follow the instructions below (skipping the [Prerequisites](#prerequisites) section), but in case of problems we did not keep track (yet) of the solutions here

### Prerequisites
The following system packages are required: `git python-pip python2.7-dev libpng-dev libfreetype6-dev 
build-essential gfortran libatlas-base-dev libxml2-dev libxslt-dev`
If you want to be (almost) sure beforehand, you can install them by typing:
```
sudo apt-get update
sudo apt-get upgrade gcc
sudo apt-get install git python-pip python2.7-dev libpng-dev libfreetype6-dev \
	build-essential gfortran libatlas-base-dev libxml2-dev libxslt-dev
```
However, you can also skip this section and get back here in case of problems
(see also the section [Installation Notes](#installation-notes))

### Cloning repository

Git-clone (basically: download) this repository to a specific folder of your choice:
```
git clone https://github.com/rizac/stream2segment.git
```
and move into package folder:
```
cd stream2segment
```

### Install and activate python virtualenv

We strongly recomend to use python virtual environment. Why? Because by isolating all python packages we are about to install, we won't create conflicts with already installed packages. However feel free to skip this part (at your own risk, but you might know what you're doing). To install python virtual environment
```
sudo pip install virtualenv
```

Make virtual environment in an stream2segment/env directory (env is a convention, but it's ignored by git commits so keep it)
 ```
virtualenv env
 ```
and activate it:
 ```
 source env/bin/activate
 ```

> <sub>Activation needs to be done __each time__ we will run the program. See section [Usage](#usage) below</sub>
> <sub>Check: To check you are in the right env, type: `which pip` and you should see it's pointing inside the env folder</sub>


### Install and config packages

Install numpy, to be done first of all
```
pip install numpy==1.10.4
```

Install the current package
```
pip install -e .
```

Copy default config to a config file (not included in git commit):
```
cp config.example.yaml config.yaml
```
and edit it if you whish

Last setting with matplotlib: use a backedn which is able to show figures (for `stream2segment --gui` options). Create the file (if it does not exist) `$HOME/.config/matplotlib/matplotlibrc`, oopen it and add the line:
```backend: TkAgg```
You can also create a `matplotlibrc` in the stream2segment directory. Advantage: it can be used for specific customizations that you do not want to apply elsewhere (if you have other matplotlib settings). Drawbacks: you need to cd to stream2segment for making the program work

## Usage

Move (`cd` on a terminal) to the stream2segment folder. If you installed and activated a python virtual environment during installation (hopefully you did), **activate the virtual environment first**:
```
source env/bin/activate
```

> <sub>When you're finished, type `deactivate` on the terminal to deactivate the current pythoin virtual environment and return to the global system defined Python</sub>

Edit config.yaml file if needed, or type ```stream2segment --help``` for command line options (options in config.yaml are the default. If given, command line options will override the defaults)

Eventually run
```
stream2segment
```

## Installation Notes:

- On Ubuntu 12.10, there might be problems with libxml (`version libxml2_2.9.0' not found`). 
Move the file or create a link in the proper folder. The problem has been solved looking at
http://phersung.blogspot.de/2013/06/how-to-compile-libxml2-for-lxml-python.html

- On Ubuntu 14.04 
All following issues should be solved by following the instructions in the section [Prerequisites](#prerequisites). However,
 - For numpy installation problems (such as `Cannot compile 'Python.h'`) , the fix
has been to update gcc and install python2.7-dev: 
	```sudo apt-get update
	sudo apt-get upgrade gcc
	sudo apt-get install python2.7-dev```
	For details see http://stackoverflow.com/questions/18785063/install-numpy-in-python-virtualenv
 - For matplotlib problems, `libpng-dev libfreetype6-dev` are required (see http://stackoverflow.com/questions/25593512/cant-install-matplotlib-using-pip and http://stackoverflow.com/questions/28914202/pip-install-matplotlib-fails-cannot-build-package-freetype-python-setup-py-e)
 - For scipy problems, `build-essential gfortran libatlas-base-dev` are required for scipy (see http://stackoverflow.com/questions/2213551/installing-scipy-with-pip/3865521#3865521)
 - For lxml problems, `libxml2-dev libxslt-dev` are required (see here: http://lxml.de/installation.html)
