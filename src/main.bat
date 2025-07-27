set LOGFILE=batch.log
call :LOG > %LOGFILE%
exit /B

:LOG
python main.py %1
