import argparse
import json
from io import StringIO
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.decomposition import PCA
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.preprocessing import StandardScaler

from cluster_views import BINS, add_views

# 1. CÁC HÀM ĐỌC VÀ CHUYỂN ĐỔI DỮ LIỆU
DEFAULT_OUTPUT = Path(__file__).resolve().parents[1] / 'web/dashboard.json'


def read_csv(raw_dir, name, **options):
    """Đọc một CSV trong data/raw, giữ các tùy chọn của pandas."""
    return pd.read_csv(raw_dir / f'{name}.csv', **options)


def records(frame):
    """Chuyển DataFrame thành danh sách record JSON, làm tròn 4 chữ số."""
    return json.loads(
        frame.to_json(orient='records', date_format='iso', double_precision=4)
    )

# 2. BÀI TOÁN 1 - PHÂN TÍCH KINH DOANH
def build_overview_daily(sales, orders, lines):
    """Tổng hợp theo ngày để đếm chính xác khách/SKU không trùng.

    Lưu chỉ số ngày xuất hiện trước đó, không lưu ID khách hàng hoặc SKU.
    -1 nghĩa là chưa xuất hiện. Một lần xuất hiện có ngày trước < mốc
    bắt đầu chính là lần đầu trong kỳ. Với delivered, hiệu giữa số lần
    có ngày trước thứ hai < mốc và ngày trước thứ nhất < mốc là số
    khách mua ít nhất hai lần trong kỳ.
    """
    start = sales.Date.min().normalize()
    end = sales.Date.max().normalize()
    daily = [
        {
            'date': day.strftime('%Y-%m-%d'),
            'orders': 0,
            'customerPrevious': [],
            'productPrevious': [],
            'deliveredPrevious': [],
            'deliveredSecondPrevious': [],
            'categoryRevenue': {},
        }
        for day in pd.date_range(start, end)
    ]
    selected_orders = orders[orders.order_date.between(start, end)]
    selected_orders = selected_orders.sort_values(['order_date', 'order_id'])
    selected_lines = lines[lines.order_date.between(start, end)].copy()
    selected_lines['day'] = (selected_lines.order_date - start).dt.days

    # Lần xuất hiện trước của khách và hai lần mua delivered gần nhất.
    last_customer = {}
    last_delivered = {}
    second_last_delivered = {}
    for order in selected_orders.itertuples(index=False):
        day = (order.order_date - start).days
        row = daily[day]
        row['orders'] += 1
        customer = order.customer_id
        if pd.isna(customer):
            continue
        row['customerPrevious'].append(last_customer.get(customer, -1))
        last_customer[customer] = day
        if order.order_status == 'delivered':
            previous = last_delivered.get(customer, -1)
            row['deliveredPrevious'].append(previous)
            row['deliveredSecondPrevious'].append(second_last_delivered.get(customer, -1))
            second_last_delivered[customer] = previous
            last_delivered[customer] = day

    # Một SKU chỉ cần ghi nhận một lần mỗi ngày.
    last_product = {}
    product_days = selected_lines[['day', 'product_id']].dropna().drop_duplicates()
    for day, product in product_days.sort_values('day').itertuples(index=False, name=None):
        daily[day]['productPrevious'].append(last_product.get(product, -1))
        last_product[product] = day

    # Revenue dòng hàng theo danh mục, trước giảm giá.
    category_totals = selected_lines.groupby(['day', 'category']).Revenue.sum()
    for (day, category), revenue in category_totals.items():
        daily[day]['categoryRevenue'][str(category)] = float(revenue)

    # Sắp xếp để JavaScript đếm nhanh bằng tìm kiếm nhị phân.
    for row in daily:
        for key in ('customerPrevious', 'productPrevious',
                    'deliveredPrevious', 'deliveredSecondPrevious'):
            row[key].sort()
    return daily


def build_business_data(raw_dir):
    """Đọc CSV, nối bảng và tổng hợp KPI theo kỳ, danh mục, vùng, trạng thái."""
    # Revenue là giá trị trước giảm giá, giống quy ước của notebook.
    sales = read_csv(raw_dir, 'sales', parse_dates=['Date'])
    orders = read_csv(raw_dir, 'orders', parse_dates=['order_date'])
    products = read_csv(raw_dir, 'products')
    customers = read_csv(raw_dir, 'customers', parse_dates=['signup_date'])
    items = read_csv(raw_dir, 'order_items')
    returns = read_csv(raw_dir, 'returns')
    inventory = read_csv(raw_dir, 'inventory', parse_dates=['snapshot_date'])
    promos = read_csv(raw_dir, 'promotions')
    geo = read_csv(raw_dir, 'geography')

    # Chỉ gán vùng nếu ZIP có đúng một vùng; không nối nhân bản đơn hàng.
    region_by_zip = geo.groupby('zip').region.agg(
        lambda regions: regions.iloc[0] if regions.nunique() == 1 else 'Không xác định'
    )
    orders['region'] = orders.zip.map(region_by_zip).fillna('Không xác định')
    orders['returned'] = orders.order_id.isin(returns.order_id).astype(int)
    lines = (
        items.merge(
            products[['product_id', 'product_name', 'category', 'cogs']],
            on='product_id',
            validate='many_to_one',
        )
        .merge(
            orders[['order_id', 'order_date', 'customer_id', 'order_status', 'region', 'returned']],
            on='order_id',
            validate='many_to_one',
        )
    )

    # Tính chỉ tiêu theo dòng sản phẩm.
    lines['Revenue'] = lines.quantity * lines.unit_price
    lines['COGS'] = lines.quantity * lines.cogs
    lines['Net'] = lines.Revenue - lines.discount_amount
    end = sales.Date.max()
    # Bốn kỳ kết thúc tại ngày cuối cùng của sales.csv.
    periods = {
        'all': sales.Date.min(),
        'year': end - pd.DateOffset(years=1) + pd.Timedelta(days=1),
        'quarter': end - pd.DateOffset(months=3) + pd.Timedelta(days=1),
        '30': end - pd.Timedelta(days=29),
    }
    data = {
        'history': records(sales.assign(Date=sales.Date.dt.strftime('%Y-%m-%d'))),
        'dates': {'start': str(sales.Date.min().date()), 'end': str(end.date())},
        'totals': {'customers': len(customers), 'orders': len(orders), 'products': len(products)},
        'periods': {},
        'categories': sorted(lines.category.unique().tolist()),
        'regions': sorted(orders.region.unique().tolist()),
        'statuses': sorted(orders.order_status.unique().tolist())
    }

    # Dữ liệu lọc khoảng ngày tùy chọn cho Tổng quan.
    data['overviewDaily'] = build_overview_daily(sales, orders, lines)

    # Dữ liệu theo kỳ và bộ lọc. All là toàn bộ danh mục; tránh cộng đếm đơn trùng giữa danh mục.
    for key, start in periods.items():
        print('Tổng hợp kỳ', key, flush=True)
        period_orders = orders[orders.order_date.between(start, end)]
        period_lines = lines[lines.order_date.between(start, end)]
        period_sales = sales[sales.Date.between(start, end)]
        period_returns = returns[returns.order_id.isin(period_orders.order_id)]
        customer_count = period_orders.customer_id.nunique()
        active_count = period_orders[period_orders.order_status.eq('delivered')].customer_id.nunique()
        category_revenue = period_lines.groupby('category').Revenue.sum().sort_values(ascending=False)
        repeat_orders = (
            period_orders[period_orders.order_status.eq('delivered')]
            .groupby('customer_id').order_id.nunique()
        )
        # Ảnh chụp kho cuối kỳ, không cộng tồn kho qua các tháng.
        latest_inventory = inventory[inventory.snapshot_date.le(end)]
        latest_inventory = latest_inventory[
            latest_inventory.snapshot_date.eq(latest_inventory.snapshot_date.max())
        ]
        period_info = {
            'start': str(start.date()),
            'end': str(end.date()),
            'customers': int(customer_count),
            'active': int(active_count),
            'new': int(customers.signup_date.between(start, end).sum()),
            'repeat': int((repeat_orders > 1).sum()),
            'products': int(period_lines.product_id.nunique()),
            'orders': len(period_orders),
            'revenue': float(period_sales.Revenue.sum()),
            'cogs': float(period_sales.COGS.sum()),
            'topCategory': str(category_revenue.index[0]),
            'topShare': float(category_revenue.iloc[0] / category_revenue.sum()),
            'stockout': int(latest_inventory.stockout_flag.sum()),
            'inventoryDate': str(latest_inventory.snapshot_date.max().date()),
            'filters': {}
        }
        # Mỗi bộ lọc danh mục/địa lý/trạng thái có chuỗi thời gian, top SP và KPI riêng.
        for category in ['all', *data['categories']]:
            category_lines = (
                period_lines if category == 'all'
                else period_lines[period_lines.category.eq(category)]
            )
            for region in ['all', *data['regions']]:
                region_lines = (
                    category_lines if region == 'all'
                    else category_lines[category_lines.region.eq(region)]
                )
                for status in ['all', *data['statuses']]:
                    filtered_lines = (
                        region_lines if status == 'all'
                        else region_lines[region_lines.order_status.eq(status)]
                    )
                    if filtered_lines.empty:
                        continue
                    unique_orders = filtered_lines.drop_duplicates('order_id')
                    filtered_returns = period_returns[period_returns.order_id.isin(unique_orders.order_id)]
                    revenue = filtered_lines.Revenue.sum()
                    cost = filtered_lines.COGS.sum()
                    # Theo ngày cho kỳ ngắn, theo tháng cho toàn lịch sử để giữ kích thước hợp lý.
                    freq = 'MS' if key == 'all' else 'D'
                    time_series = (
                        filtered_lines.groupby(pd.Grouper(key='order_date', freq=freq))[['Revenue', 'COGS']]
                        .sum()
                        .reset_index()
                        .rename(columns={'order_date': 'Date'})
                    )
                    time_series = time_series[time_series.Revenue.ne(0) | time_series.COGS.ne(0)]
                    time_series.Date = time_series.Date.dt.strftime('%Y-%m-%d')
                    top_products = (
                        filtered_lines.groupby(['product_name', 'category'])
                        .Revenue.sum().nlargest(12).reset_index()
                    )
                    filtered_category_revenue = filtered_lines.groupby('category').Revenue.sum().sort_values(ascending=False)
                    promotion_revenue = (
                        filtered_lines[filtered_lines.promo_id.notna()]
                        .groupby('promo_id').Revenue.sum().sort_values(ascending=False)
                    )
                    promo_name = 'Không ghi nhận'
                    promo_value = 0
                    if len(promotion_revenue):
                        promotion_match = promos[promos.promo_id.eq(promotion_revenue.index[0])]
                        promo_name = (
                            str(promotion_match.promo_name.iloc[0]) if len(promotion_match)
                            else str(promotion_revenue.index[0])
                        )
                        promo_value = float(promotion_revenue.iloc[0])
                    period_info['filters']['|'.join([category, region, status])] = {
                        'revenue': float(revenue),
                        'cogs': float(cost),
                        'orders': len(unique_orders),
                        'customers': int(unique_orders.customer_id.nunique()),
                        'returns': int(filtered_returns.order_id.nunique()),
                        'status': unique_orders.order_status.value_counts().to_dict(),
                        'reasons': filtered_returns.return_reason.value_counts().head(6).to_dict(),
                        'top': records(top_products),
                        'series': records(time_series),
                        'topCategory': str(filtered_category_revenue.index[0]),
                        'topShare': float(filtered_category_revenue.iloc[0] / revenue) if revenue else 0,
                        'promo': promo_name,
                        'promoRevenue': promo_value,
                        'net': float(filtered_lines.Net.sum()),
                        'discount': float(filtered_lines.discount_amount.sum())
                    }
        data['periods'][key] = period_info
    return data, sales

# 3. BÀI TOÁN 2 - PHÂN CỤM KHÁCH HÀNG
def build_cluster_data(data, model_dir):
    """Đọc kết quả RFM chính thức; bổ sung dữ liệu PCA và các chế độ đối chứng."""
    # PCA được fit trên toàn tập RFM gốc; chỉ lấy mẫu điểm để vẽ.
    rfm = pd.read_csv(model_dir / 'phan_khuc/combined_v1/ket_qua_phan_cum.csv')
    scaled_rfm = StandardScaler().fit_transform(rfm[['Recency', 'Frequency', 'Monetary']])
    pca = PCA(n_components=2)
    pca_points = pca.fit_transform(scaled_rfm)
    rng = np.random.default_rng(42)
    sample_indices = np.sort(rng.choice(len(rfm), min(3500, len(rfm)), replace=False))
    segments = []
    for cluster_id, members in rfm.groupby('cluster'):
        mask = rfm.cluster.eq(cluster_id).to_numpy()
        segments.append({
            'cluster': int(cluster_id),
            'name': members.segment.iloc[0],
            'n': len(members),
            'R': float(members.Recency.median()),
            'F': float(members.Frequency.median()),
            'M': float(members.Monetary.median()),
            'avgM': float(members.Monetary.mean()),
            'avgF': float(members.Frequency.mean()),
            'net': float(members.Monetary.sum()),
            'center': pca_points[mask].mean(axis=0).round(4).tolist()
        })
    # Silhouette từ notebook chính; PCA điểm lấy mẫu chỉ cho hình, số liệu hồ sơ toàn tập.
    histograms = {}
    for feature, bins in BINS.items():
        counts = pd.cut(rfm[feature], bins=bins).value_counts(sort=False)
        histograms[feature] = [{'label': str(interval), 'n': int(count)} for interval, count in counts.items()]
    data['cluster'] = {
        'n': len(rfm),
        'active60': int(rfm.Recency.le(60).sum()),
        'segments': segments,
        'pca': [
            [
                round(float(pca_points[index, 0]), 4),
                round(float(pca_points[index, 1]), 4),
                int(rfm.cluster.iloc[index]),
            ]
            for index in sample_indices
        ],
        'variance': pca.explained_variance_ratio_.tolist(),
        'hist': histograms,
        'median': {feature: float(rfm[feature].median()) for feature in histograms},
        'silhouette': 0.4589,
        'db': 0.7433,
        'source': 'PC03, PC06; TN1, K-Means k=3; PCA lấy mẫu 3.500 để hiển thị'
    }
    add_views(data, rfm)

# 3B. ĐỌC KẾT QUẢ THỰC NGHIỆM PHÂN CỤM TỪ NOTEBOOK PC03
def read_cluster_experiments(notebook):
    """Đọc bảng kết quả đã lưu, không huấn luyện lại hoặc thay nhãn cụm."""
    full_columns = {
        'Thí nghiệm': 'representation',
        'Số cụm': 'clusters',
        'Silhouette mẫu': 'silhouette',
        'Davies–Bouldin toàn tập': 'davies_bouldin',
        'Inertia': 'inertia',
        'Tỷ trọng cụm nhỏ nhất': 'min_cluster_share',
        'Tỷ trọng cụm lớn nhất': 'max_cluster_share',
    }
    sample_columns = [
        'run_id', 'algorithm', 'params', 'clusters', 'coverage',
        'min_cluster_share_all', 'max_cluster_share_all', 'noise_share',
        'silhouette', 'davies_bouldin', 'calinski_harabasz',
        'converged', 'eligible',
    ]
    full = None
    sample = None

    for cell in notebook['cells']:
        for output in cell.get('outputs', []):
            html = ''.join(output.get('data', {}).get('text/html', []))
            if '<table' not in html:
                continue
            for frame in pd.read_html(StringIO(html), flavor='lxml', displayed_only=False):
                if set(full_columns).issubset(frame.columns):
                    if full is None or len(frame) > len(full):
                        full = frame[list(full_columns)].rename(columns=full_columns)
                if set(sample_columns).issubset(frame.columns):
                    if sample is None or len(frame) > len(sample):
                        sample = frame[sample_columns].copy()

    if full is None or sample is None:
        raise ValueError('PC03 chưa lưu đầy đủ bảng kết quả thực nghiệm.')

    # Giữ độ chính xác đã hiển thị trong notebook, giá trị thiếu thành null.
    return {
        'full': json.loads(full.to_json(orient='records', double_precision=10)),
        'sample': json.loads(sample.to_json(orient='records', double_precision=10)),
    }

# 4. BÀI TOÁN 3 - DỰ BÁO DOANH THU
def build_forecast_data(data, model_dir, sales):
    """Tổng hợp dự báo và sai số; không tính metric cho kỳ chưa có nhãn."""
    prediction_path = model_dir / 'du_bao/forecast_predictions.csv'
    future_path = model_dir / 'du_bao/future_predictions.csv'
    if not prediction_path.exists():
        raise FileNotFoundError('Chạy tools/run_forecast.py trước khi import.')
    predictions = pd.read_csv(prediction_path)
    actual = sales.assign(Date=sales.Date.dt.strftime('%Y-%m-%d'))
    joined = predictions.merge(actual, on='Date', suffixes=('', '_actual'), validate='many_to_one')
    scores = []
    for (split, method, fold), group in joined.groupby(['Split', 'Method', 'Fold']):
        for target in ['Revenue', 'COGS']:
            actual_values = group[target + '_actual']
            predicted_values = group[target]
            scores.append({
                'split': split,
                'method': method,
                'fold': int(fold),
                'target': target,
                'mae': float(mean_absolute_error(actual_values, predicted_values)),
                'rmse': float(mean_squared_error(actual_values, predicted_values) ** 0.5),
                'r2': float(r2_score(actual_values, predicted_values))
            })
    score_table = pd.DataFrame(scores)
    average_scores = (
        score_table.groupby(['split', 'method', 'target'])[['mae', 'rmse', 'r2']]
        .mean().reset_index()
    )
    test_predictions = predictions[predictions.Split.eq('test')]
    future = pd.read_csv(future_path) if future_path.exists() else pd.DataFrame(columns=predictions.columns)
    data['forecast'] = {
        'scores': records(average_scores),
        'folds': records(score_table),
        'test': {
            method: records(group[['Date', 'Revenue', 'COGS']])
            for method, group in test_predictions.groupby('Method')
        },
        'future': {
            method: records(group[['Date', 'Revenue', 'COGS']])
            for method, group in future.groupby('Method')
        },
        'best': 'Hybrid Ensemble phân rã và phân khúc',
        'validationBest': 'Mùa vụ mức gốc cố định + hiệu ứng thứ',
        'trainEnd': '2021-07-01',
        'futureTrainEnd': '2022-12-31'
    }

# 5. XUẤT JSON VÀ KHỞI ĐỘNG PIPELINE
def save_dashboard(data, output_path):
    """Xuất JSON có thụt lề; không thay đổi các giá trị tính toán."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding='utf-8',
    )
    print('Đã xuất', output_path, output_path.stat().st_size, flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('project', type=Path, help='Đường dẫn đến đồ án Python')
    parser.add_argument('--out', type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    raw_dir = args.project / 'data/raw'
    model_dir = args.project / 'data/model'

    print('[1/4] Tổng hợp dữ liệu kinh doanh', flush=True)
    data, sales = build_business_data(raw_dir)

    print('[2/4] Tổng hợp kết quả phân cụm', flush=True)
    build_cluster_data(data, model_dir)
    notebook_path = (args.project / "notebook/05_phan_khuc_khach_hang"
                     / "PC03_thuc_nghiem_va_lua_chon_mo_hinh.ipynb")
    with notebook_path.open(encoding="utf-8") as notebook_file:
        data["clusterExperiments"] = read_cluster_experiments(json.load(notebook_file))

    print('[3/4] Tổng hợp kết quả dự báo', flush=True)
    build_forecast_data(data, model_dir, sales)

    print('[4/4] Xuất dữ liệu cho web', flush=True)
    save_dashboard(data, args.out)


if __name__ == '__main__':
    main()