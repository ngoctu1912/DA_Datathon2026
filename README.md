# Datathon 2026 Round 1 — Phân tích dữ liệu bán lẻ

Mở `notebook/` và đọc theo số thứ tự. Mỗi notebook trình bày mục tiêu, mã phân tích và kết quả ngay cạnh nhau. Nguồn dữ liệu của đồ án là [Datathon 2026 Round 1 trên Kaggle](https://www.kaggle.com/competitions/datathon-2026-round-1/data).

| Bước | Mở trước | Nội dung |
| --- | --- | --- |
| 01. Tìm hiểu dữ liệu | [01. Khảo sát dữ liệu](notebook/01_tim_hieu_du_lieu/01_khao_sat_du_lieu.ipynb) → [GD1](notebook/01_tim_hieu_du_lieu/GD1_tong_hop_kiem_chung.ipynb) | Khảo sát 14 bảng nguồn trước, rồi đọc các kiểm chứng V01–V09. |
| 02. Tiền xử lý | [GD2](notebook/02_tien_xu_ly/GD2_tien_xu_ly_va_kiem_chung.ipynb) | Chuẩn hóa và đối soát hai bảng ở cấp đơn hàng và cấp dòng hàng. |
| 03. EDA | [EDA tổng quan](notebook/03_eda/EDA_tong_quan.ipynb) | Khám phá biến động doanh thu, giá vốn và mức tập trung giá trị mua hàng. |
| 04. Bài 1 — Phân tích kinh doanh | [TH01](notebook/04_phan_tich_kinh_doanh/TH01_tong_hop_va_doi_soat_NV01_NV06.ipynb) | Xem tổng hợp sáu nghiệp vụ. [NV01–NV06](notebook/04_phan_tich_kinh_doanh/) trình bày chi tiết. |
| 05. Bài 2 — Phân khúc khách hàng | [PC01–PC05](notebook/05_phan_khuc_khach_hang/) | Từ xây dựng RFM đến lựa chọn mô hình, hồ sơ nhóm và kiểm tra độ nhạy. |
| 06. Bài 3 — Dự báo doanh thu và giá vốn | [Baseline](notebook/06_du_bao/baseline.ipynb) | Dùng lịch sử Sales và cột `Date` của mẫu nộp bài để tạo dự báo tham chiếu. |

## Dữ liệu nằm ở đâu?

- [`data/raw/`](data/raw/) chứa 14 CSV nguồn.
- [`data/processed/`](data/processed/) chứa `orders_common.csv`, `order_items_common.csv` và thông tin kiểm tra phiên bản của hai bảng.
- [`data/model/`](data/model/) chứa bộ đặc trưng, nhãn, kết quả lựa chọn mô hình và tham số phân cụm. Hai phiên bản CSV có nội dung giống hệt nhau được gộp dưới một lượt `v1`.

## Chạy lại trong VS Code hoặc Jupyter

Dùng Python 3.11 trở lên. Mở thư mục dự án, cài thư viện và chọn đúng kernel.

```bash
python -m pip install -r requirements.txt
```

Mỗi notebook tự tìm dữ liệu và nạp hàm từ [notebook dùng chung](notebook/00_ham_dung_chung.ipynb). Tài liệu giải thích nằm ở đầu từng phần. Bảng và biểu đồ xuất trực tiếp trong notebook.

- Chạy GD2 để kiểm tra hoặc tạo hai CSV đã xử lý. Đọc kết quả đã lưu trong notebook khi chỉ cần xem nội dung.
- Trong Bài 1, đọc NV01–NV06 trước TH01 nếu muốn theo dõi cách hình thành từng chỉ tiêu. TH01 đọc các bảng kết quả đã lưu của sáu notebook.
- Bài 2 mặc định đọc dữ liệu của lượt phân cụm `v1`. Để huấn luyện mới, đặt `DATATHON_MODEL_RUN` thành tên lượt mới ở kernel PC03, rồi sử dụng cùng tên đó khi chạy PC04 và PC05.
- Bài 3 hiển thị dự báo trong notebook. Bật `XUAT_DU_BAO` nếu cần xuất một CSV vào `data/model/du_bao/`. Tập kiểm tra riêng được chấm trên Kaggle.
