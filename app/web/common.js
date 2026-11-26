'use strict';

// CẤU HÌNH CHUNG VÀ TRẠNG THÁI ỨNG DỤNG
const $ = s => document.querySelector(s), app = $('#app');

const pages = [
    ['overview', 'Tổng quan', 'dashboard'],
    ['customers', 'Phân tích khách hàng', 'monitoring'],
    ['clusters', 'Phân cụm khách hàng', 'group_work'],
    ['forecast', 'Dự báo doanh thu', 'trending_up'],
    ['models', 'Mô hình ML', 'memory']
];

const colors = [
    '#465fd4', '#059669', '#e49a3b', '#a78bfa', '#64748b', '#e76b7c'
];

const iconPaths = {
    dashboard: 'M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z',
    monitoring: 'M3 3v18h18 M7 16l4-5 4 3 6-8',
    group_work: 'M12 3a4 4 0 1 0 0 8 4 4 0 0 0 0-8 M5 13a4 4 0 1 0 0 8 4 4 0 0 0 0-8 M19 13a4 4 0 1 0 0 8 4 4 0 0 0 0-8',
    trending_up: 'M3 17l6-6 4 4 8-9 M15 6h6v6',
    memory: 'M6 6h12v12H6z M9 9h6v6H9z M9 2v4 M15 2v4 M9 18v4 M15 18v4 M2 9h4 M2 15h4 M18 9h4 M18 15h4',
    insights: 'M3 17l6-7 5 4 7-9 M3 21h18',
    refresh: 'M20 7a9 9 0 1 0 1 9 M20 3v6h-6',
    file_download: 'M12 3v12 M7 10l5 5 5-5 M4 17v4h16v-4',
    groups: 'M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8 M4 21v-3a6 6 0 0 1 6-6h4a6 6 0 0 1 6 6v3',
    shopping_bag: 'M4 7h16l1 14H3z M8 8V5a4 4 0 0 1 8 0v3',
    payments: 'M3 5h18v14H3z M8 12h8 M12 8v8',
    inventory: 'M3 5h18v4H3z M5 9v12h14V9 M9 13h6',
    verified: 'M12 3l8 3v7c0 4-4 7-8 9-4-2-8-5-8-9V6z M8 12l3 3 5-6',
    science: 'M9 3h6 M10 3v8L4 20h16l-6-9V3 M8 16h8',
    timer: 'M12 5a8 8 0 1 0 0 16 8 8 0 0 0 0-16 M9 2h6 M12 8v5l3 2',
    category: 'M3 3h8v8H3z M14 3h7v8h-7z M3 14h8v7H3z M14 14h7v7h-7z',
    local_offer: 'M3 3h9l9 9-9 9-9-9z M7 7h.01',
    repeat: 'M4 7h15l-3-3 M19 7l-3 3 M20 17H5l3-3 M5 17l3 3'
};

function icon(n) {
    return `<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="${
        iconPaths[n] || iconPaths.insights
    }"/></svg>`;
}
document.querySelectorAll('[data-icon]').forEach(el => el.innerHTML = icon(el.dataset.icon));

let D; // Dữ liệu từ dashboard.json
let route; // Trang đang mở
// Mỗi trang có bộ lọc riêng. Làm mới chỉ đặt lại trang đang mở.
const pageDefaults = Object.freeze({
    overview: Object.freeze({
        overviewStart: null,
        overviewEnd: null,
        overviewGrain: 'auto'
    }),
    customers: Object.freeze({
        customers: 'year',
        cat: 'all',
        region: 'all',
        status: 'all',
        grain: 'month',
        rankingTab: 'products'
    }),
    clusters: Object.freeze({
        hist: 'Recency',
        clusterAlgorithm: 'main',
        clusterK: '3',
        clusterWindow: 'all'
    }),
    forecast: Object.freeze({
        forecastMode: 'test',
        horizon: 90,
        target: 'Revenue',
        method: null
    }),
    models: Object.freeze({
        modelTask: 'cluster',
        modelClusterScope: 'full',
        modelClusterAlgorithm: 'all',
        modelSplit: 'validation',
        modelTarget: 'Revenue',
        modelFilter: 'all'
    })
});

const state = Object.assign({}, ...Object.values(pageDefaults));

let exportRows = []; // Dữ liệu xuất CSV của trang hiện tại

// ĐỊNH DẠNG DỮ LIỆU VÀ NHÃN HIỂN THỊ
const esc = x => String(x ?? '').replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
}[c]));

const fmt = (x, d = 0) => x != null && Number.isFinite(+x) ? (+x).toLocaleString('vi-VN', { maximumFractionDigits: d }) : '—';

const pct = x => fmt(x * 100, 1) + '%';

const money = x => {
    if (x == null || !Number.isFinite(+x))
        return '—';
    let a = Math.abs(x);
    return a >= 1e9 ? fmt(x / 1e9, 2) + ' tỷ' : a >= 1e6 ? fmt(x / 1e6, 2) + ' triệu' : fmt(x, 0);
};

const date = x => String(x).slice(0, 10).split('-').reverse().join('/');

const short = m => m === D.forecast.best ? 'Hybrid Ensemble' : m === D.forecast.validationBest ? 'Mùa vụ + hiệu ứng thứ' : m;

function label(s) {
    return ({
        delivered: 'Đã giao',
        cancelled: 'Đã hủy',
        returned: 'Đã trả',
        paid: 'Đã thanh toán',
        created: 'Mới tạo',
        shipped: 'Đang giao',
        late_delivery: 'Giao trễ',
        wrong_size: 'Sai kích cỡ',
        damaged: 'Hư hỏng',
        defective: 'Lỗi sản phẩm',
        not_as_described: 'Không như mô tả'
    })[s] || s;
}

// THÀNH PHẦN GIAO DIỆN DÙNG CHUNG
function option(id, opts, value) {
    return `<select class="select" id="${
        id
    }" aria-label="${
        id
    }">${
        opts.map(o => {
        let [v, t] = Array.isArray(o) ? o : [o, o];
        return `<option value="${esc(v)}" ${String(v) === String(value) ? 'selected' : ''}>${esc(t)}</option>`;
    }).join('')
    }</select>`;
}

function tabs(id, opts, val) {
    return `<div class="tabs" aria-label="${
        id
    }">${
        opts.map(([v, t]) => `<button data-tab="${
        id
    }" data-value="${
        esc(v)
    }" class="${
        String(v) === String(val) ? 'active' : ''
    }">${
        esc(t)
    }</button>`).join('')
    }</div>`;
}

const periods = [['30', '30 ngày'], ['quarter', 'Quý'], ['year', 'Năm'], ['all', 'Toàn kỳ']];

function head(title, sub, controls = '', eye = '') {
    return `<div class="page-head"><div>${
        eye ? `<div class="eyebrow">${esc(eye)}</div>` : ''
    }<h1>${
        esc(title)
    }</h1>${sub ? `<p class="subtitle">${esc(sub)}</p>` : ''}</div><div class="controls">${
        controls
    }</div></div>`;
}

function metric(title, val, detail, ic = 'insights') {
    return `<div class="card metric"><div class="metric-label">${
        esc(title)
    } ${
        icon(ic)
    }</div><div class="metric-value">${
        esc(val)
    }</div><div class="metric-note">${
        esc(detail)
    }</div></div>`;
}

function mini(ic, title, val, note) {
    return `<div class="card mini"><div class="mini-icon">${
        icon(ic)
    }</div><div><div class="eyebrow">${
        esc(title)
    }</div><strong>${
        esc(val)
    }</strong><p>${
        esc(note)
    }</p></div></div>`;
}

function card(title, sub, body, right = '') {
    return `<section class="card"><div class="card-head"><div><h2>${
        esc(title)
    }</h2>${
        sub ? `<p class="subtitle">${esc(sub)}</p>` : ''
    }</div>${
        right
    }</div>${
        body
    }</section>`;
}

function table(headers, rows) {
    return `<div class="table-wrap"><table><thead><tr>${
        headers.map(h => `<th>${esc(h)}</th>`).join('')
    }</tr></thead><tbody>${
        rows.map(r => `<tr>${r.map(c => `<td>${c}</td>`).join('')}</tr>`).join('')
    }</tbody></table></div>`;
}

function legend(names, cs = colors) {
    return `<div class="legend">${
        names.map((s, i) => `<span><i class="dot" style="background:${cs[i % cs.length]}"></i>${esc(s)}</span>`).join('')
    }</div>`;
}

function notice(t) {
    return `<div class="notice">${esc(t)}</div>`;
}