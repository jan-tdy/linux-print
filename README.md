# Jadiv Print Center

A PyQt6 print manager for **Ubuntu / Kubuntu 24.04+** (and any modern
CUPS-based distro) that handles USB, network and remote-CUPS-server
printers with autodiscovery -- and, unlike the stock Linux print stack,
keeps working after a printer's IP address or port changes. It also has a
**Plotter tab** for Silhouette Cameo cutting plotters (USB, Cameo 4/5
family) -- SVG import, cut/pen, and print-and-cut.

Made by JapySoft TDY.

---

## Why this exists

The usual complaint with Linux printing isn't CUPS itself -- it's that a
printer added once (by IP, or picked from an autodiscovery list at some
point in time) silently breaks the moment its network address changes
(DHCP lease renewal, router reboot, printer moved to another switch port,
...). Nothing tells you why; the queue just goes to "stopped" and printing
"randomly" stops working until someone re-adds the printer by hand.

Jadiv Print Center is a normal front-end for CUPS (it doesn't replace CUPS,
which remains the actual print spooler), plus a background watcher that
keeps re-discovering printers and fixes their CUPS device URI when it
drifts.

## Features

- **Printers tab** -- list every CUPS printer, its live status (ready /
  printing / stopped / unreachable), connection type and device URI; add,
  remove, enable/disable, set default.
- **Add printer wizard** -- three tabs:
  - **USB** -- printers `lpinfo` sees plugged in.
  - **Sieť (autodiscovery)** -- printers found via mDNS/DNS-SD (`dnssd://`)
    and other network devices CUPS can already see.
  - **Vzdialený CUPS server** -- point it at a remote CUPS server
    (`host[:port]`) and browse the printers it shares.
- **Front úloh (job queue)** -- cancel, hold, resume, or move print jobs
  between printers.
- **Background self-healing** -- a watcher thread (also installable as a
  `systemd --user` service, so it runs even with no window open) keeps
  re-discovering printers and repairs device URIs that changed. See below
  for exactly what it can and can't fix.
- **Tray icon** -- quick access to the manager window and a desktop
  notification whenever a printer gets auto-repaired.

## How the self-healing actually works

There is no single trick that makes every printer immune to IP changes, so
the tool combines two strategies, and is explicit in the UI/log about which
one applies to a given printer:

1. **Prefer self-healing addresses when adding a printer.** When a network
   printer supports mDNS/Bonjour (almost all modern printers do), CUPS
   itself can already see it as a `dnssd://PrinterName._ipp._tcp.local/...`
   device. The Add Printer wizard always prefers this form over a raw IP.
   A `dnssd://` (or `usb://`) device URI is re-resolved by CUPS on every
   single print job, so a DHCP lease change or a different USB port never
   breaks it in the first place -- there is nothing to "heal".

2. **Best-effort repair for IP-pinned printers.** Some printers (or queues
   that pre-date this tool, or printers without mDNS) end up with a device
   URI that pins a raw IP, e.g. `ipp://192.168.1.50:631/ipp/print` or
   `socket://192.168.1.50:9100`. For these, Jadiv Print Center records an
   "identity" for the printer at add-time (its scheme + resource path) and,
   on every watcher cycle, re-runs discovery and compares. If it finds the
   *same* device now advertising a *different* IP/port, it repairs the CUPS
   queue with:

   ```
   lpadmin -p <name> -v <new-uri>
   ```

   and logs exactly what it changed (visible in the "Denník a nastavenia"
   tab and in `~/.local/share/jadiv-print-center/logs/healer.log`). If it
   can't confidently match a drifted printer to a new address, it leaves
   the queue alone and just marks it "Nedostupná" (unreachable) in the UI
   rather than guessing and repointing it at the wrong device.

Either way, opening the app (or letting the background service run) is
what makes this different from the vanilla CUPS experience: you get
visibility into *why* a printer stopped working, and automatic recovery
for the common case.

## Plotter tab (Silhouette Cameo)

USB-only for now. Targets the Cameo 4/5 family: Cameo 4 / 4 Plus / 4 Pro,
Cameo 5 / 5 Plus / 5 Alpha / 5 Alpha Plus, Cameo Pro Mk II (the actual
device table -- see Credits below -- also lists Portrait 2/3/4 and older
Cameo/SD/Craft Robo models, which should work too even though this tab's
own quick "is anything plugged in" status check doesn't name them).

- **Load SVG** -- parses paths, shapes and curves (flattened to line
  segments) via `svgelements`. Convention: a **red stroke** (`#ff0000`)
  means *cut with the blade*; anything else (including a shape with no
  stroke at all) means *draw with the pen*. Draw a guide line in a
  different color than red if you want it drawn, not cut.
- **Cut** / **Draw with pen** -- send the cut or pen paths to the cutter.
  Force (blade pressure / pen pressure) and speed are adjustable; media
  presets cover A4, Letter, and a few common Cameo cutting mats.
- **Print and cut** -- prints the design plus 3 registration squares to a
  CUPS printer of your choice, then (once you've placed the printed sheet
  on the cutting mat) sends the cut with the cutter's optical
  registration-mark search enabled, so the cut lines up with what was
  printed even if the sheet isn't perfectly aligned by hand.
- A status line shows whether a Cameo is currently detected over USB
  (needs `libusb-1.0-0`, which Ubuntu ships by default).

**USB permissions:** by default only root can open the raw USB device.
Install the udev rule once so your own user account can:

```bash
sudo ./install-plotter-udev.sh             # install
sudo ./install-plotter-udev.sh --uninstall # remove
```

Then unplug and replug the Cameo (or reboot).

**Honesty about testing:** the SVG import, job building, and the whole
software pipeline down to the real cutter-protocol driver are covered by
this repo's automated tests (run in a `dry_run` mode the driver itself
provides, which still exercises real code, just without touching
hardware) -- but none of it has been run against a *physical* Cameo 5 in
building this feature (no device was available). The print-and-cut
registration-mark search in particular needs the cutter's own optical
sensor to actually respond; expect to do a first calibration run and check
the underlying driver's own documentation
(https://github.com/fablabnbg/inkscape-silhouette) if something doesn't
line up.

## Requirements

- Ubuntu/Kubuntu 24.04+ (or any Linux with CUPS -- `cups` + `cups-client`)
- Python 3.10+
- PyQt6
- `pyusb` and `svgelements` (only needed for the Plotter tab; printing
  works fine without them)

Install the Python dependency:

```bash
python3 -m pip install --user -r requirements.txt
# If pip refuses with "externally-managed-environment" (Debian/Ubuntu/Arch):
python3 -m pip install --user --break-system-packages -r requirements.txt
# or, via the distro package manager instead of pip:
sudo apt install python3-pyqt6
```

Make sure CUPS itself is installed:

```bash
sudo apt install cups cups-client
```

## Running

```bash
python3 jadiv_print_center.py
```

### Desktop launcher

```bash
./install-launcher.sh             # install
./install-launcher.sh --uninstall # remove
```

Installs `assets/jadiv-print-center.desktop` into
`~/.local/share/applications/` (with the repo path filled in) and the icon
into `~/.local/share/icons/hicolor/scalable/apps/`. Look for **Jadiv Print
Center** in your application menu.

### Background self-healing service (recommended)

```bash
./install-service.sh             # install, enable and start
./install-service.sh --uninstall # stop, disable and remove
```

Installs a `systemd --user` unit
(`~/.config/systemd/user/jadiv-print-center-daemon.service`) that runs
`jadiv_print_center.py --daemon` (tray icon only, no window) so autodiscovery
and self-healing keep running even when the manager window is closed, and
across logout/login. Check it any time with:

```bash
systemctl --user status jadiv-print-center-daemon.service
```

Launching the app normally afterwards (from the app menu, from a terminal,
or from Code Master) doesn't start a second watcher -- it just raises the
existing window, since the daemon and the GUI are the same single-instance
process.

Jadiv Print Center keeps its state in:

| Path | Purpose |
|------|---------|
| `~/.config/jadiv-print-center/settings.json`          | check interval, self-healing on/off, notifications |
| `~/.local/share/jadiv-print-center/printers.json`     | recorded identity of each installed printer (for the healer) |
| `~/.local/share/jadiv-print-center/logs/healer.log`   | log of every automatic repair |
| `~/.config/systemd/user/jadiv-print-center-daemon.service` | the background service unit |
| `~/.local/share/applications/jadiv-print-center.desktop`   | the application menu launcher |

## Development

```bash
python3 -m pip install --user -r requirements-dev.txt
python3 -m pytest
```

The CUPS-facing modules (`linuxprint/cups_cli.py`, `linuxprint/discovery.py`,
`linuxprint/healer.py`) separate "parse this command's output" and "decide
what to repair" (pure functions) from "actually run the command"
(subprocess calls), so the parsing and self-healing decision logic is fully
unit-tested without needing a real CUPS install -- see `tests/`.

## Credits & third-party licenses

This repository is MIT-licensed (see `LICENSE`), with one exception:

- **`linuxprint/plotter/vendor/inkscape_silhouette/`** (`Graphtec.py`,
  `Transport.py`) is vendored, near-verbatim, from
  [fablabnbg/inkscape-silhouette](https://github.com/fablabnbg/inkscape-silhouette)
  (commit `d8f067b2e649f32eb699bb1fa24385101956f149`) -- the real Graphtec/
  Silhouette cutter protocol (device tables, command bytes, media/force/
  speed tables, optical registration-mark search), reused instead of
  reimplementing years of hardware reverse-engineering from scratch, as
  its authors intended when they released it. **That directory, and
  `linuxprint/plotter/vendor/plot_cli.py` which runs it, are licensed
  under GPL-2.0** (see the `LICENSE` file inside that directory), not MIT --
  copyright (c) 2013-2017 jw@suse.de, juewei@fabmail.org, Alexander Wenger,
  Johann Gail, and inkscape-silhouette contributors. Full attribution and
  an explanation of why this one piece is GPL-2.0 while the rest of the
  app stays MIT (short version: it only ever runs as its own subprocess,
  never imported into the main app's process) is in
  `linuxprint/plotter/vendor/inkscape_silhouette/NOTICE.md`.
- `assets/61-silhouette-cameo.rules` is adapted (trimmed to the Cameo 4/5
  family) from the same project's `silhouette-udev.rules`.
- [`svgelements`](https://github.com/meerk40t/svgelements) (MIT license,
  by Tatarize) does the SVG parsing and curve flattening for the Plotter
  tab's "Load SVG" step -- used as a normal MIT dependency, not vendored.

## Published in Jadiv Code Master

This repository ships a `codemaster-metadata.json`, so it shows up
automatically in the [Jadiv Code Master](https://github.com/jan-tdy/codemaster)
app store (Code Master scans every `jan-tdy` repository for this file --
nothing needs to be added to the Code Master repository itself).

---

Made by JapySoft TDY · contact: j44soft@gmail.com
