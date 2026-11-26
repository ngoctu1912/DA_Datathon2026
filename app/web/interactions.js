'use strict';

// XUẤT CSV VÀ HỘP THOẠI
function download(rows, name) {
    if (!rows?.length) {
        dialog('Không có dữ liệu', '<p>Không có bản ghi phù hợp để xuất.</p>');
        return;
    }
    let headers = Object.keys(rows[0]);
    let cell = v => '"' + String(v ?? '').replace(/"/g, '""') + '"';
    let text = '\ufeff' + [headers.map(cell).join(','), ...rows.map(r => headers.map(k => cell(r[k])).join(','))].join('\r\n');
    let u = URL.createObjectURL(new Blob([text], { type: 'text/csv;charset=utf-8;' }));
    let a = document.createElement('a');
    a.href = u;
    a.download = name;
    a.click();
    setTimeout(() => URL.revokeObjectURL(u), 1000);
}

function dialog(title, html) {
    $('#dialog-title').textContent = title;
    $('#dialog-body').innerHTML = html;
    $('#dialog').showModal();
}

// XỬ LÝ SỰ KIỆN GIAO DIỆN
// Thay đổi bộ lọc: lưu trạng thái rồi hiển thị lại trang.
app.addEventListener('change', e => {
    let id = e.target.id;
    if ([
        'cat',
        'region',
        'status',
        'clusterAlgorithm',
        'clusterK',
        'method',
        'forecastMode',
        'horizon',
        'target',
        'modelSplit',
        'modelTarget',
        'modelFilter',
        'modelClusterScope',
        'modelClusterAlgorithm'
    ].includes(id)) {
        state[id] = e.target.value;
        if (id === 'clusterAlgorithm') {
            state.clusterK = '3';
            state.clusterWindow = 'all';
        }
        if (id === 'modelClusterScope')
            state.modelClusterAlgorithm = 'all';
        if (id === 'modelSplit' || id === 'modelTarget')
            state.modelFilter = 'all';
        if (id === 'forecastMode')
            state.method = D.forecast.best;
        render();
    }
});
// Áp dụng khoảng ngày Tổng quan sau khi xác thực cả hai đầu mốc.
app.addEventListener('submit', event => {
    if (event.target.id !== 'overview-date-form') return;
    event.preventDefault();
    const start = $('#overview-start').value;
    const end = $('#overview-end').value;
    if (!start || !end || start > end || start < D.dates.start || end > D.dates.end) {
        dialog('Khoảng ngày không hợp lệ',
            '<p>Chọn ngày bắt đầu không lớn hơn ngày kết thúc và nằm trong lịch sử dữ liệu.</p>');
        return;
    }
    state.overviewStart = start;
    state.overviewEnd = end;
    render();
});

// Điều phối nút bấm, tab và các hành động theo trang.
app.addEventListener('click', e => {
    let b = e.target.closest('button');
    if (!b)
        return;
    if (b.dataset.tab) {
        state[b.dataset.tab] = b.dataset.value;
        render();
        // Giữ tiêu điểm khi chuyển tab xếp hạng bằng bàn phím.
        if (b.dataset.tab === 'rankingTab') {
            app.querySelector(`[data-tab="rankingTab"][data-value="${state.rankingTab}"]`)?.focus({ preventScroll: true });
        }
        return;
    }
    if (b.dataset.go) {
        location.hash = b.dataset.go;
        return;
    }
    if (b.dataset.model) {
        details(b.dataset.model);
        return;
    }
    switch (b.dataset.action) {
        case 'overviewGrain': {
            const value = b.dataset.value;
            if (!['auto', 'day', 'month', 'year'].includes(value)) break;
            // Giữ cả hai ô ngày đang nhập nếu người dùng chưa nhấn Áp dụng.
            const draftStart = $('#overview-start').value;
            const draftEnd = $('#overview-end').value;
            state.overviewGrain = value;
            render();
            $('#overview-start').value = draftStart;
            $('#overview-end').value = draftEnd;
            app.querySelector(`[data-action="overviewGrain"][data-value="${value}"]`)?.focus();
            break;
        }
        case 'overviewReset':
            state.overviewStart = D.dates.start;
            state.overviewEnd = D.dates.end;
            state.overviewGrain = 'auto';
            render();
            break;
        case 'export':
            download(exportRows, `analytix_${route}.csv`);
            break;
        case 'submission':
            download((D.forecast.future[state.method] || []).map(r => ({
                Date: r.Date, Revenue: r.Revenue, COGS: r.COGS
            })), 'submission.csv');
            break;
        case 'products':
            dialog('Top sản phẩm', table(['SẢN PHẨM', 'DANH MỤC', 'REVENUE'], businessData().top.map(r => [esc(r.product_name), esc(r.category), money(r.Revenue)])));
            break;
        case 'returns':
            dialog('Lý do hoàn trả', table(['LÝ DO', 'SỐ BẢN GHI'], Object.entries(businessData().reasons).map(([n, v]) => [esc(label(n)), fmt(v)])));
            break;
        case 'clusterCompare':
            dialog('Đối chứng thuật toán — PC03', table(['THUẬT TOÁN', 'CẤU HÌNH / MẪU', 'SILHOUETTE', 'DAVIES–BOULDIN'], [
                ['K-Means (chính)', 'TN1, k=3; toàn tập / mẫu', '0,4589', '0,7433'],
                ['K-Means', 'k=3; mẫu 5.000', '0,4595', '0,7370'],
                ['Hierarchical', 'k=3; mẫu 5.000', '0,3910', '0,6713'],
                ['GMM', 'k=3; mẫu 5.000', '0,2777', '1,0795'],
                ['DBSCAN', '2 cụm; cụm nhỏ, không eligible', '0,6784', '0,2583']
            ]) + '<p class="subtitle">Các thuật toán đối chứng không có nhãn toàn bộ khách trong CSV bàn giao; không thay nhãn bằng kết quả giả.</p>');
            break;
        case 'params':
            dialog('Kiến trúc Hybrid Ensemble', `<p>Phân rã số dòng hàng và giá trị bình quân, mùa vụ lịch, CatBoost, recovery gate, hiệu chỉnh ngoài mẫu, nhánh xu hướng giảm dần, chu kỳ hai năm và phân khúc sản phẩm.</p>${
                table(['THÀNH PHẦN', 'THAM SỐ NOTEBOOK'], [
                ['CatBoost', '450 iterations, depth 5, learning rate 0.045, seed 123'],
                ['Phối hợp dạng ngày', 'Factor 0,65; historical 0,20; CatBoost 0,15'],
                ['Validation', '3 lượt theo thời gian, 548 ngày/lượt']
            ])
            }<p class="subtitle">Đổi siêu tham số trong notebook 02, sau đó chạy lại script import. Không sửa mô hình từ test trên web.</p>`);
            break;

    }
});
$('#close-dialog').onclick = () => $('#dialog').close();
$('#nav-toggle').onclick = () => document.querySelector('.sidebar').classList.toggle('open');

// TỔNG QUAN - HIỂN THỊ GIÁ TRỊ KHI DI CHUỘT VÀO BIỂU ĐỒ
app.addEventListener('pointerover', event => {
    const point = event.target.closest('.overview-point');
    if (!point) return;

    const plot = point.closest('.overview-revenue-plot');
    const readout = plot.querySelector('.overview-hover-value');
    const crosshair = plot.querySelector('.overview-crosshair');

    readout.textContent = `${point.dataset.date}  •  Doanh thu: ${point.dataset.revenue}  •  COGS: ${point.dataset.cogs}`;
    readout.hidden = false;
    crosshair.setAttribute('x1', point.dataset.x);
    crosshair.setAttribute('x2', point.dataset.x);
    crosshair.setAttribute('visibility', 'visible');
});

app.addEventListener('pointerout', event => {
    const point = event.target.closest('.overview-point');
    if (!point) return;
    const plot = point.closest('.overview-revenue-plot');
    if (event.relatedTarget?.closest?.('.overview-point')?.closest('.overview-revenue-plot') === plot) return;

    plot.querySelector('.overview-crosshair').setAttribute('visibility', 'hidden');
    const readout = plot.querySelector('.overview-hover-value');
    readout.textContent = '';
    readout.hidden = true;
});

// BIỂU ĐỒ CHUNG - HIỂN THỊ GIÁ TRỊ KHI DI CHUỘT
function sameHoverHost(a, b) {
    return a && b && a.closest?.('.hover-host') === b.closest?.('.hover-host');
}

app.addEventListener('pointerover', event => {
    const point = event.target.closest('.hover-point');
    if (!point || point.classList.contains('overview-point')) return;

    const host = point.closest('.hover-host');
    if (!host) return;

    const readout = host.querySelector('.chart-hover-value');
    if (readout) {
        readout.textContent = point.dataset.readout || '';
        readout.hidden = !point.dataset.readout;
    }

    const crosshair = host.querySelector('.chart-crosshair');
    if (crosshair && point.dataset.x) {
        crosshair.setAttribute('x1', point.dataset.x);
        crosshair.setAttribute('x2', point.dataset.x);
        crosshair.setAttribute('visibility', 'visible');
    }
});

app.addEventListener('pointerout', event => {
    const point = event.target.closest('.hover-point');
    if (!point || point.classList.contains('overview-point')) return;

    const host = point.closest('.hover-host');
    const nextPoint = event.relatedTarget?.closest?.('.hover-point');
    if (!host || sameHoverHost(nextPoint, point)) return;

    const readout = host.querySelector('.chart-hover-value');
    if (readout) {
        readout.textContent = '';
        readout.hidden = true;
    }

    const crosshair = host.querySelector('.chart-crosshair');
    if (crosshair) {
        crosshair.setAttribute('visibility', 'hidden');
    }
});