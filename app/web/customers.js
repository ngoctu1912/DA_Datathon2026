'use strict';

// TRANG PHÂN TÍCH KHÁCH HÀNG
function business() {
    // 1. Lấy dữ liệu kinh doanh và tạo bộ lọc.
    let p = D.periods[state.customers],
        b = p.filters[[state.cat, state.region, state.status].join('|')],
        ctrl = tabs('customers', periods, state.customers) + option('cat', [['all', 'Danh mục: Tất cả'], ...D.categories], state.cat)
        + option('region', [['all', 'Khu vực: Tất cả'], ...D.regions], state.region)
        + option('status', [['all', 'Trạng thái: Tất cả'], ...D.statuses.map(s => [s, label(s)])], state.status)
        + `<button class="outline" data-action="export">${icon('file_download')} Xuất CSV</button>`;
    let h = head(
        'Phân tích khách hàng',
        `${date(p.start)} – ${date(p.end)} • Bài 1: phân tích kinh doanh và hành vi mua hàng`,
        ctrl
    );
    if (!b) {
        exportRows = [];
        return h + notice('Không có giao dịch cho bộ lọc này. Hãy chọn phạm vi khác.');
    }
    // 2. Tổng hợp theo ngày, tháng, quý hoặc năm.
    let g = state.customers === 'all' && state.grain === 'day' ? 'month' : state.grain;
    let chart = group(b.series, g);
    exportRows = chart;
    let n = b.orders;
    // 3. Chuẩn bị trạng thái đơn hàng, hoàn trả và top sản phẩm.
    let statusItems = Object.entries(b.status).map(([name, n]) => ({ name: label(name), n }));
    let reason = Object.entries(b.reasons).map(([name, n]) => ({ name: label(name), n }));
    const ranking = rankingCard(p, b);
    // 4. Ghép KPI, biểu đồ và các nhận định kinh doanh.
    return h
        + `<div class="grid four">${
        metric('DOANH THU', money(b.revenue), 'Revenue trước giảm giá', 'payments')
    }${
        metric('GIÁ VỐN (COGS)', money(b.cogs), 'Tỷ lệ giá vốn: ' + pct(b.cogs / b.revenue), 'inventory')
    }${
        metric('ĐƠN HÀNG', fmt(n), 'Revenue dòng hàng/đơn: ' + money(b.revenue / n), 'shopping_bag')
    }${
        metric('TỶ LỆ HOÀN TRẢ', pct(b.returns / n), fmt(b.returns) + ' đơn có ghi nhận returns', 'repeat')
    }</div>`
        + card(
        'Doanh thu & Giá vốn theo thời gian',
        `Dữ liệu dòng hàng • ${fmt(b.customers)} khách có giao dịch`,
        lineChart(chart, ['Revenue', 'COGS'], 290)
        + `<div class="chart-footer"><span>Net sau giảm giá: ${
        money(b.net)
    }</span><span>Giảm giá: ${
        money(b.discount)
    }</span></div>`,
        tabs(
        'grain',
        [...(state.customers === 'all' ? [] : [['day', 'Ngày']]), ['month', 'Tháng'], ['quarter', 'Quý'], ['year', 'Năm']],
        g
    )
    )
        + `<div class="grid two">${
        ranking
    }${
        card(
        'Trạng thái đơn hàng & hoàn trả',
        'Đơn hàng phân theo trạng thái; lý do từ returns.csv',
        donut(statusItems, fmt(n))
        + `<div class="section-label">Lý do hoàn trả chính</div>${
        reason.length ? bars(reason.slice(0, 3), { readout: false }) : '<p class="subtitle">Không có bản ghi hoàn trả.</p>'
    }<div class="chart-footer"><button class="link" data-action="returns">Xem chi tiết →</button></div>`
    )
    }</div><div class="grid three">${
        mini(
        'local_offer',
        'Khuyến mãi có Revenue cao nhất',
        b.promo,
        `${money(b.promoRevenue)} Revenue gắn mã promo_id; không phải hiệu quả nhân quả`
    )
    }${
        mini('category', 'Danh mục đóng góp cao nhất', b.topCategory, pct(b.topShare) + ' Revenue trong bộ lọc')
    }${
        mini(
        'inventory',
        'Cảnh báo tồn kho',
        fmt(p.stockout) + ' SKU stockout',
        `Ảnh chụp toàn hệ thống ${date(p.inventoryDate)}; không áp dụng bộ lọc đơn`
    )
    }</div>`;
}

// Dữ liệu chi tiết theo bộ lọc hiện tại.
function businessData() {
    return D.periods[state.customers].filters[[state.cat, state.region, state.status].join('|')];
}

// XẾP HẠNG SẢN PHẨM VÀ DANH MỤC
// Hai tab dùng chung bộ lọc của trang; chỉ hiển thị bảng đang chọn.
function rankingCard(period, business) {
    const categories = categoryRanking(period, business);
    const showProducts = state.rankingTab !== 'categories';
    const choices = [
        ['products', `Top ${Math.min(5, business.top.length)} sản phẩm`],
        ['categories', `Top ${categories.length} danh mục`]
    ];
    const controls = `<div class="tabs ranking-tabs" role="group" aria-label="Xếp hạng bán chạy">
        ${choices.map(([value, title]) => {
            const active = state.rankingTab === value;
            return `<button type="button" data-tab="rankingTab" data-value="${value}"
                class="${active ? 'active' : ''}" aria-pressed="${active}">${esc(title)}</button>`;
        }).join('')}
    </div>`;

    // Tab sản phẩm giữ nút xem chi tiết; tab danh mục không lặp thêm số liệu.
    const content = showProducts
        ? productRanking(business)
            + `<div class="chart-footer"><span></span><button class="link"
                data-action="products">Xem chi tiết sản phẩm →</button></div>`
        : bars(categories, { readout: false });

    return card(
        'Top sản phẩm & danh mục bán chạy',
        'Xếp hạng theo Revenue trước giảm giá',
        controls + `<div class="ranking-content">${content}</div>`
    );
}

// Tối đa 5 sản phẩm, theo Revenue trước giảm giá.
function productRanking(business) {
    const products = business.top.slice(0, 5);
    const maximum = Math.max(1, ...products.map(product => product.Revenue));

    return products.map((product, index) => {
        const share = business.revenue ? product.Revenue / business.revenue : 0;
        const width = 100 * product.Revenue / maximum;
        const rank = String(index + 1).padStart(2, '0');

        return `
            <div class="product">
                <span class="rank">${rank}</span>
                <div>
                    <b>${esc(product.product_name)}</b>
                    <small>${esc(product.category)} • ${pct(share)}</small>
                    <div class="bar-track">
                        <div class="bar-fill" style="width:${width}%"></div>
                    </div>
                </div>
                <b>${money(product.Revenue)}</b>
            </div>`;
    }).join('');
}

// Lấy doanh thu đầy đủ của từng danh mục từ dữ liệu đã tổng hợp.
// Giữ nguyên kỳ, khu vực và trạng thái đơn hàng đang chọn.
// Không cộng Top sản phẩm vì danh sách đó chỉ chứa một phần doanh thu.
function categoryRanking(period, business) {
    const categories = state.cat === 'all' ? D.categories : [state.cat];
    const ranking = [];

    for (const category of categories) {
        const key = [category, state.region, state.status].join('|');
        const categoryData = period.filters[key];
        if (!categoryData) continue;

        const revenue = categoryData.revenue;
        const share = business.revenue ? revenue / business.revenue : 0;
        ranking.push({
            name: category,
            n: revenue,
            text: `${money(revenue)} (${pct(share)})`
        });
    }

    return ranking.sort((a, b) => b.n - a.n).slice(0, 5);
}