@echo off
set "INSTALL=%USERPROFILE%\.xelis-vault"
"%INSTALL%\venv\Scripts\python.exe" "%INSTALL%\src\scripts\xvault.py" %*
