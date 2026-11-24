@echo off
rem Starts LightDeck without a console window.
rem Close SignalRGB first - only one RGB app can control the lights at a time.
start "" pythonw "%~dp0app.py"
