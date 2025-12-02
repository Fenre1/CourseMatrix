from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Literal, Optional

import pandas as pd
from PyQt5.QtCore import QDate
from PyQt5.QtWidgets import (
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


ValueKind = Literal["categorical", "numeric", "date"]


@dataclass
class FilterCriterion:
    column: str
    operator: str
    values: List[object]
    value_type: ValueKind


class MultiSelectWidget(QWidget):
    """Searchable multi-select list for categorical filters."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self.search = QLineEdit(self)
        self.search.setPlaceholderText("Search values…")
        self.search.textChanged.connect(self._apply_filter)
        layout.addWidget(self.search)

        self.list_widget = QListWidget(self)
        layout.addWidget(self.list_widget)
        self._all_items: List[str] = []

    def set_values(self, values: Iterable[object]) -> None:
        self.list_widget.clear()
        self._all_items = ["" if pd.isna(v) else str(v) for v in values]
        for value in self._all_items:
            item = QListWidgetItem(value)
            item.setCheckState(0)
            self.list_widget.addItem(item)

    def _apply_filter(self, text: str) -> None:
        text_lower = text.lower().strip()
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            visible = text_lower in item.text().lower()
            item.setHidden(not visible)

    def selected_values(self) -> List[str]:
        values: List[str] = []
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.checkState():
                values.append(item.text())
        return values

    def set_selected_values(self, values: Iterable[str]) -> None:
        selected = set(values)
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            item.setCheckState(2 if item.text() in selected else 0)


class NumericInput(QWidget):
    """Numeric input supporting single value or ranges."""

    def __init__(self, allow_range: bool, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self.minimum = QDoubleSpinBox(self)
        self.minimum.setMinimum(-1e12)
        self.minimum.setMaximum(1e12)
        self.minimum.setDecimals(6)
        layout.addWidget(self.minimum)

        self.maximum: Optional[QDoubleSpinBox] = None
        if allow_range:
            self.maximum = QDoubleSpinBox(self)
            self.maximum.setMinimum(-1e12)
            self.maximum.setMaximum(1e12)
            self.maximum.setDecimals(6)
            self.maximum.setPrefix("to ")
            layout.addWidget(self.maximum)

    def values(self) -> List[float]:
        vals = [self.minimum.value()]
        if self.maximum is not None:
            vals.append(self.maximum.value())
        return vals

    def set_values(self, values: Iterable[float]) -> None:
        vals = list(values)
        if vals:
            self.minimum.setValue(float(vals[0]))
        if self.maximum is not None and len(vals) > 1:
            self.maximum.setValue(float(vals[1]))


class DateInput(QWidget):
    """Date input supporting single value or ranges."""

    def __init__(self, allow_range: bool, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self.minimum = QDateEdit(self)
        self.minimum.setCalendarPopup(True)
        self.minimum.setDisplayFormat("yyyy-MM-dd")
        layout.addWidget(self.minimum)

        self.maximum: Optional[QDateEdit] = None
        if allow_range:
            self.maximum = QDateEdit(self)
            self.maximum.setCalendarPopup(True)
            self.maximum.setDisplayFormat("yyyy-MM-dd")
            self.maximum.setSpecialValueText("to")
            layout.addWidget(self.maximum)

    def values(self) -> List[pd.Timestamp]:
        vals = [pd.Timestamp(self.minimum.date().toPyDate())]
        if self.maximum is not None:
            vals.append(pd.Timestamp(self.maximum.date().toPyDate()))
        return vals

    def set_values(self, values: Iterable[pd.Timestamp]) -> None:
        vals = list(values)
        if vals:
            self.minimum.setDate(QDate(vals[0].year, vals[0].month, vals[0].day))
        if self.maximum is not None and len(vals) > 1:
            second = vals[1]
            self.maximum.setDate(QDate(second.year, second.month, second.day))


class FilterRowWidget(QFrame):
    """Single filter row with column/operator/value selectors."""

    CATEGORICAL_OPERATORS = ["is", "is not", "in", "not in"]
    NUMERIC_OPERATORS = ["=", "≠", "<", "≤", ">", "≥", "between"]

    def __init__(self, columns: Dict[str, ValueKind], values_by_column: Dict[str, List[object]], parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.columns = columns
        self.values_by_column = values_by_column

        self.setFrameStyle(QFrame.Panel | QFrame.Raised)
        self.setLineWidth(1)

        layout = QGridLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(6)

        self.column_combo = QComboBox(self)
        self.column_combo.addItems(sorted(self.columns.keys()))
        self.column_combo.currentTextChanged.connect(self._on_column_changed)
        layout.addWidget(self.column_combo, 0, 0)

        self.operator_combo = QComboBox(self)
        self.operator_combo.currentTextChanged.connect(self._on_operator_changed)
        layout.addWidget(self.operator_combo, 0, 1)

        self.value_container = QVBoxLayout()
        self.value_container.setContentsMargins(0, 0, 0, 0)
        self.value_container.setSpacing(0)
        self.value_widget: Optional[QWidget] = None

        placeholder = QWidget(self)
        placeholder.setLayout(self.value_container)
        layout.addWidget(placeholder, 0, 2)

        self.remove_button = QPushButton("Remove", self)
        layout.addWidget(self.remove_button, 0, 3)

        self._on_column_changed(self.column_combo.currentText())

    def _on_column_changed(self, column: str) -> None:
        value_type = self.columns[column]
        self.operator_combo.clear()
        if value_type == "categorical":
            self.operator_combo.addItems(self.CATEGORICAL_OPERATORS)
        else:
            self.operator_combo.addItems(self.NUMERIC_OPERATORS)
        self._update_value_widget(value_type)

    def _update_value_widget(self, value_type: ValueKind) -> None:
        if self.value_widget is not None:
            self.value_container.removeWidget(self.value_widget)
            self.value_widget.deleteLater()
            self.value_widget = None

        allow_range = self.operator_combo.currentText() == "between"
        if value_type == "categorical":
            widget = MultiSelectWidget(self)
            widget.set_values(self.values_by_column.get(self.column_combo.currentText(), []))
        elif value_type == "date":
            widget = DateInput(allow_range, self)
        else:
            widget = NumericInput(allow_range, self)

        self.value_container.addWidget(widget)
        self.value_widget = widget

    def _on_operator_changed(self, operator: str) -> None:
        value_type = self.columns[self.column_combo.currentText()]
        expect_range = operator == "between"
        if value_type == "categorical":
            return  # categorical widget already supports multiple values
        has_range_widget = isinstance(self.value_widget, (NumericInput, DateInput)) and self.value_widget.maximum is not None
        if expect_range == has_range_widget:
            return
        self._update_value_widget(value_type)

    def to_filter(self) -> FilterCriterion:
        column = self.column_combo.currentText()
        value_type = self.columns[column]
        operator = self.operator_combo.currentText()

        if isinstance(self.value_widget, MultiSelectWidget):
            values = self.value_widget.selected_values()
        elif isinstance(self.value_widget, NumericInput):
            values = self.value_widget.values()
        elif isinstance(self.value_widget, DateInput):
            values = self.value_widget.values()
        else:
            values = []

        return FilterCriterion(column=column, operator=operator, values=values, value_type=value_type)

    def load_filter(self, criterion: FilterCriterion) -> None:
        if criterion.column in self.columns:
            self.column_combo.setCurrentText(criterion.column)
        if criterion.operator in self.CATEGORICAL_OPERATORS + self.NUMERIC_OPERATORS:
            self.operator_combo.setCurrentText(criterion.operator)
        self._on_operator_changed(self.operator_combo.currentText())
        if isinstance(self.value_widget, MultiSelectWidget):
            self.value_widget.set_selected_values([str(v) for v in criterion.values])
        elif isinstance(self.value_widget, NumericInput):
            numeric_values = [float(v) for v in criterion.values]
            self.value_widget.set_values(numeric_values)
        elif isinstance(self.value_widget, DateInput):
            date_values = [pd.Timestamp(v) for v in criterion.values]
            self.value_widget.set_values(date_values)


class FilterDialog(QDialog):
    """Dialog that allows users to build an arbitrary set of filters."""

    def __init__(self, columns: Dict[str, ValueKind], values_by_column: Dict[str, List[object]], initial_filters: Optional[List[FilterCriterion]] = None, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add filters")
        self.columns = columns
        self.values_by_column = values_by_column
        self.rows: List[FilterRowWidget] = []

        main_layout = QVBoxLayout(self)

        info_label = QLabel("Filters are combined with AND. Add rows to refine your dataset.", self)
        main_layout.addWidget(info_label)

        self.rows_container = QVBoxLayout()
        self.rows_container.setContentsMargins(0, 0, 0, 0)
        self.rows_container.setSpacing(6)
        main_layout.addLayout(self.rows_container)

        add_button = QPushButton("Add filter", self)
        add_button.clicked.connect(self.add_row)
        main_layout.addWidget(add_button)

        main_layout.addStretch(1)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        main_layout.addWidget(buttons)

        if initial_filters:
            for criterion in initial_filters:
                self.add_row(criterion)
        if not self.rows:
            self.add_row()

    def add_row(self, criterion: Optional[FilterCriterion] = None) -> None:
        row = FilterRowWidget(self.columns, self.values_by_column, self)
        row.remove_button.clicked.connect(lambda _, r=row: self.remove_row(r))
        self.rows_container.addWidget(row)
        self.rows.append(row)
        if criterion:
            row.load_filter(criterion)

    def remove_row(self, row: FilterRowWidget) -> None:
        if row in self.rows:
            self.rows.remove(row)
            row.setParent(None)
            row.deleteLater()
        if not self.rows:
            self.add_row()

    def filters(self) -> List[FilterCriterion]:
        return [row.to_filter() for row in self.rows]


__all__ = ["FilterDialog", "FilterCriterion", "ValueKind"]