chgport
set /p PORT=Enter PORT: 
ampy --port %PORT% put micropython /
echo Ready.
putty -serial "%PORT%" -sercfg 115200
pause