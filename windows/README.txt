MeetDeck for Windows
====================

Start:   double-click MeetDeck.bat (the first start also puts a MeetDeck shortcut on the desktop).
         MeetDeck opens in your web browser. A blue "MD" icon sits in the tray (bottom-right, by the
         clock): Open MeetDeck / Open data folder / Quit MeetDeck.

Data:    Documents\MeetDeck  (meets, host schools' master meets, rules library, settings).
         Back up that folder; the app folder can be replaced with a newer version any time.

Needs:   Windows 10 or 11. Nothing to install - Python is inside this folder, and Meet Manager
         files are opened with Windows' own Microsoft Access driver (the one Meet Manager uses).

Timing:  plug the CTS console into this laptop; the Timing console panel on the Run the meet page
         finds it (the bridge runs inside MeetDeck).

Gmail:   to pull coaches' entry files from Gmail, put GMAIL_USER and GMAIL_APP_PASSWORD in
         Documents\MeetDeck\meetdeck.env, then Quit and start MeetDeck again.

Trouble: "MeetDeck (show log).bat" runs it with a window showing what happens; the log is also in
         Documents\MeetDeck\meetdeck.log.
