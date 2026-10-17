from PySide6.QtWidgets import (QWidget,
                               QApplication)
from PySide6.QtCore import (Qt,
                            QPoint,
                            QRect,
                            Signal)
from PySide6.QtGui import(QPainter,
                          QPen,
                          QColor,QPainterPath)

class RegionSelector(QWidget):

    region_selected = Signal(dict)

    def __init__(self):
        super().__init__()

        self.start_point = QPoint()
        self.current_point = QPoint()

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint|
            Qt.WindowType.WindowStaysOnTopHint

        )
        self.setAttribute(
            Qt.WidgetAttribute.WA_TranslucentBackground
        )

        self.screen = QApplication.primaryScreen()
        self.screen_geometry = self.screen.geometry()
        self.setGeometry(self.screen_geometry)

        self.show()

    def mousePressEvent(self,event):
        self.start_point = event.position().toPoint()
        self.update()

    def mouseMoveEvent(self, event):
        self.current_point = event.position().toPoint()
        self.update()

    def mouseReleaseEvent(self, event):
        self.current_point = event.position().toPoint()
        self.update()

        rect = self.get_selection_rect()

        if rect.width() > 0 and rect.height() > 0:
            region = {
                "x": rect.x(),
                "y": rect.y(),
                "width": rect.width(),
                "height": rect.height()
            }

            self.region_selected.emit(region)
            self.close()

    def get_selection_rect (self):
        self.selection_rect = QRect(
            self.start_point,
            self.current_point
            ).normalized()

        return self.selection_rect

    def paintEvent(self, event):
        self.painter = QPainter(self)
        overlay_path = QPainterPath()
        overlay_path.addRect(self.rect())

        selection_path = QPainterPath()
        selection_path.addRect(self.get_selection_rect())

        outside_selection = overlay_path.subtracted(selection_path)

        self.painter.fillPath(
            outside_selection,
            QColor(0,0,0,120)
        )

        self.painter.setPen(QPen(Qt.GlobalColor.green,2))
        self.painter.drawRect(self.get_selection_rect())

        self.painter.end()




    