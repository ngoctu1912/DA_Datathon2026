import argparse
import json
import os
from pathlib import Path

# 1. CẤU HÌNH MÔI TRƯỜNG
def configure_environment(project_root):
    """Thiết lập đường dẫn và giới hạn số luồng xử lý."""
    os.environ['RETAIL_ANALYTICS_ROOT'] = str(project_root)
    os.environ.setdefault('MPLBACKEND', 'Agg')
    os.environ.setdefault('OPENBLAS_NUM_THREADS', '2')
    os.environ.setdefault('OMP_NUM_THREADS', '2')
    os.environ.setdefault('MKL_NUM_THREADS', '2')

# 2. CHẠY NOTEBOOK GỐC: VALIDATION VÀ TEST
def run_notebook(project_root):
    """Chạy tuần tự các code cell, dùng chung biến như khi chạy Jupyter."""
    notebook_path = project_root / 'notebook/06_du_bao/02_mo_hinh.ipynb'
    notebook = json.loads(notebook_path.read_text(encoding='utf-8'))
    context = {'__name__': '__main__'}

    for cell_index, cell in enumerate(notebook['cells']):
        if cell['cell_type'] != 'code':
            continue

        print('Notebook 02 - cell', cell_index, flush=True)
        source_code = ''.join(cell['source'])
        exec(compile(source_code, f'cell{cell_index}', 'exec'), context)

    return notebook, context

# 3. DỰ BÁO KỲ KAGGLE TRÊN TOÀN BỘ LỊCH SỬ
def forecast_future(notebook, context):
    """Tái tạo panel trên toàn lịch sử; giữ nguyên validation/test đã tính."""
    # Các tên biến bên dưới phải tương thích với notebook gốc.
    context['dev_end'] = context['history_end']
    context['sales_dev'] = context['sales_daily'].set_index('Date')[context['targets']]

    # Cell 26 của phiên bản notebook hiện tại dựng panel đặc trưng.
    # Nếu thay cấu trúc notebook, cần kiểm tra lại vị trí cell này.
    panel_source = ''.join(notebook['cells'][26]['source'])
    exec(compile(panel_source, 'refit_panel', 'exec'), context)

    # Dùng lại các hàm dự báo và bảng dữ liệu do notebook tạo ra.
    pd = context['pd']
    project_root = context['project_root']
    sales_daily = context['sales_daily']
    targets = context['targets']
    predictors = context['predictors']
    prediction_block = context['prediction_block']
    test_methods = context['test_methods']

    # Lấy chính xác các ngày cần dự báo từ mẫu nộp Kaggle.
    submission = pd.read_csv(
        project_root / 'data/raw/sample_submission.csv',
        parse_dates=['Date'],
    )
    future_dates = pd.DatetimeIndex(submission['Date'])
    full_history = sales_daily.set_index('Date')[targets]

    # Dự báo từng mô hình rồi gộp về cùng một bảng kết quả.
    forecast_parts = []
    for method in test_methods:
        forecast = predictors[method](full_history, future_dates)
        forecast_parts.append(
            prediction_block(forecast, 'future', 0, full_history.index.max(), method)
        )

    future = pd.concat(forecast_parts, ignore_index=True)
    output_path = project_root / 'data/model/du_bao/future_predictions.csv'
    future.to_csv(output_path, index=False, date_format='%Y-%m-%d')
    print('Đã tạo', len(future), 'dòng dự báo tương lai (không có nhãn).')

# 4. KHỞI ĐỘNG
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('project', type=Path, help='Đường dẫn đến đồ án Python')
    args = parser.parse_args()

    project_root = args.project.resolve()
    configure_environment(project_root)

    notebook, context = run_notebook(project_root)
    forecast_future(notebook, context)


if __name__ == '__main__':
    main()