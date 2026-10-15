"""Application entry point."""
from __future__ import annotations

import os
import sys
from pathlib import Path


def main(argv=None) -> int:
    argv = list(sys.argv if argv is None else argv)
    args = [a for a in argv[1:] if not a.startswith("-")]
    if "--version" in argv:
        from pdfbuilder import __version__
        print(f"PDF Builder {__version__}")
        return 0
    if "--help" in argv or "-h" in argv:
        print(__doc__ or "")
        print("Usage: pdf-builder [FILE...]\n\n"
              "  --list-tools   print every available tool\n"
              "  --check        report optional components\n"
              "  --version      print the version")
        return 0

    from pdfbuilder import registry
    registry.load_all()

    if "--list-tools" in argv:
        from pdfbuilder.registry import CATEGORIES
        for key, label in CATEGORIES:
            tools = registry.by_category(key)
            print(f"\n{label}  ({len(tools)})")
            for t in tools:
                print(f"  {t.id:22s} {t.name}")
        print(f"\n{len(registry.REGISTRY)} tools in total.")
        return 0

    if "--check" in argv:
        from pdfbuilder import deps
        print("Optional components:")
        for name, ok, pkg, what in deps.report():
            print(f"  {name:12s} {'installed' if ok else 'MISSING  '}"
                  f"   {what}"
                  + ("" if ok else f"   (sudo apt install {pkg})"))
        return 0

    # Qt needs a display; fail with a clear message rather than a traceback
    if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        print("PDF Builder needs a graphical session (no DISPLAY or "
              "WAYLAND_DISPLAY found).\n"
              "Try the command-line options instead: --list-tools, --check",
              file=sys.stderr)
        return 2

    from PySide6 import QtWidgets

    from pdfbuilder.ui.main_window import MainWindow

    app = QtWidgets.QApplication(argv)
    app.setApplicationName("PDF Builder")
    app.setApplicationDisplayName("PDF Builder")
    app.setDesktopFileName("pdf-builder")
    app.setStyle("Fusion")
    from pdfbuilder.ui import icons
    app.setWindowIcon(icons.app_icon())

    files = [Path(a) for a in args if Path(a).exists()]
    win = MainWindow(files)
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
