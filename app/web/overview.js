'use strict';

// TRANG TỔNG QUAN
// Đếm phần tử nhỏ hơn mốc bắt đầu trong danh sách đã sắp xếp.
function countBefore(sortedDays, startIndex) {
    let left = 0;
    let right = sortedDays.length;
    while (left < right) {
        const middle = Math.floor((left + right) / 2);
        if (sortedDays[middle] < startIndex) {
            left = middle + 1;
        } else {
            right = middle;
        }
    }
    return left;
}

// Tính KPI theo khoảng ngày, bao gồm cả ngày đầu và ngày cuối.
function overviewPeriod(start, end) {
    const daily = D.overviewDaily;
    const first = daily.findIndex(row => row.date === start);
    const last = daily.findIndex(row => row.date === end);
    if (first < 0 || last < first) {
        throw new Error('Khoảng ngày không hợp lệ hoặc nằm ngoài dữ liệu.');
    }
    const period = {
        start, end, customers: 0, products: 0, orders: 0,
        repeat: 0, revenue: 0, cogs: 0,
        topCategory: 'Không ghi nhận', topShare: 0
    };
    const categoryTotals = new Map();

    // Đếm lần xuất hiện đầu tiên trong kỳ, tránh cộng trùng khách/SKU.
    for (const row of daily.slice(first, last + 1)) {
        period.orders += row.orders;
        period.customers += countBefore(row.customerPrevious, first);
        period.products += countBefore(row.productPrevious, first);
        period.repeat += countBefore(row.deliveredSecondPrevious, first)
            - countBefore(row.deliveredPrevious, first);
        for (const [category, revenue] of Object.entries(row.categoryRevenue)) {
            categoryTotals.set(category, (categoryTotals.get(category) || 0) + revenue);
        }
    }

    // Revenue và COGS từ sales.csv; danh mục từ dòng sản phẩm.
    const series = D.history.filter(row => row.Date >= start && row.Date <= end);
    for (const row of series) {
        period.revenue += row.Revenue;
        period.cogs += row.COGS;
    }
    const ranked = [...categoryTotals.entries()].sort((a, b) => b[1] - a[1]);
    const categoryRevenue = ranked.reduce((sum, item) => sum + item[1], 0);
    if (ranked.length) {
        period.topCategory = ranked[0][0];
        period.topShare = categoryRevenue ? ranked[0][1] / categoryRevenue : 0;
    }
    return { period, series };
}

// Bộ lọc chỉ áp dụng khi nhấn Áp dụng; Đặt lại về toàn kỳ.
function overviewDateFilter(start, end) {
    const min = esc(D.dates.start);
    const max = esc(D.dates.end);
    return `
        <form id="overview-date-form" class="overview-date-filter">
            <label for="overview-start">
                Từ ngày
                <input class="select" type="date" id="overview-start"
                       min="${min}" max="${max}" value="${esc(start)}" required>
            </label>
            <label for="overview-end">
                Đến ngày
                <input class="select" type="date" id="overview-end"
                       min="${min}" max="${max}" value="${esc(end)}" required>
            </label>
            <button class="primary" type="submit">Áp dụng</button>
            <button class="soft" type="button" data-action="overviewReset">Đặt lại</button>
        </form>`;
}

// Chọn mức tổng hợp phù hợp với số ngày, hoặc dùng lựa chọn thủ công.
function resolveOverviewGrain(dayCount, preference) {
    if (['day', 'month', 'year'].includes(preference)) return preference;
    if (dayCount <= 93) return 'day';
    if (dayCount <= 730) return 'month';
    return 'year';
}

// Bộ điều khiển riêng của biểu đồ: không thay đổi khoảng ngày KPI.
function overviewChartControls() {
    const choices = [
        ['auto', 'Tự động'],
        ['day', 'Ngày'],
        ['month', 'Tháng'],
        ['year', 'Năm']
    ];
    return `<div class="overview-chart-controls">
        <div class="tabs" role="group" aria-label="Mức tổng hợp biểu đồ">
            ${choices.map(([value, text]) => {
                const active = state.overviewGrain === value;
                return `<button type="button" data-action="overviewGrain"
                    data-value="${value}" class="${active ? 'active' : ''}"
                    aria-pressed="${active}">${text}</button>`;
            }).join('')}
        </div>
        ${legend(['Doanh thu', 'Giá vốn (COGS)'])}
    </div>`;
}

// Tổng hợp sau khi đã lọc ngày: không cộng các tháng/năm ngoài kỳ.
function overviewRevenueChart(series, period) {
    const grain = resolveOverviewGrain(series.length, state.overviewGrain);
    const grouped = group(series, grain);
    const labels = { day: 'ngày', month: 'tháng', year: 'năm' };
    const detail = `Theo ${labels[grain]} • ${fmt(grouped.length)} mốc dữ liệu`;
    const autoNote = state.overviewGrain === 'auto' ? ' (tự động)' : '';

    return card(
        'Doanh thu & COGS',
        `Tổng hợp từ sales.csv • ${detail}${autoNote}`,
        lineChart(grouped, ['Revenue', 'COGS'], 300, colors, true, { overview: true })
            + `<div class="chart-footer">
                    <span>Revenue: ${money(period.revenue)}</span>
                    <span>COGS: ${money(period.cogs)}</span>
                    <span>Tỷ lệ giá vốn: ${period.revenue ? pct(period.cogs / period.revenue) : '—'}</span>
                </div>`,
        overviewChartControls()
    );
}

function overview() {
    // 1. Lấy kỳ đang chọn; mặc định toàn bộ lịch sử.
    const start = state.overviewStart || D.dates.start;
    const end = state.overviewEnd || D.dates.end;
    const { period, series } = overviewPeriod(start, end);
    exportRows = series;
    const cluster = D.cluster;
    const forecastData = D.forecast;
    const score = scoreFor(forecastData.best);
    const next = forecastData.future[forecastData.best] || [];
    const futureSeries = seriesForecast(forecastData.best, 'future', 90, 'Revenue');

    // 2. Hiển thị khoảng ngày đã áp dụng.
    const heading = head(
        'Tổng quan',
        `${date(start)} – ${date(end)} • Dữ liệu DATATHON 2026`,
        overviewDateFilter(start, end)
    );

    // 3. KPI luôn cùng phạm vi ngày, kể cả khi chọn toàn kỳ.
    const kpis = [
        metric('KHÁCH HÀNG', fmt(period.customers), 'Có đơn trong kỳ', 'groups'),
        metric('ĐƠN HÀNG', fmt(period.orders), 'Mọi trạng thái đơn', 'shopping_bag'),
        metric('DOANH THU', money(period.revenue), 'Revenue trước giảm giá', 'payments'),
        metric('SẢN PHẨM', fmt(period.products), 'SKU phát sinh đơn trong kỳ', 'inventory')
    ].join('');

    // 4. Biểu đồ dùng cùng khoảng ngày với KPI, có độ chi tiết tùy chọn.
    const revenueChart = overviewRevenueChart(series, period);

    // 5. Hai thẻ mô hình dùng mốc dữ liệu cố định, không lọc theo kỳ kinh doanh.
    const clusterChart = card(
        'Phân khúc khách hàng (PCA)',
        'K-Means • TN1, k=3 • mốc 31/12/2022 (cố định)',
        donut(cluster.segments.map(s => ({ name: s.name, n: s.n })), fmt(cluster.n))
            + `<div class="chart-footer">
                <span>Silhouette ${fmt(cluster.silhouette, 4)}</span>
                <button class="link" data-go="clusters">Xem phân cụm →</button>
            </div>`,
        '<span class="badge">3 cụm</span>'
    );
    const forecastChart = card(
        'Dự báo doanh thu (+90 ngày)',
        'Hybrid Ensemble • dự báo ngoài mẫu 2023',
        lineChart(futureSeries, ['Thực tế', 'Dự báo'], 225, ['#64748b', '#465fd4'])
            + `<div class="chart-footer">
                <span>MAE test: ${money(score?.mae)}</span>
                <span>R² test: ${fmt(score?.r2, 4)}</span>
                <button class="link" data-go="forecast">Chi tiết →</button>
            </div>`,
        legend(['Thực tế', 'Dự báo'], ['#64748b', '#465fd4'])
    );

    // 6. Thẻ nhận định bổ sung.
    const highlights = [
        mini('category', 'Top danh mục đóng góp', period.topCategory,
            `${pct(period.topShare)} Revenue dòng hàng trong kỳ`),
        mini('repeat', 'Khách mua lại', fmt(period.repeat) + ' khách',
            'Có từ 2 đơn delivered trong kỳ'),
        mini('trending_up', 'Dự báo 90 ngày',
            next.length ? money(next.slice(0, 90).reduce((sum, row) => sum + row.Revenue, 0)) : 'Chưa có',
            '01/01/2023 – 31/03/2023; chưa có nhãn')
    ].join('');

    // 7. Ghép các phần thành giao diện trang Tổng quan.
    return `
        ${heading}
        <div class="grid four">${kpis}</div>
        ${revenueChart}
        <div class="grid two">${clusterChart}${forecastChart}</div>
        <div class="grid three">${highlights}</div>
    `;
}