# Thiết kế kỹ thuật: Duplicate Detection Agent

## 1. Mục tiêu

Xây dựng một agent chạy trong trình duyệt, tự rà soát toàn bộ sheet Google Sheets đang mở, phát hiện nội dung trùng chắc chắn hoặc có khả năng trùng do sai chính tả/viết tắt, rồi tạo đề xuất sửa có preview và phê duyệt từng thay đổi.

Nguồn yêu cầu: [PRD](../product/prd-duplicate-member-detection.md).

## 2. Quyết định kiến trúc

- Agent là package Python 3.12 độc lập tại `D:\connect_to_excel\agent`, không đặt business logic trong React component.
- Package không phụ thuộc React, Google SDK hoặc LLM; core là các hàm thuần và được kiểm thử bằng pytest.
- FastAPI cung cấp HTTP boundary mỏng; không đặt thuật toán trong route handler.
- `google-sheets-assistant` giữ trách nhiệm OAuth, đọc/ghi Google Sheets, lifecycle của sheet và UI; ứng dụng gửi snapshot tới agent API.
- Agent nhận snapshot dữ liệu trung lập, trả audit report cùng đề xuất; agent không nhận Google access token và không tự ghi dữ liệu.
- MVP chỉ có một audit agent. Interface dùng dạng capability để sau này coordinator có thể điều phối nhiều agent mà không thay đổi contract hiện tại.

## 3. Ranh giới hệ thống

```text
Google Sheets API
      |
SheetsGateway: metadata, read snapshot, conditional write
      |
App audit controller: load -> scan -> review -> approve -> rescan
      |
Python Sheet Audit Agent API
  structure detector -> normalizer -> matcher -> proposal builder
      |
React audit panel
```

Không có backend, database hoặc lưu lịch sử audit trong MVP.

## 4. Cấu trúc mã đề xuất

```text
agent/
  pyproject.toml
  src/
    sheet_audit_agent/
      api.py
      audit.py
      models.py
      matching.py
      structure.py
  tests/
    test_api.py
    test_audit.py
    test_normalization.py
    test_structure.py
google-sheets-assistant/src/features/sheet-audit/
  audit-controller.ts
  AuditPanel.tsx
  AuditPanel.test.tsx
```

Tên package Python: `sheet-audit-agent`, import path `sheet_audit_agent`. Ứng dụng React gọi `POST /v1/audits`; local development dùng URL cấu hình qua biến môi trường, không import source Python vào Vite.

## 5. Contracts

```python
class SheetCell(BaseModel):
    row: int
    column: int
    formatted_value: str
    user_entered_value: str | int | float | bool | None = None


class SheetSnapshot(BaseModel):
    spreadsheet_id: str
    sheet_id: int
    sheet_title: str
    row_count: int
    column_count: int
    revision: str
    complete: bool
    cells: list[SheetCell]


class AuditFinding(BaseModel):
    id: str
    classification: Literal["exact", "possible-typo", "possible-abbreviation"]
    confidence: float
    explanation: str
    candidates: list[FindingCandidate]
    suggested_values: list[str]


class AuditReport(BaseModel):
    snapshot_revision: str
    status: Literal["clean", "findings", "partial"]
    inspected_regions: list[DetectedRegion]
    skipped_regions: list[SkippedRegion]
    findings: list[AuditFinding]
```

## 6. Pipeline rà soát

### 6.1 Tải snapshot đầy đủ

1. Sau khi chọn sheet, controller lấy `rowCount` và `columnCount` từ metadata.
2. Gateway tải toàn bộ vùng có thể chứa dữ liệu theo từng chunk, đề xuất tối đa `500 x 50` ô/request.
3. Controller ghép chunk theo tọa độ và tạo `revision` từ `sheetId` cùng hash ổn định của tọa độ + giá trị ô.
4. Chỉ bắt đầu audit khi mọi chunk thành công. Nếu thiếu chunk, report là `partial`, tuyệt đối không trả `clean`.
5. Request cũ bị hủy bằng `AbortController` khi người dùng đổi sheet.

Giới hạn an toàn MVP: tối đa 50.000 ô có dữ liệu/phiên audit. Vượt giới hạn phải báo `partial` thay vì khóa trình duyệt.

### 6.2 Nhận diện cấu trúc

Detector chuẩn hóa nội dung header rồi tìm các tín hiệu:

- Nhãn bảng: `THU`, `CHI`.
- Header THU: `STT`, `HỌ VÀ TÊN`, `QUỸ HỘI`, `QUỸ KHÁC`, `GHI CHÚ`, `HÌNH THỨC`.
- Header CHI: `STT`, `NỘI DUNG CHI` hoặc `KHOẢN CHI`, `SỐ TIỀN`, `GHI CHÚ`, `HÌNH THỨC`.
- Điểm kết thúc ưu tiên hàng có nhãn `TỔNG`; nếu không có, dùng dòng có dữ liệu cuối cùng nhưng đánh dấu region confidence thấp và report `partial`.

Một region được audit khi có ít nhất nhãn bảng hoặc hai header đặc trưng, đồng thời xác định được cột nội dung. Các vùng còn lại được đưa vào `skippedRegions`.

### 6.3 Chuẩn hóa

`normalizeText` thực hiện theo thứ tự:

1. `trim` và Unicode NFD.
2. Bỏ dấu kết hợp và chuyển `đ` thành `d`.
3. Chuyển chữ thường.
4. Thay `.`, `,`, `-`, `_` bằng khoảng trắng.
5. Gộp khoảng trắng.

Giữ cả giá trị gốc và giá trị chuẩn hóa; không dùng khóa chuẩn hóa làm giá trị ghi ngược vào sheet.

### 6.4 Matching

Pipeline chạy theo độ chắc chắn giảm dần:

1. Exact: nhóm các giá trị có khóa chuẩn hóa bằng nhau; confidence `1.0`.
2. Abbreviation: so khớp token đầy đủ với token một ký tự/chữ cái đầu; trả tất cả ứng viên hợp lệ, không tự chọn; confidence tối đa `0.95`.
3. Typo: dùng normalized Levenshtein similarity `1 - distance / maxLength`; chỉ tạo finding khi điểm `>= 0.90`; confidence bằng điểm tính được.

Guardrail giảm false positive:

- Không so typo khi một bên ngắn hơn 4 ký tự.
- Với tên người, token đầu và token cuối phải tương thích; nếu không, chỉ giữ kết quả khi abbreviation rule khớp rõ ràng.
- Không ghép hai finding bằng transitive closure nếu cặp đầu-cuối không trực tiếp vượt ngưỡng.
- Mỗi cặp chỉ thuộc classification có độ ưu tiên cao nhất: exact, abbreviation, rồi typo.

### 6.5 Đề xuất

- Exact: `suggestedValues` chứa các biến thể gốc duy nhất; UI yêu cầu người dùng chọn.
- Abbreviation/typo: ưu tiên các giá trị đầy đủ hơn nhưng vẫn hiển thị mọi ứng viên.
- Người dùng có thể nhập giá trị khác.
- Không tạo request ghi cho đến khi người dùng chọn một candidate row, nhập/chọn replacement và phê duyệt preview.

## 7. Lifecycle và state machine

```text
idle -> loading -> scanning -> clean
                         \-> findings -> reviewing -> applying -> loading
              \-> partial
loading/scanning/applying -> error
mọi thay đổi dữ liệu hoặc đổi sheet -> stale -> loading
```

- Mỗi run có `runId`; response của run cũ không được cập nhật state.
- Sau một correction thành công, controller tải snapshot mới và audit lại toàn bộ sheet.
- Không lưu report hoặc pending approval vào `sessionStorage`.

## 8. Ghi có kiểm tra xung đột

Trước khi ghi một correction:

1. Gateway đọc lại đúng ô đích.
2. So sánh giá trị hiện tại với `expectedValue` và xác nhận sheet vẫn là sheet trong preview.
3. Nếu khác, trả `STALE_SOURCE`; không ghi và chạy audit lại.
4. Nếu giống, gọi `updateValues` cho đúng một ô với replacement đã phê duyệt.
5. Nếu ghi thành công, tải và audit lại sheet.

MVP phê duyệt từng correction; không batch nhiều finding trong một request.

## 9. Thay đổi cần có trong ứng dụng hiện tại

- Mở rộng `SheetsClient` trong `App.tsx` với `readRange` và `updateValues`, hoặc tạo `SheetAuditGateway` riêng dùng các hàm đã tồn tại trong `sheets-gateway.ts`.
- Tách logic audit orchestration khỏi `App.tsx` sang `audit-controller.ts` hoặc custom hook để tránh tăng kích thước component hiện đã lớn.
- `FundTableWorkspace` phát sự kiện khi dữ liệu thay đổi; controller đánh dấu stale và tự chạy lại sau khi reload hoàn tất.
- Thêm `AuditPanel` bên cạnh workspace, có live region cho trạng thái scan và kết quả.
- Fake dependencies phải chứa sheet fixture có cả THU, CHI, exact duplicate, typo và abbreviation.

## 10. Bảo mật và riêng tư

- Không gửi nội dung sheet tới LLM hoặc dịch vụ ngoài Google Sheets API.
- Không log tên, số tiền hoặc nội dung ô vào console/telemetry.
- Access token tiếp tục do auth layer hiện tại quản lý; agent package không nhận token.
- Quyền chỉ đọc: audit được phép chạy, mọi nút ghi bị vô hiệu hóa.
- Preview không được sống lâu hơn snapshot tạo ra nó.

## 11. Hiệu năng

- Audit core: dưới 500 ms cho 1.000 dòng trên thiết bị phổ thông.
- Exact matching dùng map, độ phức tạp gần `O(n)`.
- Fuzzy matching chỉ chạy trên bucket có token đầu/cuối tương thích để tránh `O(n²)` toàn cục.
- Quá trình scan nhường event loop theo batch nếu vượt 2.000 candidate; UI vẫn phản hồi.

## 12. Khả năng quan sát

Chỉ ghi metric không chứa dữ liệu người dùng:

- thời gian tải và scan;
- số ô, region, finding theo classification;
- số report `clean`, `findings`, `partial`, `error`;
- số proposal approved, ignored, stale và failed.

Không log original value, normalized value hoặc replacement value.

## 13. Failure modes

- Thiếu chunk/Google rate limit: `partial`, có retry; không báo clean.
- Không nhận diện được region: liệt kê vùng bỏ qua và lý do.
- Sheet đổi trong lúc scan: bỏ kết quả run cũ.
- Ô đổi trước approve: `STALE_SOURCE`, không ghi.
- Update thất bại: giữ proposal ở trạng thái review, không báo thành công.
- Sheet read-only: scan bình thường, không cho approve ghi.

## 14. Khả năng mở rộng multi-agent

Contract tương lai:

```ts
class SheetAgent(Protocol):
    id: str
    capabilities: tuple[str, ...]

    def audit(self, snapshot: SheetSnapshot) -> AuditReport: ...
```

Coordinator tương lai chỉ nhận snapshot bất biến, gọi nhiều agent và hợp nhất report. Không triển khai coordinator, memory, tool-calling hoặc agent-to-agent protocol trong MVP.

## 15. Handoff

Thiết kế sẵn sàng cho TDD theo các milestone trong [kế hoạch TDD](../testing/duplicate-detection-agent.tdd-plan.md). Không sửa production code trước khi xác nhận RED cho milestone tương ứng.
