@echo off
rem Open Sanae in its own window (starts Sanae in the background if it isn't running).
cd /d "%~dp0"
start "" ".venv\Scripts\pythonw.exe" -m sanae.app
