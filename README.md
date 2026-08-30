# Agent workspace

Thư mục này dành riêng cho agent hỗ trợ xử lý dữ liệu thu–chi. Phiên bản đầu tiên tập trung vào việc tự rà soát sheet Google Sheets đang mở và phát hiện nội dung trùng lặp.

## Capability đầu tiên

- Tự nhận diện và đọc các bảng THU/CHI trong sheet đang mở.
- Chuẩn hóa nội dung cần kiểm tra.
- Phát hiện và giải thích trường hợp trùng chính xác, sai chính tả hoặc viết tắt.
- Đề xuất sửa nhưng chỉ ghi sau khi người dùng xem preview và phê duyệt.

PRD hiện tại: [Agent phát hiện tên trùng lặp](docs/product/prd-duplicate-member-detection.md).

Thiết kế và kế hoạch triển khai:

- [Thiết kế kỹ thuật Duplicate Detection Agent](docs/technical/duplicate-detection-agent.design.md)
- [Kế hoạch TDD](docs/testing/duplicate-detection-agent.tdd-plan.md)

## Python agent

Agent core và API được viết bằng Python 3.12. Chạy test:

```powershell
python -m pytest
python -m pytest --cov=sheet_audit_agent --cov-report=term-missing
```

Chạy API sau khi cài package cùng server ASGI:

```powershell
python -m pip install -e ".[dev]"
python -m uvicorn sheet_audit_agent.api:app --app-dir src --reload --port 8000
```

Endpoints:

- `GET /health`
- `POST /v1/audits`

## Nguyên tắc phát triển

- Logic agent độc lập với giao diện React và Google Sheets gateway.
- Mỗi capability có input, output và tiêu chí kiểm thử rõ ràng.
- Dữ liệu tên và tài chính được xử lý cục bộ trong MVP.
- Người dùng phải xác nhận trước mọi thay đổi dữ liệu.
- Kiến trúc cho phép bổ sung nhiều agent sau này nhưng MVP chưa cần orchestration phức tạp.

## Hướng mở rộng multi-agent

Khi có thêm capability, workspace có thể tách thành các agent chuyên trách:

- Agent kiểm tra chất lượng dữ liệu.
- Agent phân tích thu–chi.
- Agent lập báo cáo.
- Agent đề xuất và thực thi thay đổi sau khi người dùng xác nhận.
- Coordinator điều phối nhiệm vụ và tổng hợp kết quả.

Cấu trúc chi tiết sẽ được quyết định khi capability thứ hai xuất hiện, để tránh khóa dự án vào một framework hoặc giao thức quá sớm.
