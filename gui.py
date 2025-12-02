from __future__ import annotations

from pathlib import Path
from typing import Optional

import pandas as pd
from PyQt5.QtCore import QItemSelection, QModelIndex, Qt
from PyQt5.QtGui import QColor, QBrush
from PyQt5.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStatusBar,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from course_dock import CourseInfoDock
from data_model import CellDescriptor, CourseDataModel, MatrixData
from student_dock import StudentInfoDock


class MatrixTableModel:
    """Qt table model adapter for the matrix data."""

    def __init__(self, data_model: CourseDataModel) -> None:
        from PyQt5.QtCore import QAbstractTableModel

        class _Model(QAbstractTableModel):
            def __init__(self, outer: "MatrixTableModel") -> None:
                super().__init__()
                self._outer = outer

            # Qt API -----------------------------------------------------
            def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # type: ignore[override]
                if parent.isValid():
                    return 0
                return len(self._outer._matrix.students)

            def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # type: ignore[override]
                if parent.isValid():
                    return 0
                return len(self._outer._matrix.courses)

            def data(self, index: QModelIndex, role: int = Qt.DisplayRole):  # type: ignore[override]
                if not index.isValid():
                    return None
                cell = self._outer._matrix.cell_lookup.get((index.row(), index.column()))
                if role == Qt.DisplayRole and cell is not None:
                    if cell.completion_date is not None and not pd.isna(cell.completion_date):
                        return pd.Timestamp(cell.completion_date).strftime("%Y-%m-%d")
                    return ""
                if role == Qt.BackgroundRole:
                    return self._outer._background_brush(cell)
                if role == Qt.ToolTipRole and cell is not None:
                    if cell.completion_date is not None:
                        timestamp = pd.Timestamp(cell.completion_date)
                        return f"Completed on {timestamp:%Y-%m-%d}"
                    return "No completion date recorded"
                return None

            def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole):  # type: ignore[override]
                if role != Qt.DisplayRole:
                    return None
                if orientation == Qt.Horizontal:
                    if 0 <= section < len(self._outer._matrix.courses):
                        return self._outer._matrix.courses[section].label
                else:
                    if 0 <= section < len(self._outer._matrix.students):
                        return self._outer._matrix.students[section].label
                return None

            def flags(self, index: QModelIndex) -> Qt.ItemFlags:  # type: ignore[override]
                if not index.isValid():
                    return Qt.NoItemFlags
                return Qt.ItemIsEnabled | Qt.ItemIsSelectable

        self._data_model = data_model
        self._matrix: MatrixData = MatrixData([], [], {})
        self._qt_model = _Model(self)

    # Public API --------------------------------------------------------
    def qt_model(self):
        return self._qt_model

    def update_matrix(self, matrix: MatrixData) -> None:
        self._qt_model.beginResetModel()
        self._matrix = matrix
        self._qt_model.endResetModel()

    # Helpers -----------------------------------------------------------
    @staticmethod
    def _background_brush(cell: Optional[CellDescriptor]) -> Optional[QBrush]:
        if cell is None or cell.completion_date is None or pd.isna(cell.completion_date):
            return QBrush(QColor(224, 224, 224))

        completion = pd.Timestamp(cell.completion_date).normalize()
        today = pd.Timestamp.today().normalize()
        days_ago = max(0, int((today - completion).days))
        if days_ago <= 30:
            color = QColor(144, 238, 144)  # light green
        elif days_ago <= 180:
            color = QColor(255, 255, 153)  # light yellow
        elif days_ago <= 365:
            color = QColor(255, 204, 153)  # light orange
        else:
            color = QColor(255, 160, 160)  # light red
        return QBrush(color)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Course Matrix")
        self.resize(1200, 800)

        self.data_model = CourseDataModel()
        self.table_model = MatrixTableModel(self.data_model)

        self._create_ui()
        self._create_docks()

    # UI setup ----------------------------------------------------------
    def _create_ui(self) -> None:
        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)

        layout = QVBoxLayout(central_widget)
        button_bar = QHBoxLayout()

        self.students_button = QPushButton("Load students", self)
        self.students_button.clicked.connect(self.on_load_students)
        button_bar.addWidget(self.students_button)

        self.courses_button = QPushButton("Load courses", self)
        self.courses_button.clicked.connect(self.on_load_courses)
        button_bar.addWidget(self.courses_button)

        button_bar.addStretch(1)
        layout.addLayout(button_bar)

        self.table_view = QTableView(self)
        self.table_view.setModel(self.table_model.qt_model())
        self.table_view.setSelectionMode(QTableView.SingleSelection)
        self.table_view.setSelectionBehavior(QTableView.SelectItems)
        self.table_view.horizontalHeader().setStretchLastSection(True)
        self.table_view.verticalHeader().setDefaultSectionSize(28)
        self.table_view.selectionModel().selectionChanged.connect(self.on_selection_changed)
        layout.addWidget(self.table_view)

        status_bar = QStatusBar(self)
        self.setStatusBar(status_bar)
        self.status_label = QLabel("Load student and course files to begin.")
        status_bar.addPermanentWidget(self.status_label)

    def _create_docks(self) -> None:
        self.student_dock = StudentInfoDock(self)
        self.addDockWidget(Qt.RightDockWidgetArea, self.student_dock)

        self.course_dock = CourseInfoDock(self)
        self.addDockWidget(Qt.RightDockWidgetArea, self.course_dock)

    # Event handlers ----------------------------------------------------
    def on_load_students(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select student Excel file",
            str(Path.home()),
            "Excel files (*.xlsx *.xls);;All files (*)",
        )
        if not file_path:
            return
        try:
            self.data_model.load_students(file_path)
            self.status_label.setText(f"Loaded students from {Path(file_path).name}")
            self._rebuild_matrix()
        except Exception as exc:  # pragma: no cover - UI feedback
            self._show_error("Unable to load students", str(exc))

    def on_load_courses(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select courses HDF5 file",
            str(Path.home()),
            "HDF5 files (*.h5 *.hdf5);;All files (*)",
        )
        if not file_path:
            return
        try:
            self.data_model.load_courses(file_path)
            self.status_label.setText(f"Loaded courses from {Path(file_path).name}")
            self._rebuild_matrix()
        except Exception as exc:  # pragma: no cover - UI feedback
            self._show_error("Unable to load courses", str(exc))

    def on_selection_changed(self, selected: QItemSelection, _: QItemSelection) -> None:
        if selected.indexes():
            index = selected.indexes()[0]
            cell = self.table_model._matrix.cell_lookup.get((index.row(), index.column()))
            if cell is None:
                self.student_dock.clear()
                self.course_dock.clear()
            else:
                self.student_dock.show_student_rows(cell.student_rows)
                if cell.course.course_row is not None:
                    self.course_dock.show_course(cell.course.course_row)
                else:
                    self.course_dock.clear()
        else:
            self.student_dock.clear()
            self.course_dock.clear()

    # Helpers -----------------------------------------------------------
    def _rebuild_matrix(self) -> None:
        matrix = self.data_model.build_matrix()
        self.table_model.update_matrix(matrix)
        self.table_view.clearSelection()
        self.table_view.resizeColumnsToContents()
        self.table_view.resizeRowsToContents()
        self.student_dock.clear()
        self.course_dock.clear()
        if matrix.is_empty:
            self.status_label.setText("Matrix is empty. Ensure both datasets overlap.")
        else:
            self.status_label.setText(
                f"Showing {len(matrix.students)} students x {len(matrix.courses)} courses"
            )

    def _show_error(self, title: str, message: str) -> None:
        QMessageBox.critical(self, title, message)


def run() -> None:
    import sys

    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    run()