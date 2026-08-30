from fastapi.testclient import TestClient

from sheet_audit_agent.api import create_app


def test_health() -> None:
    response = TestClient(create_app()).get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_audit_endpoint_returns_typed_report() -> None:
    response = TestClient(create_app()).post(
        "/v1/audits",
        json={
            "spreadsheet_id": "book",
            "sheet_id": 10,
            "sheet_title": "Sheet1",
            "row_count": 5,
            "column_count": 6,
            "revision": "r1",
            "complete": True,
            "cells": [
                {"row": 0, "column": 0, "formatted_value": "THU"},
                {"row": 1, "column": 1, "formatted_value": "HỌ VÀ TÊN"},
                {"row": 2, "column": 1, "formatted_value": "Nguyễn Văn An"},
                {"row": 3, "column": 1, "formatted_value": "Nguyen Van An"},
                {"row": 4, "column": 1, "formatted_value": "TỔNG"},
            ],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "findings"
    assert body["findings"][0]["classification"] == "exact"


def test_chat_endpoint_returns_reply() -> None:
    response = TestClient(create_app()).post(
        "/v1/chat",
        json={"message": "STT 2 là CK"}
    )
    assert response.status_code == 200
    body = response.json()
    assert "reply" in body
    assert len(body["reply"]) > 0

