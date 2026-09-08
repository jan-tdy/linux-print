# Jadiv Print Center

A PyQt6 print manager for **Ubuntu / Kubuntu 24.04+** (and any modern
CUPS-based distro) that handles USB, network and remote-CUPS-server
printers with autodiscovery -- and, unlike the stock Linux print stack,
keeps working after a printer's IP address or port changes. It also has a
**Plotter tab** for Silhouette Cameo cutting plotters (USB, Cameo 4/5
family) -- SVG/PNG/PDF import, a manual drawing tool (freehand, a shape
catalog, and text), roll-fed vinyl support, project save/load, cut/pen, and
print-and-cut -- and a **Booklet tab** that turns a PDF into an A5 booklet
printed 2-up on A4 sheets, in the page order a saddle-stitch (center-fold,
stapled) booklet needs.

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
  - **Network (autodiscovery)** -- printers found via mDNS/DNS-SD (`dnssd://`)
    and other network devices CUPS can already see.
  - **Remote CUPS server** -- point it at a remote CUPS server
    (`host[:port]`) and browse the printers it shares.
- **Job queue** -- cancel, hold, resume, or move print jobs between printers.
- **Background self-healing** -- a watcher thread (also installable as a
  `systemd --user` service, so it runs even with no window open) keeps
  re-discovering printers and repairs device URIs that changed. See below
  for exactly what it can and can't fix.
- **Tray icon** -- quick access to the manager window and a desktop
  notification whenever a printer gets auto-repaired.
- **Booklet tab** -- turn a normal PDF into an A5 booklet imposed 2-up on
  A4 sheets, in saddle-stitch page order; export the imposed PDF or print
  it directly. See below.

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

   and logs exactly what it changed (visible in the "Log & settings"
   tab and in `~/.local/share/jadiv-print-center/logs/healer.log`). If it
   can't confidently match a drifted printer to a new address, it leaves
   the queue alone and just marks it "Unreachable" in the UI rather than
   guessing and repointing it at the wrong device.

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
  different color than red if you want it drawn, not cut. See "Getting an
  AI to draw the SVG for you" below for a ready-made prompt covering these
  conventions.
- **Load PNG/PDF** -- imports a raster image (a PDF's first page is
  rendered to an image) as the artwork to *print* during print-and-cut. A
  raster image has no vector paths of its own, so it's shown as a
  reference layer under the canvas -- draw the actual cut/pen lines by
  hand on top of it (see below) tracing the parts you want cut.
- **Manual drawing tool** -- draw cut or pen polylines directly on the
  canvas without needing an SVG at all: pick "Draw cut" or "Draw pen",
  click to place points, finish with a double-click or Enter, cancel with
  Escape. "Undo" undoes the last shape, "Clear drawing" clears everything
  hand-drawn. Hand-drawn shapes combine with anything imported from an SVG
  -- draw extra cut lines around an imported design, or start a job from
  nothing but freehand lines.
- **Shape catalog** -- pick Square, Circle, Rectangle or Triangle from the
  "Shape" dropdown and drag on the canvas to draw it at any size (square
  and circle keep a 1:1 ratio); switch back to "Freehand" for the
  click-by-click polyline tool above.
- **Text tool** -- type a string, set its height in mm, click "Add text
  (click on canvas)", then click where it should go. The text is converted
  to its actual glyph outlines (via Qt's own font rendering, flattened to
  polylines) before being added, so it becomes a normal cut/pen path like
  anything else here -- no font is needed on the cutter side, and inner
  contours (the hole in an "O") come through correctly.
- **Roll-fed vinyl** -- pick the `roll_vinyl` media preset to cut on a
  mat-less roll instead of a fixed sheet: set the roll's width, and the cut
  length is automatically fit to the actual design (plus a small margin)
  instead of guessing a fixed sheet height.
- **Save/open project** -- "Save project…" writes either a `.jpcp` (Jadiv
  Print Center Project) file -- a self-contained JSON snapshot of the
  cut/draw paths, tool settings, and an embedded copy of any loaded
  background image, so a session can be closed and reopened exactly as
  left -- or a plain `.svg` (cut paths in red, pen paths in black) if you'd
  rather hand the file to another tool. "Open project…" loads a `.jpcp`
  back.
- **Cut** / **Draw with pen** / **Cut + draw** -- send the cut paths, the
  pen paths, or both together in one job to the cutter. Force (blade
  pressure / pen pressure) and speed are adjustable; media presets cover
  A4, Letter, a few common Cameo cutting mats, and roll-fed vinyl (above).
  Every one of these (plus the registration-mark search checkbox, which
  now applies uniformly to all three, not just print-and-cut) shows a
  confirmation summarizing exactly what's about to be sent -- media, path
  counts, speed/pressure -- before anything physically happens, since a
  wrong setting wastes material or a blade pass.
- **Registration-mark preview** -- ticking "Use registration marks"
  overlays where the marks will actually print (in blue) directly on the
  canvas, so misalignment with the design is obvious before committing
  paper to it, not after. The mark layout automatically scales down to fit
  whatever is actually being printed (a small custom PNG, a roll-vinyl cut,
  a full sheet) instead of assuming a fixed page size that a smaller image
  can't hold.
- **Print** and **cutting are separate steps** -- "Print…" only sends the
  design (with registration marks composited on, if enabled) to a regular
  CUPS printer; "Cut" / "Draw with pen" / "Cut + draw" independently send
  the cutter job. Print once and cut multiple times, or re-cut a sheet
  without reprinting it, instead of always chaining print immediately into
  a single cut.
- A status line shows whether a Cameo is currently detected over USB
  (needs `libusb-1.0-0`, which Ubuntu ships by default).

## Booklet tab

Turns a normal, one-page-per-sheet PDF into an A5 booklet, imposed 2-up on
A4 sheets in saddle-stitch (center-fold, stapled) order.

- **Load PDF…** -- pick the source PDF. The tab shows how many A4 sheets
  the booklet will need (blank pages are padded on at the end if the page
  count isn't a multiple of 4).
- **Rendering resolution** -- the DPI each source page is rasterized at
  before being placed on its A5 half (higher = sharper but slower/larger).
- **Duplex printing** -- "Print booklet…" prints double-sided directly via
  CUPS. Which physical edge the printer's duplex unit flips around ("short
  edge" vs "long edge") depends on the printer/driver, and matters here:
  the wrong one prints the inside pages upside-down. **Short edge is the
  usual setting for these landscape A4 sheets** and is the default -- if a
  test booklet still comes out wrong on the inside, tick **"Rotate back
  sides 180°"** and reprint (or switch the dropdown to "Long edge"), rather
  than assuming one setting always works across every printer.
- **Export booklet PDF…** -- saves the imposed PDF instead of printing it
  directly, e.g. to print manually (odd/even pages separately) on a
  non-duplex printer, or from a different machine entirely.

**How to assemble it:** print double-sided, stack the printed sheets in
the order they come out of the printer, fold the whole stack in half at
once, and staple through the fold. Pages then read 1, 2, 3, ... in order.

**Honesty about testing:** the imposition math (page order, padding, A4/A5
sizing) is covered by automated tests, but which duplex "flip" setting a
given real printer actually needs hasn't been verified against physical
hardware in building this feature -- print a single 4-page test booklet
first and check the page order before running a full print job.

### Getting an AI to draw the SVG for you

If you don't want to hand-draw a design, most AI image/vector generators
can produce one -- but only if you tell them the exact conventions this
tool expects. Paste something like this into the prompt:

> Create an SVG file for cutting on a Silhouette Cameo cutting plotter.
> Requirements:
> - Use `stroke="#FF0000"` (pure red) for every line that should be
>   **cut** with the blade. Use any other clearly dark color (e.g. black
>   `#000000`) for lines that should only be **drawn** with a pen --
>   never use white, very pale, or near-white colors for any line, since
>   those won't be visible when checking the design.
> - Every shape must be an open or closed **path/line with a stroke**, not
>   a filled shape with no stroke -- the cutter follows stroke outlines,
>   it does not cut solid fills.
> - Use a reasonable stroke width (around 0.5-2 user units) -- a stroke
>   width of 0 or an extremely thin/thick value can confuse some SVG
>   viewers, though the cutter itself only follows the path's centerline.
> - Set an explicit `viewBox` and `width`/`height` in real physical units
>   (mm, cm or in) matching the design's intended physical size -- don't
>   leave the size ambiguous or purely in unitless pixels.
> - Keep the design flat (no nested transforms/groups with unusual scale
>   or rotation) and avoid text elements -- convert any text to outlined
>   paths first, since the cutter only understands paths, not fonts.

The Plotter tab's own convention (red = cut, anything else = draw) is
exactly what that prompt asks for, so an SVG produced this way should load
and classify correctly without any manual color editing.

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
line up. The manual line-drawing tool, shape catalog, text tool, PNG/PDF
import, project save/load, and registration-mark preview overlay are
covered by automated tests down to the data they produce (paths, composited
pixels, saved/reloaded project files), but the interactive canvas behavior
itself (mouse clicks and drags, live rubber-banding) has only been
exercised through direct calls to its internal handlers, not a real mouse
-- if a click, drag, or double-click doesn't register the way you expect on
your desktop, that's the part most likely to need a follow-up fix.

## Requirements

- Ubuntu/Kubuntu 24.04+ (or any Linux with CUPS -- `cups` + `cups-client`)
- Python 3.10+
- PyQt6
- `pyusb`, `svgelements` and `defusedxml` (only needed for the Plotter tab;
  printing works fine without them -- if they're missing, the Plotter tab
  shows a placeholder telling you what to install instead of the app
  failing to start)
- `Pillow` and `pypdfium2` (only needed for the Plotter tab's PNG/PDF
  import and print-and-cut with a raster image, and for the whole Booklet
  tab; SVG-based cut/draw/print-and-cut, and printer/queue management,
  work fine without them)

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
- [`pypdfium2`](https://github.com/pypdfium2-team/pypdfium2)
  (BSD-3-Clause/Apache-2.0, both permissive) renders a PDF's first page
  for the Plotter tab's "Load PNG/PDF" step. Deliberately *not* the more
  commonly used PyMuPDF for this: PyMuPDF is dual-licensed under AGPL-3.0
  or a paid Artifex commercial license, and unlike the vendored Graphtec
  driver above there's no subprocess boundary here to keep that separate
  from this MIT-licensed process, so a permissively-licensed alternative
  was used instead.
- [Pillow](https://python-pillow.org/) (MIT-CMU/PIL license, permissive)
  reads PNG DPI metadata and composites registration-mark squares onto a
  raster image for print-and-cut, used as a normal dependency.

## Published in Jadiv Code Master

This repository ships a `codemaster-metadata.json`, so it shows up
automatically in the [Jadiv Code Master](https://github.com/jan-tdy/codemaster)
app store (Code Master scans every `jan-tdy` repository for this file --
nothing needs to be added to the Code Master repository itself).

---

Made by JapySoft TDY · contact: j44soft@gmail.com
