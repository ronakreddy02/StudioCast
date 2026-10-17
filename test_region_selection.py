import sys
from PySide6.QtWidgets import QApplication
from app.ui.region_selector import RegionSelector

app = QApplication(sys.argv)
selector = RegionSelector()

sys.exit(app.exec())