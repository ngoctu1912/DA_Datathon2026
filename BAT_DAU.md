# Bắt đầu — Bản chỉ lưu kết quả phân cụm và mô hình cần thiết

## Trong model chỉ còn hai file

`data/model/phan_khuc/combined_v1/`

| File | Vai trò |
|---|---|
| ket_qua_phan_cum.csv | Kết quả chính: mã khách, Recency, Frequency, Monetary, mã cụm và tên nhóm |
| mo_hinh_phan_cum.json | Tham số mô hình đã chọn: biến đầu vào, chuẩn hóa, tâm, bảng đổi nhãn, mốc ngày, nguồn và phiên bản |

**Không dùng ZIP mô hình, không có thư mục v1 cũ, không lưu hàng loạt CSV/JSON thử nghiệm.** CSV phân cụm là đầu ra chính được lưu. JSON là mô hình có thể dùng lại, không phải báo cáo phụ; nó đủ để tái tạo nhãn từ RFM mà không phải huấn luyện lại K-Means đã chọn.

Các bảng thử nghiệm, kiểm seed, đối chứng và độ nhạy được tính khi cần và chỉ giữ tạm trong phiên làm việc. Có thể chạy notebook riêng, nhưng một số bảng sẽ cần tính lại vì không lưu lâu dài. Dữ liệu làm việc tạm của hệ thống tự dọn khi kết thúc kernel; không rải chúng vào thư mục model.

## Cách chạy

Mở thư mục dự án, Python 3.11 trở lên, chọn đúng kernel:

```powershell
python -m pip install -r requirements.txt
```

Run All theo PC01 → PC06 trong `notebook/05_phan_khuc_khach_hang`. Các notebook tự nạp `00_ham_ho_tro_phan_cum.ipynb`; không phải chạy 00 trước. Hàm Python chung của nhóm giữ nguyên bản; không có script Python mới.

- PC01: kiểm đầu vào và RFM, trạng thái, phạm vi.
- PC02: phân bố, ngoại lệ, chuẩn hóa/log, hành vi.
- PC03: tính lại 14 cấu hình và 36 đối chứng để hiển thị; nếu chọn lượt mới sẽ huấn luyện và lưu hai file chính.
- PC04: mô tả nhóm, hủy/trả, giỏ hàng và đối chiếu số cụm.
- PC05: tính độ nhạy và đối chiếu phương án; không lưu bảng độ nhạy vào model.
- PC06: đề xuất chiến lược/KPI và lưu tên phân khúc vào CSV chính nếu thay đổi.

RFM và hồ sơ được dựng lại từ raw/common, gắn với nhãn/tham số đã lưu và kiểm chứng. Không dùng lại v1 cũ. Khi thư viện hoặc dữ liệu thay đổi, cách fit lại các ứng viên có thể khác; không tự thay mô hình đã lưu. Nếu kiểm chứng không đạt, phải nghiệm thu/huấn luyện lượt mới.

## Huấn luyện một lượt mới

Trước ô thiết lập ở PC03–PC06, dùng cùng một tên mới:

```python
import os
os.environ['DATATHON_MODEL_RUN'] = 'combined_v2'
```

Lượt đó cũng chỉ lưu CSV kết quả và JSON tham số. Không ghi đè lượt hoàn tất cũ. Nếu chưa có mô hình mặc định, PC01–PC02 có thể tạo RFM/hành vi từ raw/common trong bộ nhớ; PC03 mới huấn luyện.

## Báo cáo phụ và kiểm thử

Mặc định không xuất ảnh, bảng đánh giá hoặc JSON báo cáo. Chỉ khi chủ động cần xuất báo cáo, đặt trước ô khởi tạo Study:

```python
import os
os.environ['DATATHON_EXPORT_REPORTS'] = '1'
```

Đặt lại `'0'` và khởi tạo Study mới để tắt. Có thể xóa `reports/` mà không ảnh hưởng notebook. Không xóa CSV phân cụm, JSON mô hình, raw/common hoặc notebook hỗ trợ khi còn cần dùng lại.

Sau khi Run All và Save PC01–PC06, kiểm thử trong một ô:

```python
result = kiem_thu_phan_cum()
assert result.wasSuccessful()
```

Kiểm thử sẽ tính lại các bảng đánh giá cần kiểm, không xuất chúng vào model. Nếu thiếu common CSV, chạy GD2 rồi gọi `chuan_bi_phan_cum()` sau ô thiết lập. Restart Kernel khi sửa notebook hỗ trợ.

## Kết quả và giới hạn

K-Means TN1, k=3; 85.115 khách có 516.716 đơn delivered đến 31/12/2022. Monetary là Net sau giảm giá, không lợi nhuận/thực thu/CLV. Silhouette dùng mẫu 5.000, DB/inertia toàn tập; đối chứng bốn thuật toán dùng cùng mẫu/scaler mẫu TN1. Chưa có đánh giá theo thời gian tương lai hoặc hiệu quả chiến lược thực tế.

Toàn bộ dự án được đóng trong một file ZIP để tải về. Hãy giải nén vào thư mục mới rồi mở thư mục DA_Datathon2026. Không giải nén đè lên bản cũ vì các file kết quả cũ sẽ không tự được xóa. Bên trong thư mục model chỉ có hai file được nêu ở đầu tài liệu; không có ZIP mô hình riêng. Dữ liệu raw/common và file Python dùng chung của nhóm được giữ nguyên.
