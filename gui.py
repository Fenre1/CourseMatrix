from __future__ import annotations

from pathlib import Path
from typing import Optional

import pandas as pd
from PyQt5.QtCore import QEvent, QItemSelection, QModelIndex, Qt
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
    QHeaderView,
)

from course_dock import CourseInfoDock
from data_model import CellDescriptor, CourseDataModel, MatrixData
from filter_dialog import FilterDialog
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

        self.filter_button = QPushButton("Student Filters…", self)
        self.filter_button.clicked.connect(self.on_open_filters)
        button_bar.addWidget(self.filter_button)

        self.zoom_out_button = QPushButton("Zoom -", self)
        self.zoom_out_button.clicked.connect(self.on_zoom_out)
        button_bar.addWidget(self.zoom_out_button)

        self.zoom_in_button = QPushButton("Zoom +", self)
        self.zoom_in_button.clicked.connect(self.on_zoom_in)
        button_bar.addWidget(self.zoom_in_button)

        self.zoom_label = QLabel("100%", self)
        button_bar.addWidget(self.zoom_label)

        button_bar.addStretch(1)
        layout.addLayout(button_bar)

        self.table_view = QTableView(self)
        self.table_view.setModel(self.table_model.qt_model())
        self.table_view.setSelectionMode(QTableView.SingleSelection)
        self.table_view.setSelectionBehavior(QTableView.SelectItems)
        
        # --- CRITICAL FIX START ---
        # Allow headers to shrink to 0 pixels (removes the ~20px limit)
        self.table_view.verticalHeader().setMinimumSectionSize(0)
        self.table_view.horizontalHeader().setMinimumSectionSize(0)
        # --- CRITICAL FIX END ---

        self.table_view.horizontalHeader().setStretchLastSection(True)
        self.table_view.verticalHeader().setDefaultSectionSize(28)
        self.table_view.selectionModel().selectionChanged.connect(self.on_selection_changed)
        self.table_view.viewport().installEventFilter(self)
        self.table_view.installEventFilter(self)
        self._base_column_widths: list[int] = []
        layout.addWidget(self.table_view)

        self._zoom_factor = 1.0
        self._min_zoom_factor = 0.5
        self._max_zoom_factor = 4.0
        self._ABSOLUTE_MIN_ZOOM = 0.0001  # Allow extremely small zoom
        self._base_font_size = self.table_view.font().pointSizeF()
        self._base_row_height = self.table_view.verticalHeader().defaultSectionSize()
        self._apply_zoom()

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

    def on_open_filters(self) -> None:
        if self.data_model.students_df is None:
            self._show_error("Load students first", "Please load a student Excel file before filtering.")
            return

        columns, values_by_column = self._gather_filter_metadata()
        dialog = FilterDialog(columns, values_by_column, self.data_model.filters, self)
        if dialog.exec_():
            self.data_model.set_filters(dialog.filters())
            self._rebuild_matrix()

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

    def on_zoom_in(self) -> None:
        self._adjust_zoom(0.1)

    def on_zoom_out(self) -> None:
        self._adjust_zoom(-0.1)


    # Helpers -----------------------------------------------------------
    def _rebuild_matrix(self) -> None:
        matrix = self.data_model.build_matrix()
        self.table_model.update_matrix(matrix)
        self.table_view.clearSelection()
        self.table_view.resizeColumnsToContents()
        self.table_view.resizeRowsToContents()
        self._record_base_column_widths()
        self._fit_table_in_view()
        self.student_dock.clear()
        self.course_dock.clear()
        if matrix.is_empty:
            self.status_label.setText("Matrix is empty. Ensure both datasets overlap.")
        else:
            filter_suffix = "" if not self.data_model.filters else f" | {len(self.data_model.filters)} filter(s) applied"
            self.status_label.setText(
                f"Showing {len(matrix.students)} students x {len(matrix.courses)} courses{filter_suffix}"
            )

    def _show_error(self, title: str, message: str) -> None:
        QMessageBox.critical(self, title, message)

    def _adjust_zoom(self, delta: float) -> None:
        self._update_min_zoom()
        self._zoom_factor = min(self._max_zoom_factor, max(self._min_zoom_factor, self._zoom_factor + delta))
        self._apply_zoom()

    
    def _apply_zoom(self) -> None:
        self._update_min_zoom()
        self._zoom_factor = min(self._max_zoom_factor, max(self._min_zoom_factor, self._zoom_factor))

        # 1. Scale Font
        # Note: Qt font rendering can be unstable below 1pt, but we set it anyway.
        font_size = max(0.5, self._base_font_size * self._zoom_factor)

        table_font = self.table_view.font()
        table_font.setPointSizeF(font_size)
        self.table_view.setFont(table_font)

        header_font = self.table_view.horizontalHeader().font()
        header_font.setPointSizeF(font_size)
        self.table_view.horizontalHeader().setFont(header_font)
        self.table_view.verticalHeader().setFont(header_font)

        # 2. Scale Rows
        # We calculate the target height (down to 1 pixel)
        row_height = max(1, int(round(self._base_row_height * self._zoom_factor)))
        
        # FORCE the header to use this size for ALL rows.
        # 'Fixed' mode ignores individual row sizes and uses defaultSectionSize.
        self.table_view.verticalHeader().setSectionResizeMode(QHeaderView.Fixed)
        self.table_view.verticalHeader().setDefaultSectionSize(row_height)

        # 3. Scale Columns
        if self._base_column_widths:
            # We must set resize mode to Interactive or Fixed to allow manual setting
            self.table_view.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
            for col, width in enumerate(self._base_column_widths):
                scaled_width = max(1, int(round(width * self._zoom_factor)))
                self.table_view.setColumnWidth(col, scaled_width)

        # 4. Hide Grid at small scales
        # If pixels are too small, grid lines (which are 1px) will turn the view gray.
        if row_height < 3:
            self.table_view.setShowGrid(False)
        else:
            self.table_view.setShowGrid(True)

        self.zoom_label.setText(f"{self._zoom_factor * 100:.1f}%")

  

    def _record_base_column_widths(self) -> None:
        column_count = len(self.table_model._matrix.courses)
        self._base_column_widths = [self.table_view.columnWidth(i) for i in range(column_count)]

    def _compute_fit_zoom(self) -> float | None:
        viewport = self.table_view.viewport()
        
        # Calculate total rows and columns
        # Note: We use the matrix directly as the model returns 0 if parent is valid
        rows = len(self.table_model._matrix.students)
        cols = len(self.table_model._matrix.courses)

        fit_candidates: list[float] = []
        
        # 1. Calculate vertical fit
        # We need: (rows * row_height * zoom) <= viewport_height
        # But physically, row_height * zoom cannot be less than 1.0 pixel.
        # So the absolute physical limit is viewport_height / rows.
        if rows > 0 and viewport.height() > 0:
            # Mathematical fit based on original row height
            math_fit = viewport.height() / (rows * self._base_row_height)
            fit_candidates.append(math_fit)

        # 2. Calculate horizontal fit
        if self._base_column_widths and viewport.width() > 0:
            total_base_width = sum(self._base_column_widths)
            if total_base_width > 0:
                math_fit = viewport.width() / total_base_width
                fit_candidates.append(math_fit)

        if not fit_candidates:
            return None

        # Allow zooming out significantly further than before
        # We take the smallest fit required to see everything
        target_zoom = min(fit_candidates)
        
        # Ensure we don't go below floating point stability or 0
        return min(max(self._ABSOLUTE_MIN_ZOOM, target_zoom), self._max_zoom_factor)

    def _update_min_zoom(self) -> None:
        fit_zoom = self._compute_fit_zoom()
        if fit_zoom is None:
            return
        self._min_zoom_factor = max(self._ABSOLUTE_MIN_ZOOM, min(fit_zoom, 1.0))

    def _fit_table_in_view(self) -> None:
        fit_zoom = self._compute_fit_zoom()
        if fit_zoom is None:
            return
        self._zoom_factor = min(self._zoom_factor, fit_zoom)
        self._apply_zoom()

    def _gather_filter_metadata(self):
        assert self.data_model.students_df is not None
        df = self.data_model.students_df

        columns: dict[str, str] = {}
        values_by_column: dict[str, list[object]] = {}

        for column in df.columns:
            series = df[column]
            value_type = self._infer_value_type(series)
            columns[column] = value_type
            if value_type == "categorical":
                unique_values = series.dropna().unique().tolist()
                values_by_column[column] = sorted(unique_values, key=lambda v: str(v))[:500]

        return columns, values_by_column

    @staticmethod
    def _infer_value_type(series: pd.Series) -> str:
        if pd.api.types.is_datetime64_any_dtype(series):
            return "date"

        parsed_dates = pd.to_datetime(series, errors="coerce")
        if parsed_dates.notna().sum() > 0:
            non_na_ratio = parsed_dates.notna().mean()
            if non_na_ratio >= 0.2:
                return "date"

        if pd.api.types.is_numeric_dtype(series):
            return "numeric"

        numeric_coerced = pd.to_numeric(series, errors="coerce")
        if numeric_coerced.notna().any():
            return "numeric"

        return "categorical"


    def resizeEvent(self, event):  # type: ignore[override]
        super().resizeEvent(event)
        self._fit_table_in_view()

    def eventFilter(self, obj, event):  # type: ignore[override]
        if event.type() == QEvent.Wheel and event.modifiers() & Qt.ControlModifier:
            delta = event.angleDelta().y()
            self._adjust_zoom(0.1 if delta > 0 else -0.1)
            return True
        return super().eventFilter(obj, event)


def run() -> None:
    import sys

    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    run()