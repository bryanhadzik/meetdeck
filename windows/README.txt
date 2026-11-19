MeetDeck for Windows
====================

First time (no administrator rights needed)
-------------------------------------------
1. Unzip MeetDeck-Windows.zip into your Documents or Desktop - NOT Program Files. MeetDeck updates
   itself by replacing files in its own folder, and a normal Windows account can't change
   Program Files. (If it's there, MeetDeck says so and tells you to move it.)
2. Double-click MeetDeck.exe. If Windows says "Windows protected your PC", click More info >
   Run anyway (MeetDeck isn't signed by a paid certificate yet). If your school's IT blocks
   programs it hasn't approved, ask them to allow the MeetDeck folder.
3. Windows Firewall may ask about Python. Allow it on private networks if you can. Without an
   administrator you can't - that's fine: MeetDeck still works on this PC, only phones and other
   laptops can't open it. The tray icon says "Only this PC can open MeetDeck" when that's the case.
4. Timing console: the USB-to-serial cable needs its driver. Most get it from Windows Update by
   themselves; if Windows says the device has no driver, the cable maker's installer needs an
   administrator.

Start:   double-click MeetDeck.exe (or MeetDeck.bat). The first start also puts MeetDeck and
         MeetDeck Launcher shortcuts on the desktop. MeetDeck Launcher.exe opens the start / stop /
         update / console-tools window.
         MeetDeck opens in your web browser. A blue "MD" icon sits in the tray (bottom-right, by the
         clock): Open MeetDeck / Open data folder / Quit MeetDeck.

Network: MeetDeck also listens on this PC's network address, so a phone or another laptop on the
         same Wi-Fi can open it: the tray menu shows the address (http://<this PC's IP>:8001).
         The first start may ask to let Python through Windows Firewall - allow it on private
         networks. To keep MeetDeck to this PC only, put MEETDECK_HOST=127.0.0.1 in
         Documents\MeetDeck\meetdeck.env.

Data:    Documents\MeetDeck  (meets, host schools' master meets, rules library, settings).
         Back up that folder; the app folder can be replaced with a newer version any time.

Needs:   Windows 10 or 11. Nothing to install - Python is inside this folder, and Meet Manager
         files are opened with Windows' own Microsoft Access driver (the one Meet Manager uses).

Timing:  plug the CTS console into this laptop; the Timing console panel on the Run the meet page
         finds it (the bridge runs inside MeetDeck).

Trouble: "MeetDeck (show log).bat" runs it with a window showing what happens; the log is also in
         Documents\MeetDeck\meetdeck.log.
