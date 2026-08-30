# TDD evidence: Python Sheet Audit Agent core

## Source

- [PRD](../product/prd-duplicate-member-detection.md)
- [Thiết kế kỹ thuật](../technical/duplicate-detection-agent.design.md)
- [Kế hoạch TDD](duplicate-detection-agent.tdd-plan.md)

## RED

Command:

```powershell
python -m pytest -q -p no:cacheprovider
```

Kết quả: collection thất bại với bốn lỗi `ModuleNotFoundError: No module named 'sheet_audit_agent'`. Đây là RED hợp lệ vì tests đã tham chiếu capability chưa được triển khai.

## GREEN

Command:

```powershell
python -m pytest -q -p no:cacheprovider
```

Kết quả: `14 passed, 1 warning in 0.42s`.

Coverage command:

```powershell
python -m pytest --cov=sheet_audit_agent --cov-report=term-missing -q -p no:cacheprovider
```

Kết quả: `14 passed`; tổng coverage `95.65%`, vượt ngưỡng 80%.

## Guarantees

| Guarantee | Test | Type | Result |
|---|---|---|---|
| Chuẩn hóa dấu tiếng Việt, dấu câu và khoảng trắng | `tests/test_normalization.py` | Unit | PASS |
| Tự nhận diện THU và CHI trong cùng snapshot | `tests/test_structure.py` | Unit | PASS |
| Thiếu hàng TỔNG tạo trạng thái partial | `tests/test_structure.py` | Unit | PASS |
| Exact duplicate có confidence 1 | `tests/test_audit.py` | Unit | PASS |
| Viết tắt trả nhiều ứng viên | `tests/test_audit.py` | Unit | PASS |
| Typo điểm cao được cảnh báo, chuỗi ngắn không fuzzy-match | `tests/test_audit.py` | Unit | PASS |
| Snapshot incomplete không bao giờ trả clean | `tests/test_audit.py` | Unit | PASS |
| FastAPI health và audit endpoint trả schema đúng | `tests/test_api.py` | API | PASS |

## Known gaps

- `ruff` và `mypy` chưa có trong môi trường nên static checks chưa chạy; chúng đã được khai báo trong dev dependencies.
- Có một deprecation warning từ `fastapi.testclient`/Starlette về `httpx`; không ảnh hưởng kết quả test hiện tại.
- Chưa tích hợp React, chưa có full-sheet chunk loader, conditional write, component test hoặc E2E.
