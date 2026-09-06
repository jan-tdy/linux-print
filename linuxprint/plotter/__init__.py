"""Silhouette Cameo plotter support (USB, SVG import, cut/draw, print-and-cut).

MIT-licensed, same as the rest of linuxprint. The actual cutter protocol
lives in vendor/inkscape_silhouette/ (GPL-2.0, vendored from
fablabnbg/inkscape-silhouette) and runs only as a separate subprocess via
device_cli.py -- see vendor/inkscape_silhouette/NOTICE.md.
"""
