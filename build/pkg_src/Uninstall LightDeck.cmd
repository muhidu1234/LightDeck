@echo off
rem Double-click to remove LightDeck and its shortcuts.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup\uninstall.ps1"
