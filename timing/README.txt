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


CONSOLE EMULATOR (test without the real console; capture what Meet Manager sends)
================================================================================
emulator.py plays the System 6 on a COM port. Meet Manager - or this bridge - talks
to it exactly as it would to the console, and every byte is logged and decoded.

HOOK-UP: the two programs need the two ends of a serial "cable":
 - Virtual (no hardware): install com0com (signed 64-bit build, 2.2.2.0, from
   sourceforge.net/projects/com0com). In its Setup, make a pair and name the ends,
   e.g. COM6 <-> COM7.
 - Or hardware: two USB-serial adapters joined by a NULL-MODEM cable/adapter.

CAPTURE MEET MANAGER
 1. Double-click start-emulator.bat and give it COM6 (one end of the pair).
 2. In Meet Manager, set the timing console interface to the Colorado System 6 on
    COM7 (the other end), 9600 baud. Then:
      - send/download the meet's events to the console, and
      - do a "get times" for a heat (start the emulator with --practice so events
        1-4, heats 1-2 have stored races to read).
 3. Ctrl+C the emulator. Send these two files back:
      emulator-log.txt        every message both ways, with what it means
      emulator-capture.json   events/labels Meet Manager stored, every command it
                              used, and anything that wasn't a console message
 If the log shows "BAD CHECKSUM", the serial settings differ: restart with
 --parity E (or O). If Meet Manager sends things marked UNKNOWN or NOT A CONSOLE
 MESSAGE, that is new protocol to learn - the log has the exact bytes.
 --listen-only records without ever answering (to see Meet Manager's first move).

TEST MEETDECK THE SAME WAY
 Emulator on COM6, start-bridge.bat, then in the meet database page's Timing console
 connect to COM7: "Send events to console" and "Get times" go to the emulator.
