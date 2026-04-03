@echo off
setlocal

set "ROOT=%~dp0"
cd /d "%ROOT%"

where git >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Git was not found in PATH.
  pause
  exit /b 1
)

git rev-parse --is-inside-work-tree >nul 2>nul
if errorlevel 1 (
  echo [ERROR] This folder is not a Git repository.
  pause
  exit /b 1
)

echo [1/3] Staging all changes...
git add -A
if errorlevel 1 (
  echo [ERROR] Failed to stage changes.
  pause
  exit /b 1
)

echo [2/3] Creating commit with message "AI"...
git commit -m "AI" >nul 2>nul
if errorlevel 1 (
  echo [INFO] No new commit created. (No changes or commit blocked.)
) else (
  echo [OK] Commit created.
)

echo [3/3] Pushing to remote...
git push
if errorlevel 1 (
  echo [ERROR] Push failed. Check remote/auth/branch settings.
  pause
  exit /b 1
)

echo [OK] Push complete.
exit /b 0
