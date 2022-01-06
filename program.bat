@echo off
:: taskkill /F /IM putty.exe >NUL 2>&1
set /p RGB_ORDER="Enter RGB ORDER (RGB, BRG, etc.): "
set /p LED_COUNT="Enter LED COUNT: "
echo Available ports:
chgport
set /p SERIAL_PORT="Enter SERIAL PORT (ex. 'COM3'): "
echo %LED_COUNT% > micropython/LED_COUNT
echo %RGB_ORDER% > micropython/RGB_ORDER
cd ROM
call reset.bat %SERIAL_PORT%
echo Flash Complete!

:CHOICE
set /p OPEN_PUTTY="Do you want to open putty? (Y/N): "
if /I "%OPEN_PUTTY%" EQU "Y" goto :OPENPUTTY
if /I "%OPEN_PUTTY%" EQU "N" goto :LEAVE
goto :CHOICE

:OPENPUTTY
echo Note: You may have to press CTRL-D, CTRL-C, and or CTRL-B to allow access. You can also press the reset button the the ESP32
putty -serial "%SERIAL_PORT%" -sercfg 115200

:LEAVE
exit