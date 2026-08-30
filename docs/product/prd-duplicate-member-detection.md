# PRD: Agent phát hiện tên trùng lặp trong bảng thu–chi

**Owner:** Agent workspace

## 1. Capability

Khi người quản lý quỹ mở một sheet, trợ lý tự động rà soát toàn bộ dữ liệu có cấu trúc trong sheet đó, tự nhận diện các bảng và cột có nội dung cần kiểm tra. Người dùng không phải chỉ định bảng, cột hoặc vùng dữ liệu. Trợ lý phát hiện cả trường hợp trùng chắc chắn và trường hợp có khả năng trùng do sai chính tả hoặc viết tắt, sau đó đề xuất cách sửa để người dùng phê duyệt hoặc tự sửa.

## 2. Người dùng và vấn đề

- Người dùng chính: thủ quỹ hoặc người quản lý danh sách đóng quỹ, không cần hiểu công thức Google Sheets.
- Hiện trạng: người dùng dò tên bằng mắt; khác biệt về chữ hoa, dấu tiếng Việt hoặc khoảng trắng khiến tên trùng khó nhận ra.
- Nhu cầu: biết dòng nào chắc chắn trùng và dòng nào chỉ có khả năng trùng, nhưng không để hệ thống tự ý sửa dữ liệu.

## 3. Mục tiêu MVP

- Tự động rà soát toàn bộ sheet đang mở mà không yêu cầu người dùng chọn phạm vi.
- Tự nhận diện và kiểm tra các bảng dữ liệu có cấu trúc, bao gồm cả bảng THU và bảng CHI khi chúng tồn tại.
- Phát hiện dữ liệu trùng chắc chắn và các trường hợp có khả năng trùng do sai chính tả hoặc viết tắt.
- Hiển thị tên gốc, số dòng và dữ liệu thu liên quan của từng nhóm trùng.
- Cho phép người dùng mở/chọn dòng cần kiểm tra.
- Thông báo và tạo đề xuất sửa; chỉ ghi vào Google Sheets sau khi người dùng phê duyệt rõ ràng.

## 4. Luồng người dùng

1. Người dùng kết nối Google và mở một spreadsheet cùng sheet.
2. Ngay sau khi dữ liệu tải xong, agent tự nhận diện cấu trúc và rà soát toàn bộ sheet.
3. Giao diện hiển thị trạng thái đang kiểm tra và các bảng/cột agent đã nhận diện.
4. Hệ thống hiển thị một trong ba kết quả:
   - Không phát hiện tên trùng.
   - Phát hiện một hoặc nhiều nhóm trùng.
   - Không thể kiểm tra, kèm hướng dẫn thử lại.
5. Với mỗi nhóm, người dùng xem dữ liệu gốc, vị trí dòng, lý do bị đánh dấu, mức tin cậy và đề xuất sửa.
6. Người dùng có thể **Phê duyệt đề xuất**, **Bỏ qua** hoặc tự sửa trực tiếp.
7. Trước khi ghi, hệ thống hiển thị preview giá trị cũ/mới và kiểm tra dữ liệu nguồn chưa thay đổi.

## 5. Quy tắc nghiệp vụ

### 5.1 Phạm vi dữ liệu

- Chỉ kiểm tra sheet đang mở; không tự động đọc hoặc đối chiếu sheet khác.
- Agent tự rà soát toàn bộ vùng dữ liệu có cấu trúc trong sheet, không phụ thuộc tab THU/CHI đang được chọn trên giao diện.
- Với bảng THU, trường mặc định cần kiểm tra là **Họ và tên**. Với bảng CHI, trường mặc định cần kiểm tra là **Nội dung chi**.
- Agent phải báo rõ các bảng/cột đã nhận diện và các vùng bị bỏ qua do không xác định được cấu trúc.
- Không được trả kết quả `clean` nếu chưa quét hết các vùng dữ liệu đã nhận diện trong sheet.
- Bỏ qua hàng tiêu đề, hàng `TỔNG` và ô tên trống.
- Mỗi kết quả phải giữ số dòng theo Google Sheets (chỉ số hiển thị bắt đầu từ 1), không dùng STT làm định danh duy nhất.
- Kết quả được tính lại từ dữ liệu vừa tải; không dùng kết quả cũ sau khi sheet thay đổi.

### 5.2 Chuẩn hóa tên

Để tìm nhóm trùng chính xác, hệ thống tạo khóa so sánh theo thứ tự:

1. Chuẩn hóa Unicode về NFD.
2. Bỏ dấu tiếng Việt; chuyển `đ`/`Đ` thành `d`.
3. Chuyển về chữ thường.
4. Xóa khoảng trắng đầu/cuối.
5. Gộp nhiều khoảng trắng liên tiếp thành một khoảng trắng.
6. Bỏ dấu câu phân cách thông dụng như `.`, `,`, `-`, `_` khi chúng không làm thay đổi các từ trong tên.

Ví dụ cùng một khóa: `Nguyễn Văn An`, ` NGUYEN  VAN AN ` và `Nguyen-Van-An`.

### 5.3 Phân loại kết quả

- **Trùng chắc chắn**: ít nhất hai tên có cùng khóa sau chuẩn hóa.
- **Có khả năng trùng — sai chính tả**: tên khác nhau một số ít ký tự nhưng có cấu trúc từ đủ gần nhau, ví dụ đảo hoặc thiếu một ký tự. Kết quả phải nêu rõ ký tự/từ khác biệt.
- **Có khả năng trùng — viết tắt**: một tên chứa chữ cái đầu hoặc dạng rút gọn tương thích với tên còn lại, ví dụ `Nguyễn V. An` và `Nguyễn Văn An`.
- Ngưỡng khởi điểm cho sai chính tả là độ tương đồng chuỗi chuẩn hóa từ `0.90` trở lên. Ngưỡng phải được khai báo tập trung để có thể hiệu chỉnh bằng dữ liệu thực tế mà không thay đổi luồng sản phẩm.
- Nếu một tên viết tắt khớp với nhiều tên, agent hiển thị tất cả ứng viên đủ điều kiện cùng mức tin cậy; không tự chọn một ứng viên.
- Tên gần giống không được coi là kết luận chắc chắn. Ví dụ `Nguyễn Văn An` và `Nguyễn Văn Anh` chỉ được đưa vào diện cần xem xét nếu vượt ngưỡng cấu hình, kèm lý do và mức tin cậy.
- Một dòng chỉ xuất hiện một lần trong một nhóm kết quả.
- Nhóm được sắp xếp theo dòng xuất hiện đầu tiên; các dòng trong nhóm sắp xếp tăng dần.

### 5.4 Đề xuất và phê duyệt

- Agent đề xuất giá trị chuẩn cho từng dòng nhưng không tự ghi dữ liệu.
- Người dùng chọn giá trị chuẩn từ các ứng viên hoặc nhập một giá trị khác trước khi phê duyệt; agent không mặc định lấy dòng đầu tiên.
- Người dùng có thể phê duyệt từng đề xuất; không gộp nhiều thay đổi vào một lần phê duyệt mặc định.
- Preview phải hiển thị sheet, ô, giá trị hiện tại và giá trị đề xuất.
- Khi người dùng phê duyệt, hệ thống đọc lại ô nguồn. Nếu giá trị đã thay đổi, từ chối ghi và yêu cầu kiểm tra lại.
- Người dùng có thể bỏ qua đề xuất hoặc tự sửa; agent không được coi thao tác bỏ qua là phê duyệt.
- MVP chỉ sửa chuỗi nội dung bị nghi trùng; không tự cộng tiền, gộp dòng hoặc xóa dòng.

## 6. Yêu cầu giao diện

- Agent tự chạy sau khi sheet tải xong; nút **Kiểm tra lại** cho phép người dùng chủ động chạy lại khi cần.
- Kết quả hiển thị số nhóm và tổng số dòng liên quan, ví dụ: `Phát hiện 2 nhóm trùng, liên quan 5 dòng`.
- Mỗi nhóm hiển thị:
  - Tên đại diện.
  - Các biến thể tên gốc.
  - Số dòng trên sheet.
  - Dữ liệu liên quan trong bảng.
  - Loại phát hiện, lý do và mức tin cậy.
  - Giá trị sửa được đề xuất.
- Có hành động **Đi tới dòng** hoặc làm nổi bật thẻ thành viên tương ứng.
- Có hành động **Phê duyệt**, **Bỏ qua** và hướng dẫn **Tự sửa**.
- Có hành động **Kiểm tra lại**.
- Kết quả không được dùng màu sắc làm dấu hiệu duy nhất; cần nhãn văn bản và hỗ trợ đọc màn hình.

## 7. Trạng thái và chuyển đổi

- `idle`: chưa chạy kiểm tra.
- `scanning`: đang phân tích snapshot dữ liệu hiện tại.
- `clean`: hoàn tất, không có nhóm trùng.
- `duplicates-found`: hoàn tất, có nhóm trùng.
- `reviewing`: người dùng đang xem hoặc chỉnh đề xuất.
- `applying`: đang kiểm tra lại dữ liệu và ghi một đề xuất đã được phê duyệt.
- `applied`: đề xuất đã được ghi thành công; kết quả còn lại chuyển sang `stale` và cần kiểm tra lại.
- `stale`: dữ liệu sheet đã được tải lại hoặc sửa sau lần kiểm tra; kết quả cũ không còn hiệu lực.
- `error`: thiếu dữ liệu cần thiết hoặc không đọc được sheet; người dùng có thể thử lại.

Mọi thao tác thêm, sửa, xóa thành viên hoặc tải lại grid phải chuyển kết quả hiện tại sang `stale` hoặc tự động chạy lại kiểm tra.

## 8. Hợp đồng triển khai

### Đầu vào

- `GridWindow` của sheet hiện tại.
- Metadata và toàn bộ các vùng dữ liệu có cấu trúc của sheet đang mở.
- Vị trí hàng tiêu đề, hàng `TỔNG` và các cột nội dung được bộ nhận diện cấu trúc tìm thấy.
- Snapshot/version của dữ liệu nguồn để kiểm tra xung đột trước khi ghi.

### Đầu ra đề xuất

```ts
type DuplicateMember = {
  rowIndex: number
  sheetRow: number
  columnIndex: number
  originalValue: string
  normalizedValue: string
  relatedValues: Record<string, string>
}

type DuplicateGroup = {
  normalizedName: string
  classification: 'exact' | 'possible-typo' | 'possible-abbreviation'
  confidence: number
  explanation: string
  suggestedValue: string
  members: DuplicateMember[]
}
```

Hàm phát hiện phải là hàm thuần, không gọi Google API và không sửa `GridWindow`. UI chịu trách nhiệm hiển thị; `App`/gateway chịu trách nhiệm tải snapshot đầy đủ và áp dụng thay đổi đã được phê duyệt.

### Ràng buộc dữ liệu

- `GridWindow` hiện mặc định chỉ tải 100 dòng và 26 cột. Trước khi cam kết đã rà soát toàn bộ sheet, triển khai phải tải đủ các vùng có dữ liệu hoặc phân trang và tổng hợp kết quả.
- Bộ nhận diện cấu trúc dùng tiêu đề cột đã biết, nhãn bảng như `THU`/`CHI`, hàng `TỔNG` và ranh giới ô có dữ liệu. Vùng không đạt đủ tín hiệu phải được báo là chưa nhận diện, không được âm thầm bỏ qua hoặc suy đoán.
- Phát hiện chính xác và sinh ứng viên gần giống phải chạy cục bộ. Nếu sau này dùng LLM để giải thích/xếp hạng, cần một quyết định riêng về nhà cung cấp, sự đồng ý của người dùng và chính sách dữ liệu trước khi gửi bất kỳ dữ liệu nào ra ngoài.
- File chỉ có quyền xem vẫn được phép chạy kiểm tra.
- File chỉ có quyền xem không hiển thị hành động phê duyệt ghi; người dùng vẫn có thể xem đề xuất và tự sửa ở nơi có quyền phù hợp.

## 9. Xử lý lỗi

- Không tìm thấy cột tên hoặc hàng `TỔNG`: thông báo cấu trúc bảng chưa được hỗ trợ, không trả kết quả “không trùng”.
- Phiên Google hết hạn: dùng luồng kết nối lại hiện có.
- Chỉ tải được một phần dữ liệu: thông báo kết quả chưa đầy đủ và không gắn trạng thái `clean`.
- Tên chỉ gồm khoảng trắng hoặc dấu câu: coi là trống và bỏ qua.
- Dữ liệu thay đổi sau lúc tạo đề xuất: từ chối ghi, đánh dấu kết quả `stale` và yêu cầu kiểm tra lại.
- Ghi thất bại: giữ nguyên đề xuất, thông báo lỗi và không tuyên bố dữ liệu đã được sửa.

## 10. Tiêu chí nghiệm thu

1. `Nguyễn Văn An` và ` NGUYEN  VAN AN ` được đặt trong cùng một nhóm.
2. `Trần Thị B` và `tran-thi-b` được đặt trong cùng một nhóm.
3. `Nguyễn V. An` và `Nguyễn Văn An` được cảnh báo là có khả năng trùng do viết tắt, không phải trùng chắc chắn.
4. Một biến thể sai một ký tự được cảnh báo là có khả năng sai chính tả và hiển thị phần khác biệt.
5. Tên gần giống nhưng không đủ bằng chứng không bị tự động sửa hoặc gắn nhãn trùng chắc chắn.
6. Tên trống, hàng tiêu đề và hàng `TỔNG` không xuất hiện trong kết quả.
7. Sau khi sheet tải xong, agent tự kiểm tra mà người dùng không phải chọn bảng, cột hoặc vùng.
8. Nếu sheet có cả bảng THU và CHI, agent kiểm tra cả hai dù giao diện đang hiển thị tab nào.
9. Agent không đọc sheet khác với sheet đang mở.
10. Agent hiển thị các vùng đã kiểm tra và cảnh báo vùng không nhận diện được.
11. Nhóm kết quả hiển thị đúng số dòng Google Sheets, dữ liệu liên quan, lý do và mức tin cậy.
12. Người dùng có thể phê duyệt một đề xuất sau khi xem preview cũ/mới.
13. Không có thay đổi nào được ghi khi chưa có phê duyệt rõ ràng.
14. Nếu ô nguồn thay đổi sau khi tạo đề xuất, hệ thống từ chối ghi.
15. Sau khi sửa hoặc thêm dữ liệu, kết quả trước đó không còn được coi là hiện hành và agent tự rà soát lại.
16. Kiểm tra hoạt động với file chỉ có quyền xem nhưng không cho phép ghi.
17. Nếu dữ liệu vượt quá cửa sổ tải hiện tại, kết quả vẫn bao phủ toàn bộ vùng có dữ liệu hoặc cảnh báo rõ rằng chưa thể kiểm tra đầy đủ.

## 11. Chỉ số thành công

- 100% ca trùng theo quy tắc chuẩn hóa trong bộ test được phát hiện.
- 100% kết quả gần giống được gắn nhãn “có khả năng”, có lý do và không tự động sửa.
- Theo dõi tỷ lệ đề xuất được người dùng phê duyệt, bỏ qua và tự sửa để hiệu chỉnh ngưỡng sau MVP.
- Kết quả cho 1.000 dòng xuất hiện trong dưới 500 ms sau khi dữ liệu đã tải trên thiết bị phổ thông.
- Ít nhất 90% phiên kiểm tra kết thúc ở `clean` hoặc `duplicates-found`, không phải `error` hay kết quả một phần.

## 12. Ngoài phạm vi MVP

- Tự động gộp hoặc xóa dòng trùng.
- Tự động áp dụng đề xuất khi chưa có phê duyệt rõ ràng.
- Đối chiếu danh tính bằng số điện thoại, email hoặc mã thành viên.
- Kiểm tra đồng thời nhiều sheet hoặc nhiều spreadsheet.
- Chạy nền, gửi thông báo hoặc lưu lịch sử kiểm tra.

## 13. Quyết định đã chốt

- Agent tự rà soát toàn bộ sheet đang mở và không yêu cầu người dùng chọn phạm vi.
- Cấu trúc bảng được nhận diện bằng tiêu đề, nhãn `THU`/`CHI`, hàng `TỔNG` và ranh giới dữ liệu.
- Sai chính tả dùng ngưỡng tương đồng khởi điểm `0.90` và luôn được gắn nhãn “có khả năng”.
- Viết tắt có nhiều cách diễn giải phải hiển thị tất cả ứng viên, không tự chọn.
- Người dùng tự chọn hoặc nhập giá trị chuẩn trước khi phê duyệt.
- Mọi thay đổi đều cần preview và phê duyệt rõ ràng.

Không còn câu hỏi sản phẩm chặn MVP. Ngưỡng có thể được hiệu chỉnh sau khi đo trên bộ dữ liệu thực tế.

## 14. Handoff

PRD sẵn sàng chuyển sang thiết kế kỹ thuật và TDD. Các hạng mục gồm: tải toàn bộ dữ liệu, nhận diện bảng/cột, bộ chuẩn hóa và so khớp gần với ngưỡng cấu hình, tạo đề xuất, preview/approve có kiểm tra xung đột, UI kết quả và kiểm thử unit/component/E2E.
