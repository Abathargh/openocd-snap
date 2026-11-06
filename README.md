# openocd-snap

This is a packaging repo for the openocd snap. OpenOCD release lifecycle is
quite slow, so we pin to a specific upstream commit deemed stable enough and use
that as a source of truth.

Additionally, this snap supports STM and Renesas patches not yet included in
upstream but deemed necessary for hardware enablement of newer devices.

This is achieved through vendoring some patches which are stored under:
- `patches/stm/`, ported from STMicroelectronics `openocd-cubeide-r7` branch 
  of their fork.
- `patches/renesas/`, ported from `renesas-rz/rzg_openocd`.


Everything is compiled into one binary. Components `stm32` and `renesas` only 
carry target/board scripts; `snap/local/openocd-wrapper` adds them to the 
search path.

## udev rules

The snap cannot install custom udev rules so it is up to the user to perform
this last bit.

```cmdline
sudo cp udev/60-openocd.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules && sudo udevadm trigger
```
Then connect the USB plug: `sudo snap connect openocd:raw-usb`.

## License

GPL-2.0-or-later, same as OpenOCD. The snap ships OpenOCD's `COPYING` and 
`LICENSES/` under `usr/share/doc/openocd/`.

