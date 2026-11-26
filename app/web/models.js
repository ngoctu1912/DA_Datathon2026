'use strict';

// TRANG MÔ HÌNH ML
function models() {
    // Hai bài toán ML có tiêu chí đánh giá riêng.
    const taskTabs = tabs('modelTask', [
        ['cluster', 'Phân cụm khách hàng'],
        ['forecast', 'Dự báo doanh thu']
    ], state.modelTask);

    return head('Mô hình ML', '', taskTabs)
        + (state.modelTask === 'cluster' ? clusterModelResults() : forecastModelResults());
}

// BÀI TOÁN 2 — THỰC NGHIỆM PHÂN CỤM KHÁCH HÀNG
function clusterModelResults() {
    const experiments = D.clusterExperiments;
    if (!experiments) {
        exportRows = [];
        return card('Đánh giá phân cụm', '', '<div class="empty">Chưa có kết quả thực nghiệm PC03.</div>');
    }

    const isFull = state.modelClusterScope === 'full';
    const source = isFull ? experiments.full : experiments.sample;
    const algorithm = state.modelClusterAlgorithm;
    const rows = isFull || algorithm === 'all'
        ? source
        : source.filter(row => row.algorithm === algorithm);
    exportRows = rows;

    // Không xếp hạng chung giữa mô hình toàn tập và đối chứng trên mẫu.
    const controls = option('modelClusterScope', [
        ['full', 'K-Means toàn tập'],
        ['sample', 'Đối chứng trên mẫu']
    ], state.modelClusterScope)
        + (isFull ? '' : option('modelClusterAlgorithm', [
            ['all', 'Tất cả thuật toán'],
            ...['K-Means', 'Hierarchical', 'GMM', 'DBSCAN'].map(name => [name, name])
        ], algorithm));

    const chosen = experiments.full.find(row => row.representation === 'TN1' && row.clusters === 3);
    const summary = `<div class="grid three">
        ${metric('MÔ HÌNH ĐÃ CHỌN', 'K-Means · K = 3', 'TN1 · ' + fmt(D.cluster.n) + ' khách', 'verified')}
        ${metric('SILHOUETTE', fmt(chosen?.silhouette, 4), 'Mẫu 5.000 khách', 'science')}
        ${metric('DAVIES–BOULDIN', fmt(chosen?.davies_bouldin, 4), 'Toàn tập', 'science')}
    </div>`;

    let resultTable;
    if (isFull) {
        resultTable = table([
            'THÍ NGHIỆM', 'SỐ CỤM', 'SILHOUETTE', 'DAVIES–BOULDIN', 'INERTIA', 'CỤM NHỎ NHẤT'
        ], rows.map(row => [
            `K-Means · ${esc(row.representation)}${row === chosen ? ' <span class="badge green">Đã chọn</span>' : ''}`,
            fmt(row.clusters),
            fmt(row.silhouette, 4),
            fmt(row.davies_bouldin, 4),
            fmt(row.inertia, 2),
            pct(row.min_cluster_share)
        ]));
    } else {
        resultTable = table([
            'THUẬT TOÁN', 'CẤU HÌNH', 'SỐ CỤM', 'SILHOUETTE', 'DAVIES–BOULDIN',
            'CỤM NHỎ NHẤT', 'NHIỄU', 'SÀNG LỌC'
        ], rows.map(row => [
            esc(row.algorithm),
            esc(clusterParameterLabel(row)),
            fmt(row.clusters),
            fmt(row.silhouette, 4),
            fmt(row.davies_bouldin, 4),
            fmt(row.min_cluster_share_all * 100, 2) + '%',
            fmt(row.noise_share * 100, 2) + '%',
            row.eligible ? 'Đạt' : 'Không đạt'
        ]));
    }

    return summary + card(
        'So sánh mô hình phân cụm',
        isFull
            ? `${rows.length} cấu hình · ${fmt(D.cluster.n)} khách · Silhouette trên mẫu 5.000`
            : `${rows.length} cấu hình · Mẫu 5.000 khách · TN1`,
        resultTable,
        `<div class="controls">${controls}
            <button class="outline" data-action="export">${icon('file_download')} Xuất CSV</button>
        </div>`
    );
}

// Chỉ hiển thị các tham số có trong bảng kết quả lưu từ PC03.
function clusterParameterLabel(row) {
    if (row.algorithm !== 'DBSCAN') return `k = ${row.clusters}`;
    const eps = row.params.match(/"eps"\s*:\s*([\d.]+)/);
    const min = row.params.match(/"min_samples"\s*:\s*(\d+)/);
    return eps && min ? `eps = ${fmt(Number(eps[1]), 4)} · min = ${min[1]}` : row.params;
}

// BÀI TOÁN 3 — THỰC NGHIỆM DỰ BÁO DOANH THU
function forecastModelResults() {
    // 1. Chọn tập đánh giá, chỉ tiêu và mô hình.
    const split = state.modelSplit;
    const target = state.modelTarget;
    const all = scores(split, target);
    const selected = state.modelFilter;
    const list = all.filter(row => selected === 'all' || row.method === selected);
    const best = all[0];
    const splitLabel = split === 'validation' ? 'Validation' : 'Test';
    exportRows = list;

    const controls = option('modelSplit', [
        ['validation', 'Validation'],
        ['test', 'Test']
    ], split)
        + option('modelTarget', [['Revenue', 'Revenue'], ['COGS', 'COGS']], target)
        + option('modelFilter', [
            ['all', 'Tất cả mô hình'],
            ...all.map(row => [row.method, short(row.method)])
        ], selected);


    // 2. Bảng so sánh kết quả. MAE thấp nhất xét trong tập đang chọn.
    const resultTable = table(['MÔ HÌNH', 'MAE', 'RMSE', 'R²', 'CHI TIẾT'], list.map(row => [
        `<b>${esc(row.method)}</b>${row === best ? ' <span class="badge green">MAE thấp nhất</span>' : ''}`,
        fmt(row.mae, 2),
        fmt(row.rmse, 2),
        fmt(row.r2, 4),
        `<button class="outline small" data-model="${esc(row.method)}">Xem</button>`
    ]));

    const comparison = card(
        'So sánh mô hình',
        `${splitLabel} • ${target} • ${list.length} phương pháp`,
        resultTable,
        `<div class="controls">${controls}<button class="outline" data-action="export">${icon('file_download')} Xuất CSV</button></div>`
    );

    // 3. Diễn biến sai số qua từng lượt validation của mô hình đang xem.
    // Khi chọn tất cả, biểu đồ dùng mô hình có MAE thấp nhất ở validation.
    const method = selected === 'all' ? scores('validation', target)[0]?.method : selected;
    const folds = D.forecast.folds
        .filter(row => row.split === 'validation' && row.target === target && row.method === method)
        .sort((a, b) => a.fold - b.fold);

    const validationChart = card(
        'Sai số qua các lượt validation',
        method ? `${short(method)} • ${target}` : '',
        lineChart(folds.map(row => ({
            Date: `Fold ${row.fold}`,
            MAE: row.mae,
            RMSE: row.rmse
        })), ['MAE', 'RMSE'], 250),
        legend(['MAE', 'RMSE'])
    );

    return comparison + validationChart;
}

// Kết quả của một phương pháp trên các tập đánh giá đã lưu.
function details(method) {
    const rows = D.forecast.scores.filter(row => row.method === method);
    dialog(method, table(['TẬP', 'CHỈ TIÊU', 'MAE', 'RMSE', 'R²'], rows.map(row => [
        esc(row.split),
        esc(row.target),
        fmt(row.mae, 2),
        fmt(row.rmse, 2),
        fmt(row.r2, 4)
    ])));
}