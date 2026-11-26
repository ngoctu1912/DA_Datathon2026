import numpy as np
import pandas as pd
from sklearn.cluster import KMeans, AgglomerativeClustering, DBSCAN
from sklearn.decomposition import PCA
from sklearn.metrics import silhouette_score, davies_bouldin_score
from sklearn.mixture import GaussianMixture
from sklearn.neighbors import NearestNeighbors
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

# 1. CẤU HÌNH RFM
RFM_FEATURES = ['Recency', 'Frequency', 'Monetary']
BINS = {
    'Recency': [-1, 30, 90, 180, 365, 730, np.inf],
    'Frequency': [-1, 1, 3, 5, 10, 20, np.inf],
    'Monetary': [-1, 25000, 50000, 100000, 250000, 500000, np.inf],
}
# 2. CHUẨN BỊ DỮ LIỆU HIỂN THỊ CHO MỘT KẾT QUẢ PHÂN CỤM
def make_view(frame, xy, variance, labels, description, sil, db, seed=42):
    """Tổng hợp hồ sơ cụm, mẫu điểm PCA, phân phối RFM và các chỉ số."""
    customers = frame.copy()
    customers['cluster'] = labels
    customer_count = len(customers)
    segments = []

    # DBSCAN dùng -1 cho điểm nhiễu; hiển thị thành nhóm riêng.
    display_labels = {
        label: index for index, label in enumerate(sorted(np.unique(labels)))
    }

    for cluster_id, members in customers.groupby('cluster'):
        mask = customers.cluster.eq(cluster_id).to_numpy()

        if 'segment' in members:
            name = str(members.segment.iloc[0])
        elif cluster_id == -1:
            name = 'Nhiễu (DBSCAN)'
        else:
            name = f'Cụm {cluster_id}'

        segments.append({
            'cluster': display_labels[cluster_id],
            'rawCluster': int(cluster_id),
            'name': name,
            'n': len(members),
            'R': float(members.Recency.median()),
            'F': float(members.Frequency.median()),
            'M': float(members.Monetary.median()),
            'avgM': float(members.Monetary.mean()),
            'avgF': float(members.Frequency.mean()),
            'net': float(members.Monetary.sum()),
            'center': xy[mask].mean(axis=0).round(4).tolist(),
        })

    # Chỉ lấy tối đa 1.800 điểm để vẽ, không giảm số khách tính KPI.
    sample_indices = np.random.default_rng(seed).choice(
        customer_count, min(customer_count, 1800), replace=False
    )
    histograms = {}
    for feature, bins in BINS.items():
        counts = pd.cut(customers[feature], bins=bins).value_counts(sort=False)
        histograms[feature] = [
            {'label': str(interval), 'n': int(count)}
            for interval, count in counts.items()
        ]

    return {
        'n': customer_count,
        'active60': int(customers.Recency.le(60).sum()),
        'segments': segments,
        'pca': [
            [round(float(xy[index, 0]), 4), round(float(xy[index, 1]), 4),
             display_labels[labels[index]]]
            for index in sample_indices
        ],
        'variance': variance.tolist(),
        'hist': histograms,
        'median': {feature: float(customers[feature].median()) for feature in BINS},
        'silhouette': sil,
        'db': db,
        'source': description,
        'actualK': int(len(set(labels) - {-1})),
        'noise': int(np.sum(labels == -1)),
    }

# 3. BỘ LỌC RECENCY CỦA MÔ HÌNH CHÍNH THỨC
def build_recency_views(rfm):
    """Tạo 3 tập con theo Recency, giữ nguyên nhãn và màu cụm PC06."""
    scaled_rfm = StandardScaler().fit_transform(rfm[RFM_FEATURES])
    pca = PCA(n_components=2)
    points = pca.fit_transform(scaled_rfm)
    views = {}

    for window in [30, 90, 365]:
        mask = rfm.Recency.le(window).to_numpy()
        subset = rfm.loc[mask].reset_index(drop=True)
        description = (
            f'Khách có Recency ≤ {window} ngày tại 31/12/2022; giữ nguyên nhãn PC06'
        )
        view = make_view(
            subset, points[mask], pca.explained_variance_ratio_,
            subset.cluster.to_numpy(), description, None, None,
        )

        mapping = {
            segment['cluster']: segment['rawCluster'] for segment in view['segments']
        }
        for segment in view['segments']:
            segment['cluster'] = segment['rawCluster']
        for point in view['pca']:
            point[2] = mapping[point[2]]

        view['actualK'] = 3
        views[f'main-{window}'] = view

    return views

# 4. KHỞI TẠO THUẬT TOÁN ĐỐI CHỨNG
def create_model(algorithm, k, features):
    """Giữ nguyên cấu hình thuật toán, số cụm và seed của bản trước."""
    eps = None

    if algorithm == 'K-Means':
        model = KMeans(n_clusters=k, n_init=10, random_state=42, max_iter=300)
    elif algorithm == 'GMM':
        model = GaussianMixture(n_components=k, random_state=42, n_init=3)
    elif algorithm == 'Hierarchical':
        model = AgglomerativeClustering(n_clusters=k, linkage='ward')
    else:
        distances = NearestNeighbors(n_neighbors=5).fit(features).kneighbors(features)[0]
        eps = float(np.quantile(distances[:, -1], 0.99))
        model = DBSCAN(eps=eps, min_samples=5)

    return model, eps

# 5. CHẠY VÀ ĐÁNH GIÁ CÁC MÔ HÌNH ĐỐI CHỨNG
def build_comparison_views(rfm):
    """Thử thuật toán trên mẫu tối đa 5.000 khách, chuẩn hóa riêng mẫu."""
    sample_indices = np.random.default_rng(42).choice(
        len(rfm), min(5000, len(rfm)), replace=False
    )
    sample = (
        rfm.iloc[sample_indices]
        .drop(columns=['segment', 'cluster'])
        .reset_index(drop=True)
    )
    features = StandardScaler().fit_transform(sample[RFM_FEATURES])
    pca = PCA(n_components=2)
    points = pca.fit_transform(features)
    views = {}

    with threadpool_limits(limits=1):
        for algorithm in ['K-Means', 'GMM', 'Hierarchical', 'DBSCAN']:
            # DBSCAN không yêu cầu số cụm k.
            cluster_counts = [0] if algorithm == 'DBSCAN' else range(2, 7)
            for k in cluster_counts:
                model, eps = create_model(algorithm, k, features)
                labels = model.fit_predict(features)

                # Loại điểm nhiễu (-1) khi tính chỉ số nội tại.
                valid = labels != -1
                unique_clusters = len(set(labels[valid]))
                silhouette = None
                davies_bouldin = None
                if 1 < unique_clusters < valid.sum():
                    silhouette = float(silhouette_score(features[valid], labels[valid]))
                    davies_bouldin = float(davies_bouldin_score(features[valid], labels[valid]))

                description = (
                    'Thực nghiệm bổ sung cho web, mẫu 5.000 khách RFM, '
                    'seed 42; không phải nhãn bàn giao.'
                )
                if algorithm == 'DBSCAN':
                    description += f' eps={eps:.4f}, min_samples=5; chỉ số bỏ nhiễu.'

                view = make_view(
                    sample, points, pca.explained_variance_ratio_,
                    labels, description, silhouette, davies_bouldin,
                )

                # Điều kiện đối chứng: 2–8 cụm, ít nhất 95% không nhiễu,
                # cụm nhỏ nhất chiếm tối thiểu 2% mẫu.
                view['eligible'] = bool(
                    2 <= unique_clusters <= 8
                    and valid.mean() >= 0.95
                    and min(np.bincount(labels[valid]), default=0) >= 0.02 * len(sample)
                ) if valid.any() else False

                views[f'{algorithm}-{k}'] = view

    return views
# 6. GHÉP KẾT QUẢ VÀO DỮ LIỆU DASHBOARD
def add_views(data, rfm):
    """Được gọi bởi build_data.py sau khi tổng hợp phân cụm chính thức."""
    data['cluster']['actualK'] = 3
    data['cluster']['noise'] = 0

    views = build_recency_views(rfm)
    views.update(build_comparison_views(rfm))
    data['clusterViews'] = views