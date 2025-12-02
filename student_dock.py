from __future__ import annotations

from typing import Optional

import pandas as pd
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QDockWidget, QTextBrowser


class StudentInfoDock(QDockWidget):
    """Dock widget that renders the student information for a selection."""

    def __init__(self, parent=None) -> None:
        super().__init__("Student details", parent)
        self.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        self._browser = QTextBrowser(self)
        self._browser.setOpenExternalLinks(True)
        self.setWidget(self._browser)
        self.clear()

    def clear(self) -> None:
        self._browser.setHtml("<i>Select a student/course to see details.</i>")

    def show_student_rows(self, rows: Optional[pd.DataFrame]) -> None:
        if rows is None or rows.empty:
            self.clear()
            return

        html_parts = ["<h3>Student record</h3>"]
        for idx, (_, row) in enumerate(rows.iterrows(), start=1):
            html_parts.append(f"<h4>Entry {idx}</h4>")
            html_parts.append("<table style='width:100%; border-collapse: collapse;'>")
            for column, value in row.items():
                value_str = "" if pd.isna(value) else str(value)
                html_parts.append(
                    "<tr>"
                    f"<th style='text-align:left; padding:4px; border-bottom:1px solid #ccc;'>{column}</th>"
                    f"<td style='padding:4px; border-bottom:1px solid #ccc;'>{value_str}</td>"
                    "</tr>"
                )
            html_parts.append("</table>")
        self._browser.setHtml("\n".join(html_parts))