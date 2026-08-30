# Kế hoạch TDD: Duplicate Detection Agent

## 1. Nguồn và phạm vi

- PRD: [duplicate-member-detection](../product/prd-duplicate-member-detection.md)
- Thiết kế: [duplicate-detection-agent](../technical/duplicate-detection-agent.design.md)
- Test runner của agent: pytest + pytest-cov. Ứng dụng tiếp tục dùng npm + Vitest, Testing Library và Playwright.
- Mục tiêu coverage: tối thiểu 80% branches, functions, lines và statements; không có test skip.

Kế hoạch này chưa phải bằng chứng PASS. Mỗi milestone phải ghi lại RED và GREEN thực tế khi triển khai.

## 2. User journeys

1. Là thủ quỹ, khi mở một sheet, tôi muốn agent tự rà soát tất cả bảng được nhận diện để không phải chọn vùng thủ công.
2. Là thủ quỹ, tôi muốn phân biệt trùng chắc chắn với trường hợp có thể sai chính tả/viết tắt để đánh giá đúng rủi ro.
3. Là thủ quỹ, tôi muốn biết vùng nào chưa được kiểm tra để không hiểu nhầm kết quả `clean`.
4. Là thủ quỹ, tôi muốn xem preview và tự chọn giá trị chuẩn trước khi phê duyệt sửa.
5. Là thủ quỹ, tôi muốn hệ thống từ chối ghi khi ô đã thay đổi để không ghi đè dữ liệu mới.
6. Là người chỉ có quyền xem, tôi muốn nhận kết quả audit nhưng không thể thực hiện thay đổi.

## 3. Thứ tự RED → GREEN

### Milestone 0 — Khởi tạo package và contract

RED:

- Test import `audit_sheet`, các contract và fixture; thất bại vì package/module chưa tồn tại.

GREEN tối thiểu:

- Tạo package Python 3.12 với `pyproject.toml`, Pydantic contracts và pytest.
- Tạo FastAPI boundary mỏng mà chưa thay đổi hành vi UI.

Validation:

```powershell
python -m pytest
python -m mypy src
```

### Milestone 1 — Chuẩn hóa văn bản

Test file: `agent/tests/test_normalization.py`

RED cases:

- `Nguyễn Văn An`, ` NGUYEN  VAN AN ` và `Nguyen-Van-An` có cùng khóa.
- `Đặng` chuyển thành `dang`.
- Nhiều khoảng trắng/dấu câu được gộp đúng.
- Chuỗi chỉ có khoảng trắng hoặc dấu câu trả khóa rỗng.
- Giá trị gốc không bị mutate.

GREEN tối thiểu: cài `normalizeText` đúng thứ tự trong thiết kế.

### Milestone 2 — Nhận diện bảng THU/CHI

Test file: `agent/tests/test_structure.py`

RED cases:

- Nhận diện bảng THU từ `HỌ VÀ TÊN` và các header đặc trưng.
- Nhận diện bảng CHI từ `NỘI DUNG CHI` hoặc `KHOẢN CHI`.
- Nhận diện cả hai bảng trong cùng sheet dù UI đang ở tab THU.
- Dùng hàng `TỔNG` làm điểm kết thúc.
- Không có `TỔNG`: region confidence thấp và report không được `clean`.
- Vùng không đủ tín hiệu xuất hiện trong `skippedRegions`.
- Header không dấu/chữ thường vẫn được nhận diện.

GREEN tối thiểu: detector dựa trên header/label, không hard-code duy nhất tọa độ hiện tại.

### Milestone 3 — Exact duplicate

Test file: `agent/tests/test_audit.py`

RED cases:

- Hai giá trị có cùng khóa tạo finding `exact`, confidence `1`.
- Ba biến thể nằm trong cùng finding.
- Tên trống, header và `TỔNG` bị bỏ qua.
- Một giá trị duy nhất không tạo finding.
- Không trùng xuyên sang sheet khác vì input chỉ chứa snapshot hiện tại.

GREEN tối thiểu: grouping bằng `Map`, kết quả ổn định theo vị trí dòng.

### Milestone 4 — Viết tắt và sai chính tả

Test files:

- `agent/tests/test_audit.py`

RED cases:

- `Nguyễn V. An` khớp `Nguyễn Văn An` dưới classification `possible-abbreviation`.
- Một viết tắt khớp nhiều tên trả tất cả ứng viên, không tự chọn.
- Typo similarity đúng tại biên `0.90`; dưới biên không tạo finding.
- Chuỗi ngắn hơn 4 ký tự không chạy typo matching.
- Tên có token đầu/cuối không tương thích không bị gộp do similarity toàn chuỗi.
- Một cặp thỏa exact không lặp lại ở abbreviation/typo.
- Không ghép transitive closure khi hai đầu không trực tiếp đạt ngưỡng.

GREEN tối thiểu: abbreviation matcher, normalized Levenshtein và bucket guardrails.

### Milestone 5 — Audit report và trạng thái partial

Test file: `agent/tests/test_audit.py`

RED cases:

- Sheet đủ dữ liệu, không finding trả `clean`.
- Có finding trả `findings`.
- Thiếu chunk, thiếu `TỔNG` hoặc có vùng không nhận diện trả `partial`, không trả `clean`.
- Report chứa inspected/skipped regions và snapshot revision.
- Abort signal dừng scan và không trả report hoàn tất.
- 1.000 dòng hoàn tất trong budget 500 ms ở benchmark test riêng, không dùng assertion thời gian quá chặt trong CI chia sẻ.

GREEN tối thiểu: pipeline detector → matcher → proposal builder.

### Milestone 6 — Gateway tải toàn bộ snapshot

Test file: `google-sheets-assistant/src/features/sheet-audit/sheet-audit-gateway.test.ts`

RED cases:

- Metadata 1.200 x 60 được chia chunk tối đa 500 x 50.
- Các chunk được ghép đúng tọa độ, không mất hoặc lặp cell.
- Một chunk lỗi làm snapshot incomplete; không trả snapshot complete.
- Abort khi đổi sheet hủy các request còn lại.
- Vượt 50.000 ô có dữ liệu trả lỗi giới hạn có thể hiển thị.
- Revision ổn định với cùng dữ liệu và đổi khi một ô đổi.

GREEN tối thiểu: adapter dùng `getGridWindow`; không sửa core agent.

### Milestone 7 — Controller tự động scan và chống race

Test file: `google-sheets-assistant/src/features/sheet-audit/audit-controller.test.ts`

RED cases:

- Sheet tải xong tự chuyển `loading -> scanning -> clean/findings` không cần click.
- Đổi sheet khi đang scan khiến kết quả cũ bị bỏ qua.
- Thêm/sửa/xóa dữ liệu chuyển report sang stale và tự scan lại sau reload.
- Lỗi tải/scan tạo trạng thái error có retry.
- Report partial hiển thị cảnh báo, không hiển thị thông điệp sạch.

GREEN tối thiểu: controller/runId độc lập React và không lưu pending approval vào session.

### Milestone 8 — Preview, approve và conflict check

Test files:

- `google-sheets-assistant/src/features/sheet-audit/audit-controller.test.ts`
- `google-sheets-assistant/src/features/sheet-audit/sheet-audit-gateway.test.ts`

RED cases:

- Không thể approve khi chưa chọn/nhập replacement.
- Preview hiển thị sheet, ô, expected và replacement.
- Approve đọc lại ô trước khi update.
- Giá trị nguồn khác expected trả `STALE_SOURCE` và không gọi update.
- Giá trị khớp gọi update đúng một ô.
- Update thành công kích hoạt load + full rescan.
- Update thất bại giữ proposal để review và không báo thành công.
- File read-only không gọi update.

GREEN tối thiểu: compare-before-write qua `readRange` và `updateValues` đã có trong Sheets gateway.

### Milestone 9 — UI và accessibility

Test file: `google-sheets-assistant/src/features/sheet-audit/AuditPanel.test.tsx`

RED cases:

- Hiển thị trạng thái đang rà soát bằng live region.
- Hiển thị số finding theo classification, explanation và confidence.
- Hiển thị inspected regions và skipped-region warning.
- Cho phép đi tới dòng, bỏ qua, chọn/nhập giá trị chuẩn và mở preview.
- Confirm ghi là thao tác tách biệt với mở preview.
- Read-only vẫn xem report nhưng không có nút ghi khả dụng.
- Không truyền đạt classification chỉ bằng màu sắc.

GREEN tối thiểu: component semantic, callback-based, không chứa matching logic.

### Milestone 10 — App integration và E2E

Test files:

- `google-sheets-assistant/src/app/App.test.tsx`
- `google-sheets-assistant/tests/e2e/sheet-audit.spec.ts`

RED journeys:

- Mở sheet fixture tự động scan cả THU và CHI.
- Exact, typo và abbreviation xuất hiện đúng nhãn.
- User chọn giá trị chuẩn, xem preview, approve và thấy kết quả audit mới.
- Conflict giả lập chặn ghi và yêu cầu scan lại.
- Đổi sheet giữa lúc scan không hiển thị finding của sheet cũ.
- File read-only không thể approve.
- Partial load không hiển thị “không phát hiện lỗi”.

GREEN tối thiểu: nối controller/panel vào App, fake dependencies hỗ trợ read/update và race fixtures.

## 4. Ma trận guarantee

| Guarantee | Unit | Integration/component | E2E |
|---|---:|---:|---:|
| Chuẩn hóa dấu, khoảng trắng, dấu câu | Có | — | — |
| Nhận diện THU và CHI tự động | Có | Có | Có |
| Exact/typo/abbreviation đúng classification | Có | Có | Có |
| Không báo clean khi scan thiếu | Có | Có | Có |
| Tự scan và bỏ kết quả race | — | Có | Có |
| Preview + explicit approval | — | Có | Có |
| Compare-before-write | — | Có | Có |
| Read-only không ghi | — | Có | Có |
| Accessibility của audit panel | — | Có | Smoke |

## 5. Quy tắc thực thi TDD

Với từng milestone:

1. Viết test cho đúng behavior của milestone.
2. Chạy riêng test target và xác nhận RED do thiếu behavior, không phải lỗi setup.
3. Ghi lại command cùng output RED.
4. Viết production code tối thiểu.
5. Chạy lại cùng target và xác nhận GREEN.
6. Refactor khi test vẫn xanh.
7. Chạy test liên quan, typecheck và lint.

Không tạo commit tự động nếu người dùng chưa yêu cầu. Nếu cần checkpoint commit, dùng commit RED/GREEN riêng như hướng dẫn TDD.

## 6. Lệnh validation dự kiến

Các lệnh sẽ được xác nhận lại sau khi package `agent` có `package.json`:

```powershell
# Agent unit/API tests
python -m pytest
python -m pytest --cov=sheet_audit_agent --cov-report=term-missing
python -m ruff check .
python -m mypy src

# App integration/component
npm test -- src/features/sheet-audit src/app/App.test.tsx
npm run typecheck
npm run lint
npm run test:coverage

# Critical browser flow
npm run test:e2e -- tests/e2e/sheet-audit.spec.ts
```

Chạy nhóm đầu trong `D:\connect_to_excel\agent`; hai nhóm sau trong `D:\connect_to_excel\google-sheets-assistant`.

## 7. Exit criteria

- Tất cả milestone có bằng chứng RED rồi GREEN.
- Không có test skip hoặc only.
- Coverage agent core và phần app thay đổi đạt tối thiểu 80% cho cả bốn chỉ số.
- Typecheck, lint, unit/component và E2E quan trọng đều pass.
- Manual smoke với test Google account xác nhận tự scan và approve không ghi nhầm ô.
- Tạo evidence report tại `agent/docs/testing/duplicate-detection-agent.tdd.md` với command/output thực tế; không ghi PASS khi chưa chạy.
