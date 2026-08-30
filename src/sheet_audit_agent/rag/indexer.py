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

        # Build per-region column metadata and method column mappings
        method_cols_by_region: dict[str, dict[int, int]] = {}
        all_method_cols_by_year: dict[int, int] = {}

        # Look for default year in sheet title
        title_y_match = re.search(r"\b(20\d\d)\b", snapshot.sheet_title)
        default_sheet_year = int(title_y_match.group(1)) if title_y_match else None

        for region in detection.regions:
            reg_method_cols: dict[int, int] = {}
            reg_col_meta: dict[int, dict[str, Any]] = {}
            curr_year: int | None = None

            for c in range(region.start_column, region.end_column):
                r0 = cell_map.get((0, c), "").strip()
                r1 = cell_map.get((1, c), "").strip()
                r2 = cell_map.get((2, c), "").strip()

                # Detect year in row 0 or 1 for this column
                y_match = re.search(r"\b(20\d\d)\b", f"{r0} {r1}")
                if y_match:
                    curr_year = int(y_match.group(1))

                col_header = r2 or r1 or r0 or f"Cột {c + 1}"
                norm_header = normalize_text(col_header)
                is_method = "hinh thuc" in norm_header or norm_header == "ht"

                year_for_col = curr_year or default_sheet_year
                if is_method and year_for_col:
                    reg_method_cols[year_for_col] = c
                    all_method_cols_by_year[year_for_col] = c

                reg_col_meta[c] = {
                    "year": year_for_col,
                    "header": col_header,
                    "norm_header": norm_header,
                    "is_method": is_method,
                }

            method_cols_by_region[region.kind] = reg_method_cols

            if region.kind == "THU":
                name_col = region.audit_columns[0].column
                stt_col = region.start_column

                for r in range(region.start_row, region.end_row):
                    name = cell_map.get((r, name_col), "").strip()
                    stt = cell_map.get((r, stt_col), "").strip()
                    if not name or name.lower() in ["tong", "tổng", "tong cong", "tổng cộng"]:
                        continue

                    payment_by_year: dict[int, dict[str, str]] = {}
                    row_details: dict[str, str] = {}

                    for c in range(region.start_column, region.end_column):
                        # Skip identity columns (STT and name) from payment_by_year
                        val = cell_map.get((r, c), "").strip()
                        if not val:
                            continue
                        meta = reg_col_meta.get(c, {})
                        c_year = meta.get("year")
                        c_header = meta.get("header", f"col_{c}")
                        row_details[f"col_{c}"] = val

                        if c_year and c not in (stt_col, name_col):
                            y_dict = payment_by_year.setdefault(c_year, {})
                            if meta.get("is_method"):
                                y_dict["method"] = val
                            else:
                                y_dict[c_header] = val

                    # Structured semantic text
                    semantic_lines = [
                        f"Thành viên đóng quỹ: STT #{stt or (r - region.start_row + 1)} - Họ và tên: {name} (Dòng {r + 1})"
                    ]
                    if payment_by_year:
                        for yr in sorted(payment_by_year.keys()):
                            details_yr = payment_by_year[yr]
                            parts = []
                            if "method" in details_yr:
                                parts.append(f"Hình thức: {details_yr['method']}")
                            for k, v in details_yr.items():
                                if k != "method":
                                    parts.append(f"{k}: {v}")
                            semantic_lines.append(f"  • Năm {yr}: {', '.join(parts) if parts else 'Chưa có dữ liệu'}")
                    elif row_details:
                        semantic_lines.append(f"  • Chi tiết: {', '.join(f'{k}: {v}' for k, v in row_details.items())}")

                    semantic_text = "\n".join(semantic_lines)

                    tags = [str(stt or (r - region.start_row + 1)), name.lower(), "member", "thu"]
                    for yr in reg_method_cols.keys():
                        tags.append(str(yr))

                    member_records.append({
                        "type": "member",
                        "region": "THU",
                        "row": r,
                        "sheet_id": snapshot.sheet_id,
                        "stt": stt or str(r - region.start_row + 1),
                        "name": name,
                        "name_col": name_col,
                        "method_cols_by_year": reg_method_cols,
                        "payment_by_year": payment_by_year,
                        "years": list(reg_method_cols.keys()),
                        "context_tags": tags,
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

                    payment_by_year = {}
                    row_details = {}
                    for c in range(region.start_column, region.end_column):
                        val = cell_map.get((r, c), "").strip()
                        if not val:
                            continue
                        meta = reg_col_meta.get(c, {})
                        c_year = meta.get("year")
                        c_header = meta.get("header", f"col_{c}")
                        row_details[f"col_{c}"] = val

                        if c_year and c not in (stt_col, content_col):
                            y_dict = payment_by_year.setdefault(c_year, {})
                            if meta.get("is_method"):
                                y_dict["method"] = val
                            else:
                                y_dict[c_header] = val

                    semantic_lines = [
                        f"Khoản chi tiêu: STT #{stt or (r - region.start_row + 1)} - Nội dung chi: {content} (Dòng {r + 1})"
                    ]
                    if payment_by_year:
                        for yr in sorted(payment_by_year.keys()):
                            details_yr = payment_by_year[yr]
                            parts = []
                            if "method" in details_yr:
                                parts.append(f"Hình thức: {details_yr['method']}")
                            for k, v in details_yr.items():
                                if k != "method":
                                    parts.append(f"{k}: {v}")
                            semantic_lines.append(f"  • Năm {yr}: {', '.join(parts) if parts else 'Chưa có dữ liệu'}")
                    elif row_details:
                        semantic_lines.append(f"  • Chi tiết: {', '.join(f'{k}: {v}' for k, v in row_details.items())}")

                    semantic_text = "\n".join(semantic_lines)

                    tags = [str(stt or (r - region.start_row + 1)), content.lower(), "expense", "chi"]
                    for yr in reg_method_cols.keys():
                        tags.append(str(yr))

                    expense_records.append({
                        "type": "expense",
                        "region": "CHI",
                        "row": r,
                        "sheet_id": snapshot.sheet_id,
                        "stt": stt or str(r - region.start_row + 1),
                        "content": content,
                        "content_col": content_col,
                        "method_cols_by_year": reg_method_cols,
                        "payment_by_year": payment_by_year,
                        "years": list(reg_method_cols.keys()),
                        "context_tags": tags,
                        "details": row_details,
                        "semantic_text": semantic_text,
                    })

        # Extract total row summaries
        for r in range(snapshot.row_count):
            for c in range(snapshot.column_count):
                val = cell_map.get((r, c), "").strip().lower()
                if val in ["tong", "tổng", "tong cong", "tổng cộng"]:
                    totals = []
                    summary_tags = ["tong", "tong cong", "summary", "total"]
                    for tc in range(snapshot.column_count):
                        t_val = cell_map.get((r, tc), "").strip()
                        if t_val and t_val.lower() not in ["tong", "tổng", "tong cong", "tổng cộng"]:
                            header_val = cell_map.get((2, tc), "") or cell_map.get((1, tc), "") or f"Cột {tc + 1}"
                            year_val = cell_map.get((1, tc), "") or cell_map.get((0, tc), "")
                            label = f"{header_val} ({year_val})" if year_val and year_val != header_val else header_val
                            totals.append(f"{label}: {t_val}")
                            y_m = re.search(r"\b(20\d\d)\b", label)
                            if y_m:
                                summary_tags.append(y_m.group(1))

                    if totals:
                        summary_text = f"Tổng kết hàng TỔNG (Dòng {r + 1}): {', '.join(totals)}"
                        summaries.append({
                            "type": "summary",
                            "row": r,
                            "context_tags": summary_tags,
                            "semantic_text": summary_text,
                            "details": totals,
                        })

        return {
            "sheet_title": snapshot.sheet_title,
            "sheet_id": snapshot.sheet_id,
            "method_cols_by_region": method_cols_by_region,
            "method_cols_by_year": all_method_cols_by_year,
            "members": member_records,
            "expenses": expense_records,
            "summaries": summaries,
            "total_records": len(member_records) + len(expense_records),
        }
