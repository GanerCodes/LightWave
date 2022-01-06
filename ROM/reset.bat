call erase.bat %1
echo.
echo.
echo FLASH ERASE COMPLETE
echo.
echo.
call load.bat %1
echo.
echo.
echo BOOT LOAD COMPLETE
echo.
echo.
call compile.bat %1
echo.
echo.
echo FILE TRANSFER COMPLETE
echo.
echo.