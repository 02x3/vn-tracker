@echo off
rem Starts the VN Character Tracker overlay without a console window.
rem Uses meikipop's Python so the tracker can OCR with meikiocr; falls back to pythonw on PATH.
rem Set VN_TRACKER_PYTHON to a pythonw.exe to override.
set "PYW=%VN_TRACKER_PYTHON%"
if not defined PYW set "PYW=%USERPROFILE%\meikipop\meikipop\.venv\Scripts\pythonw.exe"
if not exist "%PYW%" set "PYW=%USERPROFILE%\meikipop\.venv\Scripts\pythonw.exe"
if not exist "%PYW%" set "PYW=pythonw"
start "" "%PYW%" "%~dp0tracker.py" %*
