@echo off
setlocal
pushd "%~dp0hub" || exit /b 1
call npm.cmd run build
if errorlevel 1 (
    popd
    exit /b 1
)
call npm.cmd start
set "hub_exit=%ERRORLEVEL%"
popd
exit /b %hub_exit%
