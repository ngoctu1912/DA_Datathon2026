# Analytix — DATATHON 2026

Ứng dụng web trình bày 3 bài toán của đồ án: phân tích kinh doanh/khách hàng, phân cụm RFM và dự báo Revenue–COGS. Thiết kế dựa trên 5 bản Stitch (11–15), dùng một sidebar thống nhất và 5 chức năng theo yêu cầu. Các bảng và biểu đồ đọc dữ liệu tổng hợp thực, không lấy số mẫu trong thiết kế Stitch.

## 1. Chạy ngay (Linux, Windows, macOS)

Giải nén và mở thư mục `Analytix` trong VS Code. Dữ liệu tổng hợp đã có sẵn, không cần tải lại Kaggle, cài thư viện ML hay mở Jupyter để xem dashboard.

```bash
python run_local.py
```

Trình duyệt mở URL được in trong Terminal (mặc định `http://127.0.0.1:8098`). Nếu cổng đang bận, `run_local.py` tự thử cổng kế tiếp (tối đa 50 cổng), không dừng tiến trình khác. Nhấn Ctrl+C để dừng ứng dụng. Nếu lệnh `python` không có, dùng `python3 run_local.py` trên Linux hoặc `py run_local.py` trên Windows. Có thể chọn cổng bắt đầu: `python run_local.py --port 8099`. Mở đúng URL và kiểm tra đường dẫn thư mục được in trong Terminal để tránh dùng server cũ. Không mở trực tiếp index.html bằng file:// vì trình duyệt có thể chặn fetch JSON.

## 2. Chạy bằng Spring Boot (Java)

Yêu cầu JDK 17+ và Maven 3.9+. Kiểm tra `java -version` và `mvn -v`, sau đó chạy trong thư mục ứng dụng:

```bash
mvn spring-boot:run
```

Hoặc đóng gói và chạy JAR:

```bash
mvn clean package
java -jar target/datascope-1.0.0.jar
```

Mở http://localhost:8080. Spring Boot phục vụ giao diện và hai API GET `/api/dashboard`, `/api/health`. Giao diện dùng đường dẫn tương đối `dashboard.json` để chạy được cả Spring Boot lẫn hosting tĩnh. Java không huấn luyện mô hình ML; giữ nguyên pipeline Python của đồ án. Không cần cơ sở dữ liệu riêng cho bản trình bày.

Docker (nếu đã cài Docker):

```bash
docker build -t datascope .
docker run --rm -p 8080:8080 datascope
```

## 3. Cấu trúc

```
Analytix/
├── web/
│   ├── index.html                 # khung giao diện, sidebar, header
│   ├── style.css                  # thiết kế giao diện responsive
│   ├── app.js                     # khởi động, nạp dữ liệu, điều hướng
│   ├── common.js                  # cấu hình, trạng thái, thành phần chung
│   ├── charts.js                  # biểu đồ SVG và tổng hợp thời gian
│   ├── overview.js                # trang Tổng quan
│   ├── customers.js               # trang Phân tích khách hàng
│   ├── clusters.js                # trang Phân cụm khách hàng
│   ├── forecast.js                # trang Dự báo doanh thu
│   ├── models.js                  # trang Mô hình ML
│   ├── interactions.js            # bộ lọc, nút bấm, dialog, xuất CSV
│   └── dashboard.json             # dữ liệu tổng hợp, thụt lề 2 dấu cách
├── backend/
│   ├── DataScopeApplication.java  # Spring Boot và API
│   └── application.properties
├── tools/
│   ├── run_forecast.py
│   ├── build_data.py
│   ├── cluster_views.py
│   └── requirements.txt
├── .github/workflows/pages.yml     # xuất bản website tĩnh
├── pom.xml
├── Dockerfile
├── run_local.py
└── README.md
```

Maven được cấu hình trong `pom.xml` để đọc Java từ `backend/` và đóng gói `web/` vào `static/` của JAR. Không cần tạo lại cây `src/main/`. GitHub Pages chỉ xuất bản thư mục `web/`.

### Chỉnh sửa giao diện

Mỗi trang có một file JS riêng trong `web/`. Sửa HTML khung ở `index.html`, màu sắc và bố cục ở `style.css`, biểu đồ ở `charts.js`. Các file JS dùng chung trạng thái `D`, `state` và các hàm từ `common.js`. Không đổi thứ tự script trong HTML nếu chưa kiểm tra phụ thuộc. `app.js` chỉ nạp dữ liệu, điều hướng và khởi động; xử lý nút bấm và CSV ở `interactions.js`.

`dashboard.json` được tạo tự động, định dạng 2 dấu cách và giữ nguyên các giá trị dữ liệu. Không cần sửa từng dòng bằng tay; khi cập nhật đồ án hãy chạy `tools/build_data.py`. Trong VS Code có thể thu gọn từng object bằng chức năng Fold (gutter bên trái), tìm tên khóa bằng Ctrl+F.

## 4. Import lại dữ liệu khi đồ án thay đổi

Đặt hai thư mục cạnh nhau (không cần chép dữ liệu gốc vào ứng dụng):

```
workspace/
├── DA_Datathon2026/               # giải nén ZIP đồ án của nhóm
│   ├── data/raw/
│   ├── data/model/
│   └── notebook/
└── Analytix/
```

Từ thư mục ứng dụng, tạo môi trường Python (nếu cần chạy lại phân tích):

```bash
python -m venv .venv
# Linux/macOS: source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -r tools/requirements.txt
python tools/run_forecast.py ../DA_Datathon2026
python tools/build_data.py ../DA_Datathon2026
```

`run_forecast.py` thực thi các code cell của notebook `06_du_bao/02_mo_hinh.ipynb` theo thứ tự; tạo `forecast_predictions.csv` (validation/test) và `future_predictions.csv` (refit toàn lịch sử 2012–2022, 548 ngày tương lai theo sample_submission.csv). Nó ghi các đầu ra vào `data/model/du_bao/` của đồ án, không thay đổi raw CSV và không sửa notebook. Nếu hai file này đã tồn tại, có thể bỏ qua bước chạy forecast. Bài 2 dùng CSV `data/model/phan_khuc/combined_v1/ket_qua_phan_cum.csv`; huấn luyện lại Bài 2 bằng các notebook PC01–PC06 trong đồ án trước khi import nếu cần.

`build_data.py` đọc các CSV nguồn và kết quả mô hình, tạo `web/dashboard.json`. Tải lại trang trong trình duyệt để nạp dữ liệu mới khi chạy static server; nếu đã đóng gói JAR thì đóng gói lại để cập nhật resource. Không cần xuất nhiều bảng CSV phụ. Bản hiện tại đã tạo dữ liệu từ ZIP thật và đã refit dự báo 2023–2024; sai số test không phải điểm Kaggle.

## 5. Chức năng

- Tổng quan: KPI toàn kỳ / 30 ngày / quý / năm, Revenue/COGS, quy mô cụm, dự báo 90 ngày.
- Phân tích khách hàng: giữ nội dung mẫu phân tích kinh doanh; lọc kỳ, danh mục, khu vực, trạng thái; biểu đồ ngày/tháng/quý/năm (toàn lịch sử tối thiểu theo tháng), đơn hàng, hoàn trả, top sản phẩm, khuyến mãi, cảnh báo tồn kho. Kỳ được tính lùi từ ngày cuối dữ liệu 31/12/2022, không theo ngày hiện tại.
- Phân cụm khách hàng: K-Means TN1 k=3 từ CSV bàn giao, PCA, phân bố RFM, hồ sơ cụm, bộ lọc Recency; đối chứng K-Means/GMM/Hierarchical k=2–6 và DBSCAN trên mẫu 5.000 khách. Chọn thuật toán và số cụm để xem các kết quả đã tính. Không nhầm nhãn đối chứng với nhãn bàn giao.
- Dự báo doanh thu: chọn mô hình, chỉ tiêu Revenue/COGS, 30/90/180/548 ngày, test hoặc kỳ Kaggle; đường thực tế/dự báo, metric test, residual, bảng so sánh, siêu tham số, xuất submission đủ 548 ngày và đúng 3 cột. Huấn luyện thực hiện qua script Python ở mục 4.
- Mô hình ML: hai tab Phân cụm khách hàng và Dự báo doanh thu. Phân cụm đọc 14 cấu hình K-Means toàn tập và 36 cấu hình đối chứng từ bảng đã lưu trong PC03; không trộn hai phạm vi đánh giá. Dự báo giữ bảng so sánh validation/test và biểu đồ sai số. Làm mới mặc định về Phân cụm / K-Means toàn tập; tab Dự báo mặc định Validation.

## 6. Đưa lên mạng để gửi link

### A. GitHub Pages — khuyến nghị cho bản trình bày

Chỉ cần đưa mã nguồn ứng dụng này lên một repository riêng (branch `main`); giữ file ẩn `.github/workflows/pages.yml`. **Không đẩy `DA_Datathon2026/data/raw` hoặc CSV định danh lên repository công khai.** Kiểm tra điều khoản sử dụng bộ dữ liệu Kaggle trước khi công khai cả dữ liệu tổng hợp.

1. Tạo repository trên GitHub và push nội dung ứng dụng.
2. Mở Settings → Pages → Build and deployment → Source → GitHub Actions.
3. Mở Actions → Deploy Analytix to GitHub Pages → Run workflow (hoặc push branch main).
4. Khi deploy thành công, GitHub hiển thị link tại Settings → Pages. Link dự kiến có dạng `https://<username>.github.io/<repository>/`.

Hướng dẫn: https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site

Bản Pages chạy tương tác lọc, biểu đồ và xuất CSV hoàn toàn trong trình duyệt, không cần bật máy hay server Java của người làm đồ án. Đây vẫn là web application; không huấn luyện model trực tuyến.

### B. Render — nếu cần chạy backend Spring Boot thật

1. Push ứng dụng (có Dockerfile) lên GitHub.
2. Đăng nhập Render, tạo New → Web Service và kết nối repository.
3. Chọn Docker runtime, branch main, health check path `/api/health`. Spring Boot tự đọc biến môi trường PORT.
4. Deploy, dùng URL `https://<service>.onrender.com` được cấp. Kiểm tra chính sách phí và tài nguyên của gói đã chọn.

Hướng dẫn: https://render.com/docs/docker và https://render.com/docs/web-services

## 7. Nguồn và giới hạn kiểm chứng

- Dữ liệu gốc không thay đổi: 121.930 hồ sơ khách, 646.945 đơn, 2.412 SKU, 3.833 ngày sales. Phân cụm chính 85.115 khách, 3 nhóm. Revenue trước giảm giá; không mặc nhiên là tiền thực nhận. Đơn vị tiền theo nguồn, không tự gán VNĐ. Monetary là Net delivered, không phải lợi nhuận.
- Kỳ toàn lịch sử đối soát tổng Revenue dòng hàng với sales.csv. Khu vực ghép ZIP khi có đúng một vùng; ZIP mơ hồ để Không xác định. Hoàn trả tính số đơn có bản ghi returns, không đồng nhất với trạng thái returned. Top promo chỉ theo promo_id chính và Revenue gắn mã; không khẳng định hiệu quả nhân quả. Tồn kho là snapshot toàn hệ thống cuối kỳ dữ liệu.
- Kết quả dự báo được tái chạy ở môi trường NumPy 2.3.5, pandas 2.2.3, scikit-learn 1.8.0, statsmodels 0.14.6, CatBoost 1.2.8. MAE Revenue Hybrid test khoảng 499.184 đơn vị, khác nhẹ số notebook lưu (498.090) vì chạy lại môi trường/phiên bản khác; web tính lại metric từ đầu ra thực tế. Mùa vụ + hiệu ứng thứ dẫn đầu validation; Hybrid dẫn đầu test, không dùng test để chứng minh mô hình tối ưu tổng quát. Kỳ Kaggle chưa có nhãn, chưa nộp/chấm Kaggle.
- Silhouette 0,4589 và DB 0,7433 của mô hình chính đọc từ notebook PC03; nhánh ablation đọc từ kết quả đã lưu notebook 04. Đối chứng bổ sung web tính lại trên mẫu, không phải nhãn chính. PCA fit toàn tập chính, lấy mẫu để giảm số điểm hiển thị.
- Đã kiểm thử UI bằng Chromium/Playwright với dữ liệu JSON thật được nạp vào trang kiểm thử: 5 route, 5 sidebar links, lọc kinh doanh, GMM/DBSCAN, RFM, đổi mô hình/giai đoạn dự báo, chi tiết model, xuất CSV, mobile 390px; không có lỗi JS trong các thao tác thử. Chưa kiểm thử đóng gói Spring Boot/Maven (môi trường không có Maven), chưa deploy ra internet, không có URL public thực tế. Font Inter có fallback hệ thống.


## Bảo trì thư mục tools

Các script Python chỉ cần thiết khi cập nhật dữ liệu, không cần chạy để mở web.

| File | Hàm chính | Vai trò |
|---|---|---|
| `build_data.py` | `build_business_data`, `build_cluster_data`, `build_forecast_data`, `save_dashboard` | Đọc CSV và kết quả đã có, tổng hợp JSON cho web |
| `cluster_views.py` | `make_view`, `build_recency_views`, `create_model`, `build_comparison_views`, `add_views` | Chuẩn bị phân cụm đối chứng và biểu đồ |
| `run_forecast.py` | `configure_environment`, `run_notebook`, `forecast_future` | Chạy notebook gốc và dự báo kỳ Kaggle |
| `requirements.txt` | — | Thư viện Python dùng khi cập nhật dữ liệu |

Các file đã có tiêu đề theo từng phần, chú thích tiếng Việt và hàm `main()` cho hai script chạy trực tiếp. `cluster_views.py` được import tự động bởi `build_data.py`. Các tham số, công thức và kết quả dashboard sẵn có được giữ nguyên. Lưu ý: `run_forecast.py` phụ thuộc vào code cell số 26 (chỉ số bắt đầu từ 0) và các biến của notebook dự báo hiện tại; nếu nhóm thay đổi notebook, cần kiểm tra lại. Các nhãn mô hình chính thức, chỉ số phân cụm chính thức và mốc thời gian được giữ cố định theo bản đồ án hiện tại trong `build_data.py`.


### Bộ lọc khoảng ngày trên trang Tổng quan

Chọn Từ ngày và Đến ngày, nhấn Áp dụng. Đặt lại trở về toàn kỳ.
KPI khách hàng và sản phẩm tính số lượng không trùng có giao dịch trong kỳ,
kể cả khi chọn toàn kỳ (không phải tổng hồ sơ hoặc danh mục).
Phân cụm và dự báo là kết quả mô hình tại mốc cố định, không huấn luyện lại khi lọc.
Các trang khác giữ nguyên bộ lọc riêng. `overviewDaily` trong dashboard.json
là dữ liệu tổng hợp để tính đúng KPI, không chứa ID khách hàng/SKU.

### Tổng quan — bộ lọc ngày, độ chi tiết và Làm mới

- Chọn Từ ngày / Đến ngày, nhấn Áp dụng. KPI và biểu đồ doanh thu cùng lấy dữ liệu trong khoảng đó (bao gồm hai ngày đầu/cuối).
- Trong biểu đồ Doanh thu & COGS, chọn Ngày, Tháng hoặc Năm để đổi cách tổng hợp mà không đổi khoảng ngày. Tự động: đến 93 ngày dùng ngày, đến 730 ngày dùng tháng, dài hơn dùng năm. Tháng/năm không trọn kỳ chỉ cộng những ngày nằm trong bộ lọc. Di chuột để xem giá trị từng mốc. Đặt lại đưa khoảng ngày về toàn kỳ và độ chi tiết về Tự động.
- Làm mới khôi phục bộ lọc mặc định của trang đang xem; không đổi bộ lọc các trang khác. Để đọc JSON mới sau khi chạy pipeline import, tải lại trang bằng trình duyệt.
