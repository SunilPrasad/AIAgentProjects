import os

# Run Qt without opening real windows during tests.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session", autouse=True)
def qt_app():
    return QApplication.instance() or QApplication([])
