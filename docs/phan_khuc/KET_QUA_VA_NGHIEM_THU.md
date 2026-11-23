# Kết quả và nghiệm thu bản tích hợp — 23/11/2026

## Phạm vi kết hợp

Giữ nguyên dữ liệu raw, code dùng chung và notebook ngoài phân cụm của dự án cũ. Mở rộng PC01–PC05, thêm PC06 và notebook hỗ trợ kiểm chứng/đối chứng riêng. Không chép notebook trùng vào thư mục kết quả; không nạp các joblib của ZIP mới để giả định chúng tương thích. Tất cả mô hình dùng trong bản tích hợp được tính lại từ dữ liệu đã nghiệm thu.

## Kết quả chính

K-Means TN1, k=3. 85.115 khách, 516.716 đơn delivered đến 31/12/2022, tổng Net chính xác 12.518.175.957,20. Đây là đề xuất mô tả, không là chứng minh tối ưu cho mọi mục tiêu.

|Nhóm|Khách|Tỷ trọng khách|R trung vị (ngày)|F trung vị|M trung vị|Tỷ trọng Net|
|---|---:|---:|---:|---:|---:|---:|
|0|34,498|40.53%|2307|1|29,651.965|11.46%|
|1|40,342|47.40%|598|5|124,473.995|44.85%|
|2|10,275|12.07%|244|19|477,244.080|43.68%|

## Chất lượng và đánh đổi

- 14 cấu hình K-Means toàn tập TN1/TN2. Quy tắc chọn: min share 1%, tổng hạng Silhouette/DB, top3 kiểm seed. k2 có thể có Silhouette tốt hơn k3; PC04 trình bày hồ sơ/bảng chéo k2/k3/k4 để thẩm định phần chi tiết thêm.
- 36 đối chứng trên cùng mẫu 5.000 và cùng scaler mẫu, chỉ TN1. Không trộn chỉ số với mô hình toàn tập. Ba thuật toán k3 có đánh đổi Silhouette/DB; không tuyên bố K-Means thắng mọi chỉ số.
- DBSCAN đạt sàng lọc: 0/15. Cấu hình không đạt vẫn có bảng/hình chẩn đoán riêng, không được chọn là người thắng.
- Seed toàn tập, mẫu con 80%, P99 và siêu tham số là các phép thử khác nhau. Giữ seed mô hình cố định khi đổi mẫu. P99 fit lại scaler và mô hình chỉ trên bản sao. ARI DBSCAN báo kèm nhiễu và số cụm.
- Bảo toàn phân tích trạng thái: cancelled/returned/shipped/paid/created vẫn tham gia hành vi và kiểm tra nguồn; không cộng chúng vào RFM mua thành công. Hai kịch bản shipment/shipped dùng scaler và tâm cố định, không giả là mô hình refit.

## Vì sao khác số khách từng cụm của ZIP thực nghiệm mới?

Đối chiếu CSV mới với RFM tích hợp: cùng mã khách, R và F trùng; sai khác M số thực tối đa 2.3283064365386963e-10. Thứ tự dòng khác: CSV mới sắp mã số 1,2,3…; baseline dùng mã chuỗi 1,10,10000… . Cùng seed nhưng thứ tự khác có thể chọn khách mẫu và tâm khởi tạo khác. Bản này ghi mẫu/ID/scaler/phiên bản cụ thể, dùng số liệu tính lại của chính lượt combined_v1. Không gọi khác biệt nhãn là bằng chứng làm sạch sai khi chưa có kiểm chứng.

## Nghiệm thu

- 6 notebook, 70 ô code thực thi, 80 ô giải thích, 15 hình đầu ra, 17 công thức hiển thị.
- 26/26 kiểm thử tích hợp đạt; 0 lỗi. Có kiểm nhãn tái tạo từ scaler/tâm/mapping cho toàn bộ khách.
- GD2 đã thực sự tạo và round-trip hai common CSV từ raw hiện tại. Sau thực thi, file notebook GD2 của nhóm được giữ lại nguyên byte bản gốc; chứng cứ thực thi ghi riêng trong gd2_execution.json.
- 30 file gốc giữ nguyên byte, 15 file mô hình v1 gốc được bỏ theo yêu cầu, chỉ 5 notebook phân cụm và README/requirements được cập nhật; file dùng chung giữ nguyên bản gốc; các file bổ sung là code, dữ liệu kết quả và hướng dẫn mới.
- Không khẳng định đã chạy lại/nghiệm thu tất cả notebook kinh doanh hoặc dự báo. Chưa có dữ liệu sau triển khai để đánh giá tác động chiến lược.

## Cách dùng

Đọc BAT_DAU.md. Kết quả khách cuối: data/model/phan_khuc/combined_v1/ket_qua_phan_cum.csv. Không còn thư mục v1 cũ; xem BAT_DAU.md về CSV kết quả và JSON mô hình hiện tại.

## Hướng phát triển có điều kiện

Đánh giá cửa sổ thời gian/cohort khi mục tiêu chuyển sang hoạt động hiện tại; xác minh ngữ nghĩa payment/delivery_date; bổ sung chi phí/biên trước khi gọi nhóm lợi nhuận cao. PC06 đã định nghĩa KPI 60 ngày và phân nhóm ngẫu nhiên/A-B như một thiết kế đề xuất, không bịa doanh thu tăng.

## Điều chỉnh chế độ xuất file

PC01–PC06 mặc định chỉ hiển thị bảng/ảnh; không tự tạo `reports/`, chỉ lưu CSV phân cụm chính và JSON mô hình. Báo cáo là đầu ra tuỳ chọn và có thể xóa. Chứng cứ nghiệm thu của lần đóng gói đặt ở `docs/phan_khuc/nghiem_thu/`; notebook không dùng chúng làm đầu vào. Xem `BAT_DAU.md` về hai cờ xuất độc lập. Dữ liệu/tham số thí nghiệm trong `data/model` vẫn là đầu vào cần thiết.

Kiểm chứng bổ sung: xóa/không đóng gói reports, chạy lại cả 6 notebook thành công; so SHA-256 trước/sau không tạo, xóa hoặc đổi file nào ngoài chính notebook. Ba kiểm thử mới bao gồm mặc định không xuất, bật xuất chủ động và không đọc báo cáo làm đầu vào. Tổng 26/26 đạt.




## Chính sách lưu tối giản hiện tại

Model chỉ có ket_qua_phan_cum.csv và mo_hinh_phan_cum.json. Không có ZIP mô hình, không có v1 cũ, không lưu bảng scores/grid/seed/sensitivity/ảnh như file kết quả rời. Chúng được tính lại trong phiên notebook. Dữ liệu mô hình cố định đã lưu được kiểm chứng bằng nguồn và nhãn; bảng ứng viên tính lại không tự thay thế mô hình chính. File Python dùng chung gốc vẫn không đổi.
