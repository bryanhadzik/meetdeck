@echo off
rem CTS System 6 console emulator - uses MeetDeck's own Python
cd /d "%~dp0"
"%~dp0..\..\python\python.exe" -X utf8 "%~dp0emulator.py" %*
