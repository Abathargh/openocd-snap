# openocd-snap - WIP

Packaging repo for the openocd snap. OpenOCD release lifecycle is quite slow, 
so we pin to a specific upstream commit deemed stable enough and use that as a 
source of truth.

Additionally, this snap supports STM and Renesas patches not yet included in
upstream but deemed necessary for hardware enablement of newer devices.

This is achieved through vendoring some patches which are stored under:
- `patches/stm/`, ported from STMicroelectronics `openocd-cubeide-r7` branch 
  of their fork.
- `patches/renesas/`, ported from `renesas-rz/rzg_openocd`.

Everything is compiled into one binary, with snap omponents `stm32` and 
`renesas` carrying target/board scripts.

## udev rules

The snap cannot install custom udev rules so it is up to the user to perform
this last bit.

```cmdline
sudo cp udev/60-openocd.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules && sudo udevadm trigger
```
Then connect the USB plug: `sudo snap connect openocd:raw-usb`.

## Arduino Ventuno Q

This snap also adds support for flashing the on-board STM32H5 MCU from the 
board's Linux SoC (bit-banged SWD over GPIO). Needs the `stm32` component and 
root (for now, or access to `/dev/gpiochip2`).

```cmdline
sudo snap install --classic openocd
sudo snap install openocd+stm32
sudo openocd -f board/arduino_ventuno_q.cfg \
  -c "set filename zephyr.elf" -f board/arduino_ventuno_q_flash_bootloader.cfg
```

With LLEXT sketches, `filename0` is the loader and `filename1` the sketch:

```cmdline
sudo openocd -f board/arduino_ventuno_q.cfg \
  -c "set filename0 loader.elf" -c "set filename1 sketch.bin" \
  -f board/arduino_ventuno_q_flash_sketch.cfg
```

## License

GPL-2.0-or-later, same as OpenOCD. The snap ships OpenOCD's `COPYING` and 
`LICENSES/` under `usr/share/doc/openocd/`.

