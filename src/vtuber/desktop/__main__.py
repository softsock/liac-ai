"""Run with python -m vtuber.desktop from any working directory."""
import argparse
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description='LIAC desktop chat and runtime inspector')
    default_root = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path.cwd()
    parser.add_argument('--root', type=Path, default=default_root, help='project root for private local data')
    parser.add_argument('--replay',type=Path,help='open recorded history without starting providers')
    args = parser.parse_args()
    try:
        from PySide6.QtWidgets import QApplication
        from vtuber.desktop.window import MainWindow
    except ImportError as error:
        parser.exit(1, f'Desktop dependency unavailable ({error}). Install: python -m pip install -e ".[desktop,nemotron]"\n')
    app = QApplication(sys.argv[:1])
    app.setApplicationName('LIAC Conversation Lab')
    window = MainWindow(args.root)
    window.show()
    if args.replay:
        window.load_history(args.replay)
    code = app.exec()
    from PySide6.QtCore import QCoreApplication, QEvent
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    sys.exit(code)


if __name__ == '__main__':
    main()
