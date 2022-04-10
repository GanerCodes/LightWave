# Make sure to install this specific branch of esptool https://github.com/m-rossi/reedsolomon/tree/fix-cythonize-when-c-file-present
# Also fix any paths because there's some weird stuff that happens

DEVICE="/dev/ttyUSB0"

cd ./ROM
sudo python -m esptool --chip esp32 -p ${DEVICE} erase_flash
sudo python -m esptool -p ${DEVICE} -b 460800 --before default_reset --after hard_reset write_flash --flash_mode dio --flash_size detect --flash_freq 40m 0x1000 bootloader.bin 0x8000 partition-table.bin 0x10000 micropython.bin
cd ..
echo No idea why this is the part that often takes the longest...
sudo python /root/.local/bin/ampy --port ${DEVICE} put micropython /
echo Done, press 'ctrl+d' in screen to reboot
sudo screen ${DEVICE} 115200