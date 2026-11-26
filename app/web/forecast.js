'use strict';

// TIỆN ÍCH ĐÁNH GIÁ VÀ DỰ BÁO
function scores(split, target) {
    return D.forecast.scores.filter(x => x.split === split && x.target === target && x.method !== 'Phương pháp được chọn').sort((a, b) => a.mae - b.mae);
}

function scoreFor(method, target = 'Revenue') {
    return scores('test', target).find(x => x.method === method);
}

function seriesForecast(method, mode, n, target) {
    const rows = D.forecast[mode]?.[method] || [];
    const selected = rows.slice(0, n);
    const actual = new Map(D.history.map(r => [r.Date, r[target]]));
    if (mode === 'test')
        return selected.map(r => ({
            Date: r.Date, 'Thực tế': actual.get(r.Date), 'Dự báo': r[target]
        }));
    const start = selected[0]?.Date || '2023-01-01';
    let past = D.history.filter(r => r.Date < start).slice(-90).map(r => ({
        Date: r.Date, 'Thực tế': r[target], 'Dự báo': null
    }));
    return [...past, ...selected.map(r => ({
            Date: r.Date, 'Thực tế': null, 'Dự báo': r[target]
        }))];
}

// TRANG DỰ BÁO DOANH THU
function forecast() {
    // 1. Chọn mô hình, mục tiêu và giai đoạn dự báo.
    let f = D.forecast,
        m = state.method || f.best,
        target = state.target,
        mode = state.forecastMode,
        n = +state.horizon,
        score = scoreFor(m, target),
        rows = seriesForecast(m, mode, n, target),
        actualMap = new Map(D.history.map(r => [r.Date, r[target]])),
        test = f.test[m] || [],
        res = test.map(r => actualMap.get(r.Date) - r[target]);
    let hist = [];
    if (res.length) {
        let min = Math.min(...res), max = Math.max(...res), step = (max - min) / 12 || 1;
        for (let i = 0; i < 12; i++)
            hist.push({
                name: `${money(min + i * step)} → ${money(min + (i + 1) * step)}`,
                n: res.filter(x => x >= min + i * step && (i === 11 ? x <= max : x < min + (i + 1) * step)).length
            });
    }
    let opts = Object.keys(mode === 'future' ? f.future : f.test).filter(m => m !== 'Phương pháp được chọn');
    if (!opts.length)
        return head(
            'Dự báo doanh thu',
            'Chưa có đầu ra cho lựa chọn hiện tại',
            option('forecastMode', [['test', 'Tập test'], ['future', 'Dự báo ngoài mẫu']], mode)
        );
    if (!opts.includes(m)) {
        m = opts.includes(f.best) ? f.best : opts[0];
        state.method = m;
        return forecast();
    }
    // 2. Chuẩn bị dữ liệu xuất CSV.
    exportRows = (f[mode][m] || []).slice(0, n).map(r => ({
        ...r, Actual: mode === 'test' ? actualMap.get(r.Date) : null, Target: target, Method: m
    }));
    let sc = scores('test', target);
    return head(
        'Dự báo doanh thu',
        `Hybrid Ensemble • chia dữ liệu thành train / validation / test`,
        option('method', opts.map(x => [x, short(x)]), m)
        + option('forecastMode', [['test', 'Tập test đánh giá mô hình'], ['future', 'Dự báo ngoài mẫu']], mode)
        + option('horizon', [[30, '30 ngày'], [90, '90 ngày'], [180, '180 ngày'], [548, '548 ngày']], n)
        + option('target', [['Revenue', 'Revenue'], ['COGS', 'COGS']], target)
        + (mode === 'future' ? `<button class="outline" data-action="submission">Xuất submission</button>` : ''),
        ''
    )
        + `<div class="grid four">${
        metric('MAE (SAI SỐ TUYỆT ĐỐI TB)', money(score?.mae), 'Trên tập test • ' + target, 'science')
    }${
        metric('RMSE', money(score?.rmse), 'Trên tập test • ' + target, 'science')
    }${
        metric('HỆ SỐ XÁC ĐỊNH R²', fmt(score?.r2, 4), 'Không phải tỷ lệ dự báo đúng', 'verified')
    }${
        metric('MÔ HÌNH MAE THẤP NHẤT', short(sc[0].method), 'Đối chiếu trên tập đánh giá', 'verified')
    }</div>`
        + card(
        'Thực tế vs Dự báo ' + target,
        mode === 'test' ? 'Tập test dùng để đánh giá mô hình • ' + n + ' mốc dữ liệu' : 'Dự báo ngoài mẫu • ' + n + ' mốc dữ liệu',
        lineChart(rows, ['Thực tế', 'Dự báo'], 350, ['#64748b', '#465fd4'])
        + `<div class="grid four" style="margin-top:12px">${
        mini(
        'timer',
        'HUẤN LUYỆN',
        mode === 'test' ? 'Tập train' : 'Toàn bộ lịch sử',
        mode === 'test' ? 'Dùng để huấn luyện mô hình' : 'Dùng khi tạo dự báo ngoài mẫu'
    )
    }${
        mini('science', 'VALIDATION', '3 lượt × 548 ngày', 'Dùng để tinh chỉnh và so sánh mô hình')
    }${
        mini('category', 'THÀNH PHẦN', '8 phân khúc', 'Phân rã Revenue / COGS')
    }${
        mini(
        'verified',
        'ĐÁNH GIÁ',
        mode === 'test' ? 'Có nhãn thực tế' : 'Chưa có nhãn',
        mode === 'test' ? 'Dùng để kiểm tra chất lượng mô hình' : 'Chỉ là kết quả dự báo ngoài mẫu'
    )
    }</div>`,
        legend(['Thực tế', 'Dự báo'], ['#64748b', '#465fd4'])
    )
        + `<div class="grid two">${
        card(
        'So sánh các mô hình dự báo',
        'So sánh trên tập test • ' + target,
        table(['MÔ HÌNH', 'MAE', 'RMSE', 'R²'], sc.map(s => [
        `<b>${esc(short(s.method))}</b>${s.method === m ? ' <span class="badge">Đang xem</span>' : ''}`,
        money(s.mae),
        money(s.rmse),
        fmt(s.r2, 4)
    ]))
        + `<div class="chart-footer"><button class="link" data-go="models">Xem thực nghiệm →</button><button class="link" data-action="params">Siêu tham số →</button></div>`
    )
    }${
        card(
        'Phân tích sai số (Residuals Analysis)',
        'Phần dư = thực tế − dự báo; toàn bộ 548 ngày test',
        bars(hist, { readout: false })
    )
    }</div><div class="grid three">${
        mini('verified', 'R² TEST', fmt(score?.r2, 4), 'Giải thích phương sai trên tập test, không gọi là độ chính xác %')
    }${
        mini(
        'science',
        'MAE VALIDATION',
        money(scores('validation', target).find(x => x.method === m)?.mae),
        'Trung bình 3 lượt validation'
    )
    }${
        mini(
        'trending_up',
        'TỔNG DỰ BÁO TRONG KỲ',
        money((f[mode][m] || []).slice(0, n).reduce((s, r) => s + r[target], 0)),
        mode === 'future' ? 'Kết quả dự báo ngoài mẫu' : 'Tổng giá trị dự báo trên tập test'
    )
    }</div>`
        ;
}