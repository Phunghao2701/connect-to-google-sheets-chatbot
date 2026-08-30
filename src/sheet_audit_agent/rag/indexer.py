"""Semantic Indexer for Google Sheets data."""

import re
from typing import Any
from sheet_audit_agent.matching import normalize_text
from sheet_audit_agent.models import SheetSnapshot
from sheet_audit_agent.structure import detect_regions


class SheetIndexer:
    """Extracts structured knowledge documents from a SheetSnapshot."""

    @staticmethod
    def index(snapshot: SheetSnapshot) -> dict[str, Any]:
        detection = detect_regions(snapshot)
        cell_map = {(c.row, c.column): c.formatted_value for c in snapshot.cells}

        member_records = []
        expense_records = []
        summaries = []

        # Find method columns by year across header rows (0 to 3)
        method_cols_by_year: dict[int, int] = {}
        for c in range(snapshot.column_count):
            col_header = normalize_text(cell_map.get((2, c), "") or cell_map.get((1, c), ""))
            if "hinh thuc" in col_header or "ht" == col_header:
                # Find associated year
                year_text = cell_map.get((1, c), "") or cell_map.get((0, c), "") or cell_map.get((1, max(0, c - 2)), "")
                y_match = re.search(r"\b(20\d\d)\b", year_text)
                if y_match:
                    method_cols_by_year[int(y_match.group(1))] = c

        for region in detection.regions:
            if region.kind == "THU":
                name_col = region.audit_columns[0].column
                stt_col = region.start_column

                for r in range(region.start_row, region.end_row):
                    name = cell_map.get((r, name_col), "").strip()
                    stt = cell_map.get((r, stt_col), "").strip()
                    if not name or name.lower() in ["tong", "tổng", "tong cong", "tổng cộng"]:
                        continue

                    row_details = {}
                    for c in range(region.start_column, region.end_column):
                        val = cell_map.get((r, c), "").strip()
                        if val:
                            row_details[f"col_{c}"] = val

                    semantic_text = f"Thành viên đóng quỹ: STT #{stt or (r - region.start_row + 1)} - Họ và tên: {name} (Dòng {r + 1})"
                    if row_details:
                        semantic_text += f" | Chi tiết: {', '.join(f'{k}: {v}' for k, v in row_details.items())}"

                    member_records.append({
                        "type": "member",
                        "row": r,
                        "sheet_id": snapshot.sheet_id,
                        "stt": stt or str(r - region.start_row + 1),
                        "name": name,
                        "name_col": name_col,
                        "method_cols_by_year": method_cols_by_year,
                        "details": row_details,
                        "semantic_text": semantic_text,
                    })

            elif region.kind == "CHI":
                content_col = region.audit_columns[0].column
                stt_col = region.start_column

                for r in range(region.start_row, region.end_row):
                    content = cell_map.get((r, content_col), "").strip()
                    stt = cell_map.get((r, stt_col), "").strip()
                    if not content or content.lower() in ["tong", "tổng", "tong cong", "tổng cộng"]:
                        continue

                    row_details = {}
                    for c in range(region.start_column, region.end_column):
                        val = cell_map.get((r, c), "").strip()
                        if val:
                            row_details[f"col_{c}"] = val

                    semantic_text = f"Khoản chi tiêu: STT #{stt or (r - region.start_row + 1)} - Nội dung chi: {content} (Dòng {r + 1})"
                    if row_details:
                        semantic_text += f" | Chi tiết: {', '.join(f'{k}: {v}' for k, v in row_details.items())}"

                    expense_records.append({
                        "type": "expense",
                        "row": r,
                        "sheet_id": snapshot.sheet_id,
                        "stt": stt or str(r - region.start_row + 1),
                        "content": content,
                        "content_col": content_col,
                        "method_cols_by_year": method_cols_by_year,
                        "details": row_details,
                        "semantic_text": semantic_text,
                    })

        # Extract total row summaries
        for r in range(snapshot.row_count):
            for c in range(snapshot.column_count):
                val = cell_map.get((r, c), "").strip().lower()
                if val in ["tong", "tổng", "tong cong", "tổng cộng"]:
                    totals = []
                    for tc in range(snapshot.column_count):
                        t_val = cell_map.get((r, tc), "").strip()
                        if t_val and t_val.lower() not in ["tong", "tổng", "tong cong", "tổng cộng"]:
                            header_val = cell_map.get((2, tc), "") or cell_map.get((1, tc), "") or f"Cột {tc + 1}"
                            year_val = cell_map.get((1, tc), "") or cell_map.get((0, tc), "")
                            label = f"{header_val} ({year_val})" if year_val and year_val != header_val else header_val
                            totals.append(f"{label}: {t_val}")

                    if totals:
                        summary_text = f"Tổng kết hàng TỔNG (Dòng {r + 1}): {', '.join(totals)}"
                        summaries.append({
                            "type": "summary",
                            "row": r,
                            "semantic_text": summary_text,
                            "details": totals,
                        })

        return {
            "sheet_title": snapshot.sheet_title,
            "sheet_id": snapshot.sheet_id,
            "members": member_records,
            "expenses": expense_records,
            "summaries": summaries,
            "method_cols_by_year": method_cols_by_year,
            "total_records": len(member_records) + len(expense_records),
        }
