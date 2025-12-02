from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import json
import pandas as pd

from filter_dialog import FilterCriterion

__all__ = [
    "CourseDataModel",
    "MatrixData",
    "StudentDescriptor",
    "CourseDescriptor",
    "CellDescriptor",
]


# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------


@dataclass
class StudentDescriptor:
    identifier: str
    label: str
    rows: pd.DataFrame


@dataclass
class CourseDescriptor:
    qid: str
    label: str
    course_row: Optional[pd.Series]


@dataclass
class CellDescriptor:
    student: StudentDescriptor
    course: CourseDescriptor
    completion_date: Optional[pd.Timestamp]
    student_rows: pd.DataFrame


@dataclass
class MatrixData:
    students: List[StudentDescriptor]
    courses: List[CourseDescriptor]
    cell_lookup: Dict[Tuple[int, int], CellDescriptor]

    @property
    def is_empty(self) -> bool:
        return not self.students or not self.courses


# ---------------------------------------------------------------------------
# Persistence helpers for the HDF5 structure used in CourseMatrix
# ---------------------------------------------------------------------------


def _has_key(store: pd.HDFStore, name: str) -> bool:
    return any(k.lstrip("/") == name for k in store.keys())


def load_courses_from_hdf5(path: str | Path) -> Tuple[pd.DataFrame, pd.DataFrame]:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)

    with pd.HDFStore(path, mode="r") as store:
        courses_df = store["courses"]
        kwalificaties_df = store["kwalificaties"]

        if "ot_product_id" in courses_df.columns:
            courses_df["ot_product_id"] = courses_df["ot_product_id"].astype(str)
        if "ot_product_id" in kwalificaties_df.columns:
            kwalificaties_df["ot_product_id"] = kwalificaties_df["ot_product_id"].astype(str)

        if _has_key(store, "kwalificaties_json"):
            kval_json = store["kwalificaties_json"]
            if "ot_product_id" in kval_json.columns:
                kval_json["ot_product_id"] = kval_json["ot_product_id"].astype(str)
            kval_json["kwalificaties"] = kval_json["kwalificaties_json"].apply(
                lambda s: None
                if s is None or (isinstance(s, float) and pd.isna(s))
                else json.loads(s)
            )
            kval_json = kval_json[["ot_product_id", "kwalificaties"]]
            courses_df = courses_df.merge(kval_json, on="ot_product_id", how="left")
        else:
            courses_df["kwalificaties"] = None

    return courses_df, kwalificaties_df


# ---------------------------------------------------------------------------
# Main data model
# ---------------------------------------------------------------------------


class CourseDataModel:
    STUDENT_ID_CANDIDATES: Tuple[str, ...] = (
        "student_id",
        "Student ID",
        "StudentID",
        "studentnummer",
        "Studentnummer",
        "Relatienummer",
        "student",
        "ID",
    )
    STUDENT_NAME_CANDIDATES: Tuple[str, ...] = (
        "Naam",
        "name",
        "Naam student",
        "student_name",
        "Student Name",
    )
    QID_CANDIDATES: Tuple[str, ...] = (
        "Kwal. ID",
        "Kwalificatie ID",
        "kwalificatie_id",
        "Kwalificatie",
        "KwalificatieID",
        "QID",
        "qid",
    )
    COMPLETION_CANDIDATES: Tuple[str, ...] = (
        "Uitgifte",
        "Completion",
        "Completion Date",
        "CompletionDate",
    )

    def __init__(self) -> None:
        self.students_df: Optional[pd.DataFrame] = None
        self.courses_df: Optional[pd.DataFrame] = None
        self.kwalificaties_df: Optional[pd.DataFrame] = None
        self.student_id_column: Optional[str] = None
        self.student_name_column: Optional[str] = None
        self.qid_column: Optional[str] = None
        self.completion_column: Optional[str] = None
        self.course_lookup_by_qid: Dict[str, pd.Series] = {}
        self.matrix_data: MatrixData = MatrixData([], [], {})
        self.filters: list[FilterCriterion] = []
    # ------------------------------------------------------------------
    # Loading routines
    # ------------------------------------------------------------------

    def load_students(self, path: str | Path) -> None:
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(path)

        df = pd.read_excel(path)
        if df.empty:
            raise ValueError("The provided Excel file does not contain any rows.")

        self.students_df = df
        self.student_id_column = self._detect_column(df.columns, self.STUDENT_ID_CANDIDATES)
        if not self.student_id_column:
            raise KeyError(
                "Could not determine the student identifier column. "
                "Please ensure the Excel file contains one of the following columns: "
                f"{', '.join(self.STUDENT_ID_CANDIDATES)}"
            )

        self.qid_column = self._detect_column(df.columns, self.QID_CANDIDATES)
        if not self.qid_column:
            raise KeyError(
                "Could not determine the qualification ID column. "
                "Ensure the Excel file contains a column such as 'Kwal. ID'."
            )

        self.completion_column = self._detect_column(df.columns, self.COMPLETION_CANDIDATES)
        if not self.completion_column:
            raise KeyError(
                "Could not determine the completion date column. "
                "Ensure the Excel file contains a column such as 'Uitgifte'."
            )

        self.student_name_column = self._detect_column(df.columns, self.STUDENT_NAME_CANDIDATES)

        df[self.completion_column] = pd.to_datetime(df[self.completion_column], errors="coerce")
        df[self.qid_column] = df[self.qid_column].astype(str)
        df[self.student_id_column] = df[self.student_id_column].astype(str)

        self.matrix_data = MatrixData([], [], {})
        self.filters = []        

    def load_courses(self, path: str | Path) -> None:
        courses_df, kwalificaties_df = load_courses_from_hdf5(path)
        if courses_df.empty:
            raise ValueError("The provided HDF5 file does not contain any courses.")

        self.courses_df = courses_df
        self.kwalificaties_df = kwalificaties_df
        self._build_course_lookup()
        self.matrix_data = MatrixData([], [], {})

    # ------------------------------------------------------------------
    # Matrix construction
    # ------------------------------------------------------------------

    def build_matrix(self) -> MatrixData:
        if self.students_df is None or self.courses_df is None:
            self.matrix_data = MatrixData([], [], {})
            return self.matrix_data

        students_df = self._apply_filters(self.students_df)

        students: List[StudentDescriptor] = []
        for _, student_rows in students_df.groupby(self.student_id_column):
            student_id = str(student_rows[self.student_id_column].iloc[0])
            if self.student_name_column and self.student_name_column in student_rows.columns:
                name_value = student_rows[self.student_name_column].iloc[0]
                label = f"{name_value} ({student_id})"
            else:
                label = student_id
            students.append(StudentDescriptor(student_id, label, student_rows.copy()))

        if not students:
            self.matrix_data = MatrixData([], [], {})
            return self.matrix_data

        unique_qids = (
            students_df[self.qid_column]
            .dropna()
            .astype(str)
            .unique()
            .tolist()
        )
        unique_qids.sort()

        courses: List[CourseDescriptor] = []
        for qid in unique_qids:
            course_row = self.course_lookup_by_qid.get(str(qid))
            label = self._course_label(course_row, qid)
            courses.append(CourseDescriptor(str(qid), label, None if course_row is None else course_row.copy()))

        if not courses:
            self.matrix_data = MatrixData(students, [], {})
            return self.matrix_data

        course_index_by_qid = {course.qid: idx for idx, course in enumerate(courses)}

        cell_lookup: Dict[Tuple[int, int], CellDescriptor] = {}
        for row_index, student in enumerate(students):
            if self.qid_column not in student.rows:
                continue
            grouped = student.rows.groupby(self.qid_column)
            for qid, rows in grouped:
                qid = str(qid)
                column_index = course_index_by_qid.get(qid)
                if column_index is None:
                    continue
                course = courses[column_index]
                completion_series = pd.to_datetime(rows[self.completion_column], errors="coerce")
                completion_date: Optional[pd.Timestamp]
                completion_date = None
                if not completion_series.isna().all():
                    completion_date = completion_series.max()
                cell_lookup[(row_index, column_index)] = CellDescriptor(
                    student=student,
                    course=course,
                    completion_date=completion_date,
                    student_rows=rows.copy(),
                )

        self.matrix_data = MatrixData(students, courses, cell_lookup)
        return self.matrix_data

    # ------------------------------------------------------------------
    # Helper accessors
    # ------------------------------------------------------------------

    def set_filters(self, filters: list[FilterCriterion]) -> None:
        self.filters = filters
        # Reset cached matrix so it is rebuilt on demand
        self.matrix_data = MatrixData([], [], {})


    def get_cell(self, row: int, column: int) -> Optional[CellDescriptor]:
        if not self.matrix_data.cell_lookup:
            return None
        return self.matrix_data.cell_lookup.get((row, column))

    def get_course_by_qid(self, qid: str) -> Optional[pd.Series]:
        return self.course_lookup_by_qid.get(str(qid))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_column(columns: Iterable[str], candidates: Iterable[str]) -> Optional[str]:
        columns_lower = {col.lower(): col for col in columns}
        for candidate in candidates:
            if candidate in columns:
                return candidate
            lowered = candidate.lower()
            if lowered in columns_lower:
                return columns_lower[lowered]
        return None

    def _build_course_lookup(self) -> None:
        self.course_lookup_by_qid.clear()
        if self.courses_df is None:
            return

        for _, row in self.courses_df.iterrows():
            kwalificaties = row.get("kwalificaties")
            if isinstance(kwalificaties, list):
                for kwal in kwalificaties:
                    if isinstance(kwal, dict):
                        qid = kwal.get("Kwal. ID") or kwal.get("Kwalificatie ID") or kwal.get("kwalificatie_id")
                        if qid is not None:
                            self.course_lookup_by_qid[str(qid)] = row

    @staticmethod
    def _course_label(course_row: Optional[pd.Series], qid: str) -> str:
        if course_row is None:
            return str(qid)
        for candidate in ("naam", "name", "course_name", "title"):
            if candidate in course_row.index:
                value = course_row[candidate]
                if isinstance(value, str) and value.strip():
                    return f"{value} ({qid})"
        return str(qid)
    
    def _apply_filters(self, df: pd.DataFrame) -> pd.DataFrame:
        if not self.filters:
            return df

        filtered = df
        for criterion in self.filters:
            if criterion.column not in filtered.columns:
                continue

            series = filtered[criterion.column]
            if criterion.value_type == "categorical":
                values = [str(v) for v in criterion.values if pd.notna(v)]
                if not values:
                    continue
                series_str = series.astype(str)
                if criterion.operator == "is":
                    mask = series_str == values[0]
                elif criterion.operator == "is not":
                    mask = series_str != values[0]
                elif criterion.operator == "not in":
                    mask = ~series_str.isin(values)
                else:  # in
                    mask = series_str.isin(values)
            elif criterion.value_type == "date":
                series_dt = pd.to_datetime(series, errors="coerce")
                if not criterion.values:
                    continue
                start = pd.to_datetime(criterion.values[0], errors="coerce")
                end = pd.to_datetime(criterion.values[1], errors="coerce") if len(criterion.values) > 1 else None
                if pd.isna(start):
                    continue
                if criterion.operator == "between" and end is not None and not pd.isna(end):
                    mask = (series_dt >= start) & (series_dt <= end)
                elif criterion.operator == "≠":
                    mask = series_dt != start
                elif criterion.operator == "<":
                    mask = series_dt < start
                elif criterion.operator == "≤":
                    mask = series_dt <= start
                elif criterion.operator == ">":
                    mask = series_dt > start
                elif criterion.operator == "≥":
                    mask = series_dt >= start
                else:
                    mask = series_dt == start
            else:  # numeric
                numeric_series = pd.to_numeric(series, errors="coerce")
                if not criterion.values:
                    continue
                start = pd.to_numeric(criterion.values[0], errors="coerce")
                end = pd.to_numeric(criterion.values[1], errors="coerce") if len(criterion.values) > 1 else None
                if pd.isna(start):
                    continue
                if criterion.operator == "between" and end is not None and not pd.isna(end):
                    mask = (numeric_series >= start) & (numeric_series <= end)
                elif criterion.operator == "≠":
                    mask = numeric_series != start
                elif criterion.operator == "<":
                    mask = numeric_series < start
                elif criterion.operator == "≤":
                    mask = numeric_series <= start
                elif criterion.operator == ">":
                    mask = numeric_series > start
                elif criterion.operator == "≥":
                    mask = numeric_series >= start
                else:
                    mask = numeric_series == start

            filtered = filtered[mask]

        return filtered    