@echo off
rem ============================================================
rem  BOE Analytics - one-click demo stack launcher
rem  Double-click this file. It opens 4 labeled server windows.
rem  Keep all 4 windows open for the demo. Close them to stop.
rem ============================================================

rem Clear Next.js's dev build cache first — stale caches cause the
rem "__webpack_modules__ / __webpack_require__" runtime errors. Rebuilding
rem takes a few extra seconds on first page load and guarantees a clean run.
if exist "C:\Cursor Projects\PDR\web\.next" rmdir /s /q "C:\Cursor Projects\PDR\web\.next"

start "API 8000 - website backend"            /d "C:\Cursor Projects\PDR\backend"     cmd /k ".venv\Scripts\activate.bat && uvicorn finclone.api.main:app --port 8000"
start "API 8443 - Excel add-in backend HTTPS" /d "C:\Cursor Projects\PDR\backend"     cmd /k ".venv\Scripts\activate.bat && uvicorn finclone.api.main:app --port 8443 --ssl-keyfile %USERPROFILE%\.office-addin-dev-certs\localhost.key --ssl-certfile %USERPROFILE%\.office-addin-dev-certs\localhost.crt"
start "WEB 3000 - website"                    /d "C:\Cursor Projects\PDR\web"         cmd /k "npm run dev"
start "ADDIN 3100 - add-in files HTTPS"       /d "C:\Cursor Projects\PDR\excel-addin" cmd /k "npm run dev"

echo.
echo  Four server windows are opening.
echo.
echo  NOTE: if any window shows "EADDRINUSE", that server was
echo  ALREADY running in another window - just close the new
echo  duplicate window. It is not an error.
echo.
echo  Wait ~20 seconds, then verify these in your browser:
echo    https://localhost:8443/health          (expect {"status":"ok"})
echo    https://localhost:3100/taskpane.html   (expect the task pane)
echo    http://localhost:3000                  (expect the website)
echo.
pause
