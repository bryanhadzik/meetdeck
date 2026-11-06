TIMING BRIDGE - Colorado Time Systems System 6  <->  Meet Entry Check
=====================================================================
STATUS: written from the documented protocol and tested against the built-in
simulator only. The first session with a real console will confirm the serial
settings and data layout - everything sent/received is logged in cts-log.txt.

WHAT YOU NEED
 - Windows laptop with Python 3.9+ (python.org; tick "Add to PATH").
 - USB-to-serial adapter (FTDI chip preferred over Prolific on Windows 11).
 - Straight-through DB-9 male/female RS-232 cable (NOT null modem), under 25 ft.
 - Plug into the console's "COM PORT 1" (not the scoreboard port).

CONSOLE SETUP
 - Set date/time (Setups > Set Date/Time).  Power-cycle before each session
   (each power-on starts a new meet on the console).
 - To receive events: Setups > Hardware > Allow Remote Setup = ON, then Quit.
   The console must be in RESET (not running a race, not on a Setups screen).
 - Run one test heat and Store/Print it before the meet.

RUN
 - Double-click start-bridge.bat (installs pyserial the first time).
 - Open the meet database page > Events > Timing console > pick the COM port >
   Connect. It tries the usual serial settings until the console answers.
 - Per heat: "Get times" pulls the stored race for that event/heat, shows
   final, backup and place per lane; "Apply" writes them into the meet.
 - "Send events to console" writes the meet's events into an event sequence
   slot (8 or 9 recommended) and makes it active. Heats are advanced on the
   console by the operator, as with Meet Manager.

PRACTICE WITHOUT A CONSOLE
 - Double-click start-simulator.bat, connect, and use "Load practice times".

COMMAND LINE
 python bridge.py probe COM5     find the serial settings
 python bridge.py races COM5     list the console's stored races
