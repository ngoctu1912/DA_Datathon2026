'use strict';

// TRANG PHÂN CỤM KHÁCH HÀNG
const strategies = [
    'Nhắc mua có chọn lọc với ngân sách giới hạn; khảo sát nguyên nhân.',
    'Gợi ý bổ sung danh mục đã mua; thử thông điệp theo chu kỳ.',
    'Duy trì trải nghiệm, chăm sóc ưu tiên và quyền lợi có kiểm soát.'
];

function clusters() {
    // 1. Chọn kết quả phân cụm chính thức hoặc đối chứng.
    let main = state.clusterAlgorithm === 'main',
        key = main ? (state.clusterWindow === 'all' ? 'main' : `main-${state.clusterWindow}`) : `${state.clusterAlgorithm}-${state.clusterAlgorithm === 'DBSCAN' ? 0 : state.clusterK}`,
        c = key === 'main' ? D.cluster : D.clusterViews?.[key] || D.cluster,
        net = c.segments.reduce((a, b) => a + b.net, 0);
    let algo = main ? 'K-Means (TN1 – bàn giao)' : state.clusterAlgorithm;
    let strategy = s => main ? strategies[s.rawCluster ?? s.cluster] : 'Chỉ đối chứng kỹ thuật; chưa thẩm định chiến lược.';
    // 2. Chuẩn bị bảng xuất phân khúc.
    exportRows = c.segments.map(s => ({
        cluster: s.rawCluster ?? s.cluster,
        segment: s.name,
        customers: s.n,
        recency_median: s.R,
        frequency_median: s.F,
        monetary_median: s.M,
        net: s.net
    }));
    // 3. Bộ lọc thuật toán, số cụm và Recency.
    let ctrls = option(
        'clusterAlgorithm',
        [
        ['main', 'K-Means • bàn giao'],
        ['K-Means', 'K-Means • đối chứng'],
        ['GMM', 'GMM'],
        ['Hierarchical', 'Hierarchical'],
        ['DBSCAN', 'DBSCAN']
    ],
        state.clusterAlgorithm
    ) + (main ? `<span class="badge">K = 3</span>` : state.clusterAlgorithm === 'DBSCAN' ? `<span class="badge">K tự xác định</span>` : option('clusterK', [
        2, 3, 4, 5, 6
    ].map(x => [x, 'K = ' + x]), state.clusterK)) + (main ? tabs(
        'clusterWindow',
        [['30', '30 ngày'], ['90', '90 ngày'], ['365', '12 tháng'], ['all', 'Toàn tập']],
        state.clusterWindow
    ) : '')
        + `<button class="outline" data-action="clusterCompare">Đối chứng</button><button class="primary" data-action="export">${
        icon('file_download')
    } Xuất phân khúc</button>`;
    // 4. Hiển thị KPI, PCA, RFM và hồ sơ phân khúc.
    return head('Phân cụm khách hàng', `Mô hình học máy RFM • ${algo} • mốc 31/12/2022`, ctrls)
        + `<div class="grid four">${
        metric('TỔNG KHÁCH HÀNG', fmt(c.n), main ? 'Có đơn delivered đủ điều kiện' : 'Mẫu RFM 5.000 khách', 'groups')
    }${
        metric('KHÁCH HOẠT ĐỘNG', fmt(c.active60), pct(c.active60 / c.n) + ' có Recency ≤ 60 ngày', 'groups')
    }${
        metric('SỐ CỤM', String(c.actualK || 3) + ' cụm', c.noise ? fmt(c.noise) + ' điểm nhiễu' : algo, 'group_work')
    }${
        metric(
        'SILHOUETTE SCORE',
        fmt(c.silhouette, 4),
        c.db != null ? 'Davies–Bouldin: ' + fmt(c.db, 4) : 'Không tính lại chỉ số khi lọc',
        'verified'
    )
    }</div>`
        + card(
        'Phân tán cụm khách hàng (2D PCA Cluster Map)',
        c.source,
        pcaChart(c)
        + `<div class="chart-footer"><span>Hai trục PCA giải thích ${
        pct(c.variance.reduce((a, b) => a + b, 0))
    } phương sai của tập fit.</span><span>${
        fmt(c.pca.length)
    } điểm hiển thị</span></div>`,
        legend(c.segments.map(s => s.name), c.segments.map(s => colors[s.cluster % colors.length]))
    )
        + `<div class="grid two">${
        card(
        'Phân bố chỉ số RFM',
        'Số khách theo các khoảng giá trị',
        histChart(c.hist[state.hist], c),
        tabs('hist', [['Recency', 'Recency (R)'], ['Frequency', 'Frequency (F)'], ['Monetary', 'Monetary (M)']], state.hist)
    )
    }${
        card(
        'Tỷ trọng từng phân khúc khách hàng',
        'Quy mô phân bổ khách đủ điều kiện',
        donut(c.segments.map(s => ({ name: s.name, n: s.n })), fmt(c.n))
    )
    }</div><section class="card table-card"><div class="card-head"><div><h2>Hồ sơ chi tiết phân khúc RFM</h2><p class="subtitle">Trung vị trên thang gốc ${
        main ? 'và đề xuất hành động từ PC06' : '• đối chứng kỹ thuật'
    }</p></div><span class="badge">${
        main ? 'combined_v1' : 'Mẫu 5.000'
    }</span></div>${
        table([
        'PHÂN KHÚC & RFM', 'QUY MÔ TỆP', 'NET TB / KHÁCH', 'TẦN SUẤT MUA', 'ĐỊNH HƯỚNG HÀNH ĐỘNG'
    ], c.segments.map(s => [
        `<b><i class="dot" style="background:${
            colors[s.cluster % colors.length]
        }"></i>${
            esc(s.name)
        }</b><small>R: ${
            fmt(s.R)
        } ngày • F: ${
            fmt(s.F)
        } • M: ${
            money(s.M)
        }</small>`,
        `${fmt(s.n)}<small>${pct(s.n / c.n)} tổng khách</small>`,
        `${money(s.avgM)}<small>${pct(s.net / net)} tổng Net</small>`,
        `${fmt(s.avgF, 1)} đơn/khách<small>Toàn lịch sử đủ điều kiện</small>`,
        esc(strategy(s))
    ]))
    }</section><div class="grid three">${
        c.segments.map(s => mini('groups', s.name, pct(s.net / net) + ' Net', strategy(s))).join('')
    }</div>`;
}