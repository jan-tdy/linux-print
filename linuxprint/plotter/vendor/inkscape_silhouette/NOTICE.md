# Attribution

`Graphtec.py` and `Transport.py` in this directory are vendored from the
[inkscape-silhouette](https://github.com/fablabnbg/inkscape-silhouette)
project, at commit `d8f067b2e649f32eb699bb1fa24385101956f149`
(`silhouette/Graphtec.py` and `silhouette/Transport.py`).

That project implements the actual on-wire Graphtec/Silhouette cutter
protocol (device tables, command bytes, media/force/speed tables, the
optical registration-mark search used for print-and-cut). Reimplementing
that from scratch would mean re-deriving years of reverse-engineering and
hardware quirks across many Silhouette/Graphtec models -- so this
integration uses the real thing instead, with credit and under its own
license.

**Copyright** (from the file headers, `Graphtec.py`):

- (c) 2013, 2014 jw@suse.de
- (c) 2016 juewei@fabmail.org
- (c) 2016 Alexander Wenger
- (c) 2017 Johann Gail
- inkscape-silhouette contributors (`Transport.py`)

**License:** GPL-2.0 (`Distribute under GPLv2 or ask.`, per the original
file headers). The full license text is in `LICENSE` in this directory,
copied from the [inkscape-silhouette
repository](https://github.com/fablabnbg/inkscape-silhouette/blob/main/LICENSE).

**Modifications** made for this integration are documented in comments at
the top of each modified file. Summary: `Graphtec.py`'s imports were
changed from an absolute `silhouette.*` package path to a relative import
so this copy can ship as its own small package, and `BLETransport.py` here
is a stub (this integration is USB-only) rather than the original's real
Bluetooth LE transport.

## Why this directory has a different license than the rest of the repo

The rest of `jan-tdy/linux-print` is MIT-licensed (see the repository's top
level `LICENSE`). GPL-2.0 is a copyleft license: a program that *links*
GPL-2.0 code into itself (e.g. imports it into the same running process)
is generally considered a combined work that must, as a whole, comply with
GPL-2.0 when distributed -- which would be inconsistent with the rest of
this MIT-licensed repository.

To avoid that, the GPL-2.0 driver in this directory is never imported by
`linuxprint`'s own (MIT) code. It is only ever run by `plot_cli.py`
(the sibling script one level up, also GPL-2.0 for the same reason -- it
directly imports `Graphtec.SilhouetteCameo`), which `linuxprint.plotter`
launches as a **separate subprocess** and talks to over stdin/stdout, the
same way `linuxprint/cups_cli.py` shells out to `lpadmin`/`lpstat` instead
of linking against libcups. Two independent programs communicating this way
is not the kind of "combined work" GPL-2.0's copyleft is about -- each
keeps its own license.

If you package or redistribute `jan-tdy/linux-print`, keep this directory's
files (and `plot_cli.py`) together with this notice and the GPL-2.0
`LICENSE` file.

## Also used by the Plotter tab

- [`svgelements`](https://github.com/meerk40t/svgelements) (MIT license) --
  SVG parsing and curve flattening for the "Load SVG" step. Used directly
  by `linuxprint.plotter.svg_import` (MIT code, same license as the rest of
  the app) -- it is a normal MIT dependency, not vendored here.
- The USB permission rule `assets/61-silhouette-cameo.rules` is adapted
  from inkscape-silhouette's `silhouette-udev.rules` (same repository and
  commit as above) -- trimmed to the device IDs this integration knows
  about; see the comment at the top of that file.
