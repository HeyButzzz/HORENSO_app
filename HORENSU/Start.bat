@echo off
setlocal EnableExtensions EnableDelayedExpansion
title HORENSO - Problem Card System
color 0B

REM ===========================================================================
REM  HORENSO - one-click launcher
REM
REM  Double-click this file to run the web app. It will, in order:
REM    1. find a Python interpreter
REM    2. install the required packages the first time (or if any are missing)
REM    3. create the database and demo data on first run
REM    4. start the server and open it in your browser
REM
REM  Close this window (or press Ctrl+C) to stop the server.
REM ===========================================================================

cd /d "%~dp0"

set "APP_HOST=10.10.20.19"
set "APP_PORT=8080"

echo.
echo  ============================================================
echo    HORENSO - Problem Card System
echo  ============================================================
echo.

REM --------------------------------------------------- 1. find Python ------
set "PY="
where py >nul 2>&1 && set "PY=py -3"
if not defined PY (
  where python >nul 2>&1 && set "PY=python"
)
if not defined PY (
  echo  [X] Python tidak ditemukan di komputer ini.
  echo.
  echo      Silakan install Python 3 terlebih dahulu dari:
  echo        https://www.python.org/downloads/
  echo      Saat instalasi, centang "Add Python to PATH".
  echo.
  goto :fail
)

%PY% --version >nul 2>&1
if errorlevel 1 (
  echo  [X] Python ditemukan tetapi tidak dapat dijalankan.
  goto :fail
)
for /f "delims=" %%v in ('%PY% --version 2^>^&1') do set "PYVER=%%v"
echo  [1/4] Python siap        : !PYVER!

REM ------------------------------------------- 2. dependencies -------------
%PY% -c "import flask, flask_sqlalchemy, flask_login, flask_wtf" >nul 2>&1
if errorlevel 1 (
  echo  [2/4] Menginstal dependencies ^(sekali saja, mohon tunggu^)...
  %PY% -m pip install --disable-pip-version-check -q -r requirements.txt
  if errorlevel 1 (
    echo        Percobaan pertama gagal, mencoba dengan --user ...
    %PY% -m pip install --disable-pip-version-check -q --user -r requirements.txt
    if errorlevel 1 (
      echo.
      echo  [X] Gagal menginstal dependencies.
      echo      Coba jalankan manual di Command Prompt:
      echo        %PY% -m pip install -r requirements.txt
      goto :fail
    )
  )
  %PY% -c "import flask, flask_sqlalchemy, flask_login, flask_wtf" >nul 2>&1
  if errorlevel 1 (
    echo  [X] Dependencies masih belum lengkap setelah instalasi.
    goto :fail
  )
  echo        Dependencies terpasang.
) else (
  echo  [2/4] Dependencies      : lengkap
)

REM ------------------------------------------- 3. database -----------------
if not exist "instance" mkdir "instance" >nul 2>&1
if not exist "instance\horensu.db" (
  echo  [3/4] Menyiapkan database ^& data demo ^(pertama kali^)...
  %PY% seed.py
  if errorlevel 1 (
    echo  [X] Gagal menyiapkan database.
    goto :fail
  )
) else (
  echo  [3/4] Database          : siap
)

REM ------------------------------------------- 4. run ----------------------
REM Always bind every interface: the app is then reachable both on the lab IP
REM and on localhost, and it starts even when this machine is not on that
REM network. Only the address we open in the browser depends on the IP check.
set "HORENSO_HOST=0.0.0.0"
set "HORENSO_PORT=%APP_PORT%"

set "URL=http://127.0.0.1:%APP_PORT%"
%PY% -c "import socket,sys;a=set(i[4][0] for i in socket.getaddrinfo(socket.gethostname(),None,socket.AF_INET));sys.exit(0 if '%APP_HOST%' in a else 1)" >nul 2>&1
if errorlevel 1 (
  echo  [!] IP %APP_HOST% tidak aktif di komputer ini - memakai alamat lokal.
) else (
  set "URL=http://%APP_HOST%:%APP_PORT%"
)

echo  [4/4] Menjalankan server : !URL!
echo.
echo  ------------------------------------------------------------
echo    Buka di browser : !URL!
echo    Hentikan server : tutup jendela ini atau tekan Ctrl+C
echo  ------------------------------------------------------------
echo.

REM Open the browser a few seconds later, once the server has bound its port.
start "" /b powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 3; Start-Process '!URL!'" >nul 2>&1

%PY% run.py

echo.
echo  Server berhenti.
goto :done

:fail
echo.
echo  ============================================================
echo    Gagal menjalankan HORENSO. Lihat pesan di atas.
echo  ============================================================
echo.
pause
exit /b 1

:done
echo.
pause
exit /b 0
