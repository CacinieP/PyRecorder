"""Application entry point (console script `pyrecorder`, `python -m pyrecorder`)."""
import sys

from pyrecorder.ui.main_window import run_app


def main():
    app, _window = run_app()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
