from __future__ import annotations

from typing import Optional

import pandas as pd
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QDockWidget, QTextBrowser


class CourseInfoDock(QDockWidget):
    """Dock widget that displays course metadata."""

    def __init__(self, parent=None) -> None:
        super().__init__("Course details", parent)
        self.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        self._browser = QTextBrowser(self)
        self.setWidget(self._browser)
        self.clear()

    def clear(self) -> None:
        self._browser.setHtml("<i>Select a student/course to see course details.</i>")

    def show_course(self, course_row: Optional[pd.Series]) -> None:
        if course_row is None or course_row.empty:
            self.clear()
            return

        html_parts = ["<h3>Course information</h3>", "<table style='width:100%; border-collapse: collapse;'>"]
        for column, value in course_row.items():
            if isinstance(value, (list, dict)):
                value_str = str(value)
            elif pd.isna(value):
                value_str = ""
            else:
                value_str = str(value)
            html_parts.append(
                "<tr>"
                f"<th style='text-align:left; padding:4px; border-bottom:1px solid #ccc;'>{column}</th>"
                f"<td style='padding:4px; border-bottom:1px solid #ccc;'>{value_str}</td>"
                "</tr>"
            )
        html_parts.append("</table>")
        self._browser.setHtml("\n".join(html_parts))