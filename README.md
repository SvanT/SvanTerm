SvanTerm is a terminal window manager for cygwin which supports tabbing, splitting of windows, moving splits around, searching for windows and more.

![SvanTerm screenshot](/screenshot.png "SvanTerm screenshot")

Installation
============
1. Download the 64-bit cygwin installer:
	http://cygwin.com/setup-x86_64.exe
2. Run the installer to install 64-bit cygwin to it's default location (C:\cygwin64), make sure you go through the package selection and add tools you might want, some recommendations:
	- bind-utils (host, dig)
	- curl
	- git
	- mosh (latency friendly alternativ to ssh, http://mosh.mit.edu/)
	- nano
	- openssh (for the ssh client and ssh server)
	- procps (top)
	- rsync
	- tig (ncurses based git history viewer)
	- wget
	- whois
	(you can always run the installer again to install more packages)
3. Unpack the svanterm package
4. Run svanterm.exe

Keyboard shortcuts
==================
Ctrl-Shift-T   Create tab
Ctrl-Shift-W   Close tab
Ctrl-Shift-H   Horizontal split
Ctrl-Shift-V   Vertical split
Ctrl-Shift-C   Close active terminal
Ctrl-Shift-J   Select previous terminal in tab
Ctrl-Shift-K   Select next terminal in tab
Ctrl-Shift-U   Select previous tab
Ctrl-Shift-I   Select next tab
Ctrl-Shift-O   Select previous window
Ctrl-Shift-P   Select next window
Ctrl-Shift-R   Rename tab
Ctrl-Shift-N   New window
Ctrl-Shift-F   Find terminal (type what you want to search for, cycle through the results with up/down-arrows)
Ctrl-Shift-A   Make terminal smaller horizontally
Ctrl-Shift-S   Make terminal bigger horizontally
Ctrl-Shift-Z   Make terminal smaller vertically
Ctrl-Shift-X   Make terminal bigger vertically
Ctrl-Shift-F1  Select tab #1
...
Ctrl-Shift-F12 Select tab #12

Tips and tricks
===============
- Drag and drop the header of a terminal (the red/grey area) to dock it to another terminal/tab/window
- Drag and drop a tab to another window or a new window
- Rename tabs to custom names to make them easier to find, you can use Ctrl-Shift-F to either search for the tab name or the individual terminals

Development requirements
========================
- Python 2.7 (Windows x86-64)
	- 64-bits https://www.python.org/download
- PyWin32 (amd64-py2.7)
	- http://sourceforge.net/projects/pywin32/files/pywin32/
- wxPython (win64-py27)
	- http://www.wxpython.org/download.php#msw
- PyInstaller (for building binaries)
	- http://www.pyinstaller.org/
