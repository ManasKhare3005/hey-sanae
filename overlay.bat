@echo off
rem Desktop overlay for Sanae: start/stop, push-to-talk, chats, memories, due today.
cd /d "%~dp0"
start "" ".venv\Scripts\pythonw.exe" -m sanae.overlay
