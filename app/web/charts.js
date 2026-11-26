'use strict';

// TỔNG HỢP DỮ LIỆU VÀ BIỂU ĐỒ SVG
function group(rows, grain) {
    const m = new Map();
    for (const r of rows) {
        const d = r.Date.slice(0, 10);
        const y = d.slice(0, 4);
        const month = +d.slice(5, 7);
        const key = grain === 'day'
            ? d
            : grain === 'year'
                ? y
                : grain === 'quarter'
                    ? `${y}-Q${Math.ceil(month / 3)}`
                    : d.slice(0, 7);

        if (!m.has(key)) {
            m.set(key, { Date: key, Revenue: 0, COGS: 0 });
        }
        const a = m.get(key);
        a.Revenue += r.Revenue;
        a.COGS += r.COGS;
    }
    return [...m.values()].sort((a, b) => a.Date.localeCompare(b.Date));
}

// Định dạng nhãn trục thời gian cho Tổng quan, tránh thiếu năm.
function overviewAxisDate(value) {
    if (value.length === 10) return date(value);
    if (value.length === 7) return `${value.slice(5)}/${value.slice(0, 4)}`;
    return value;
}

// Định dạng nhãn chung cho các biểu đồ đường.
function chartDateLabel(value) {
    if (String(value).startsWith('Fold ')) return String(value);
    if (String(value).length === 10) return date(value);
    if (String(value).length === 7) return `${value.slice(5)}/${value.slice(0, 4)}`;
    return String(value);
}

function hoverReadout(labelText, pairs) {
    return `${labelText}  •  ${pairs.join('  •  ')}`;
}

function lineChart(rows, keys = ['Revenue', 'COGS'], height = 280,
                   cs = colors, area = true, options = {}) {
    if (!rows.length) {
        return '<div class="empty">Không có dữ liệu phù hợp.</div>';
    }

    const w = 900;
    const h = height;
    const p = { l: 75, r: 18, t: 16, b: 37 };

    if (options.overview) {
        p.l = 90;
        p.r = 26;
    }

    const values = rows.flatMap(r => keys.map(k => r[k])).filter(Number.isFinite);
    if (!values.length) {
        return '<div class="empty">Chưa có dữ liệu.</div>';
    }

    const low = Math.min(0, ...values);
    const max = Math.max(...values, 1);
    const range = max - low || 1;
    const x = i => options.overview && rows.length === 1
        ? (p.l + w - p.r) / 2
        : p.l + i * (w - p.l - p.r) / Math.max(1, rows.length - 1);
    const y = v => p.t + (max - v) * (h - p.t - p.b) / range;

    let svg = '';

    for (let j = 0; j <= 4; j++) {
        const val = max - range * j / 4;
        const yy = y(val);
        svg += `<line class="axis" x1="${p.l}" x2="${w - p.r}" y1="${yy}" y2="${yy}"/>`;
        svg += `<text x="${p.l - 8}" y="${yy + 4}" text-anchor="end">${esc(money(val))}</text>`;
    }

    const step = Math.max(1, Math.ceil(rows.length / 8));
    const indices = [];
    if (options.overview) {
        const count = Math.min(rows.length, 7);
        for (let i = 0; i < count; i++) {
            indices.push(count === 1 ? 0 : Math.round(i * (rows.length - 1) / (count - 1)));
        }
    } else {
        for (let i = 0; i < rows.length; i += step) indices.push(i);
    }

    for (const i of indices) {
        const anchor = options.overview && rows.length > 1
            ? (i === 0 ? 'start' : i === rows.length - 1 ? 'end' : 'middle')
            : 'middle';
        const label = options.overview
            ? overviewAxisDate(rows[i].Date)
            : (rows[i].Date.length === 10 ? rows[i].Date.slice(5) : rows[i].Date);
        svg += `<text x="${x(i)}" y="${h - 12}" text-anchor="${anchor}">${esc(label)}</text>`;
    }

    keys.forEach((k, j) => {
        const groups = [];
        let g = [];

        rows.forEach((r, i) => {
            if (Number.isFinite(r[k])) {
                g.push([x(i), y(r[k])]);
            } else if (g.length) {
                groups.push(g);
                g = [];
            }
        });

        if (g.length) groups.push(g);

        for (const segment of groups) {
            const pts = segment.map(a => a.join(',')).join(' ');
            if (area && j === 0) {
                svg += `<polygon points="${segment[0][0]},${y(0)} ${pts} ${segment.at(-1)[0]},${y(0)}" fill="${cs[j]}" opacity=".075"/>`;
            }
            svg += `<polyline points="${pts}" fill="none" stroke="${cs[j]}" stroke-width="2.3" stroke-linejoin="round" ${j === 1 && keys[1] === 'Dự báo' ? 'stroke-dasharray="6 3"' : ''}/>`;

            if (rows.length <= 24) {
                for (const [cx, cy] of segment) {
                    svg += `<circle cx="${cx}" cy="${cy}" r="3" fill="${cs[j]}"/>`;
                }
            }
        }
    });

    if (options.overview) {
        const hit = rows.map((row, i) => {
            const left = i === 0 ? p.l : (x(i - 1) + x(i)) / 2;
            const right = i === rows.length - 1 ? w - p.r : (x(i) + x(i + 1)) / 2;
            const label = overviewAxisDate(row.Date);
            const revenue = fmt(row.Revenue, 2);
            const cogs = fmt(row.COGS, 2);
            return `<rect class="point overview-point" x="${left}" y="${p.t}"
                width="${right - left}" height="${h - p.t - p.b}" fill="transparent"
                data-date="${esc(label)}" data-revenue="${esc(revenue)}" data-cogs="${esc(cogs)}"
                data-x="${x(i)}"></rect>`;
        }).join('');

        svg += `<line class="overview-crosshair" x1="0" x2="0" y1="${p.t}" y2="${h - p.b}" visibility="hidden"/>`;

        return `<div class="chart overview-revenue-plot">
            <svg viewBox="0 0 ${w} ${h}" role="img" aria-label="Biểu đồ Doanh thu và COGS">${svg}${hit}</svg>
            <div class="overview-hover-value" hidden></div>
        </div>`;
    }

    const hit = rows.map((row, i) => {
        const left = i === 0 ? p.l : (x(i - 1) + x(i)) / 2;
        const right = i === rows.length - 1 ? w - p.r : (x(i) + x(i + 1)) / 2;
        const label = chartDateLabel(row.Date);
        const pairs = keys
            .filter(key => Number.isFinite(row[key]))
            .map(key => `${key}: ${fmt(row[key], 2)}`);
        return `<rect class="point hover-point chart-point" x="${left}" y="${p.t}"
            width="${right - left}" height="${h - p.t - p.b}" fill="transparent"
            data-readout="${esc(hoverReadout(label, pairs))}" data-x="${x(i)}"></rect>`;
    }).join('');

    svg += `<line class="chart-crosshair" x1="0" x2="0" y1="${p.t}" y2="${h - p.b}" visibility="hidden"/>`;

    return `<div class="chart hover-host interactive-plot">
        <svg viewBox="0 0 ${w} ${h}" role="img" aria-label="Biểu đồ chuỗi thời gian">${svg}${hit}</svg>
        <div class="chart-hover-value" hidden></div>
    </div>`;
}

function donut(items, totalText) {
    const sum = items.reduce((s, x) => s + x.n, 0);
    const size = 220;
    const cx = 110;
    const cy = 110;
    const r = 70;
    const stroke = 32;
    const circumference = 2 * Math.PI * r;

    let acc = 0;
    const rings = items.map((x, i) => {
        const part = sum ? x.n / sum : 0;
        const dash = `${part * circumference} ${circumference}`;
        const dashOffset = -acc * circumference;
        acc += part;
        const readout = hoverReadout(x.name, [
            `Số lượng: ${fmt(x.n)}`,
            `Tỷ trọng: ${pct(sum ? x.n / sum : 0)}`
        ]);
        return `<circle class="donut-segment hover-point donut-point" cx="${cx}" cy="${cy}" r="${r}"
            fill="none" stroke="${colors[i % colors.length]}" stroke-width="${stroke}"
            stroke-linecap="butt" stroke-dasharray="${dash}" stroke-dashoffset="${dashOffset}"
            transform="rotate(-90 ${cx} ${cy})" data-readout="${esc(readout)}"></circle>`;
    }).join('');

    const rows = items.map((x, i) => {
        const readout = hoverReadout(x.name, [
            `Số lượng: ${fmt(x.n)}`,
            `Tỷ trọng: ${pct(sum ? x.n / sum : 0)}`
        ]);
        return `<div class="donut-item hover-point donut-point" data-readout="${esc(readout)}">
            <div class="list-row"><span><i class="dot" style="background:${colors[i % colors.length]}"></i>${esc(x.name)}</span><b>${pct(sum ? x.n / sum : 0)}</b></div>
            <div class="bar-track"><div class="bar-fill" style="background:${colors[i % colors.length]};width:${sum ? 100 * x.n / sum : 0}%"></div></div>
        </div>`;
    }).join('');

    return `<div class="donut-block hover-host">
        <div class="donut-row">
            <div class="chart donut-chart">
                <svg viewBox="0 0 ${size} ${size}" role="img" aria-label="Biểu đồ tròn tỷ trọng phân khúc khách hàng">
                    <circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="#e9edf6" stroke-width="${stroke}"></circle>
                    ${rings}
                    <circle cx="${cx}" cy="${cy}" r="48" fill="white"></circle>
                    <text x="${cx}" y="108" text-anchor="middle" class="donut-value">${esc(totalText)}</text>
                    <text x="${cx}" y="128" text-anchor="middle" class="donut-caption">Tổng số</text>
                </svg>
            </div>
            <div>${rows}</div>
        </div>
        <div class="chart-hover-value" hidden></div>
    </div>`;
}

// readout = false: thanh đã có đầy đủ nhãn và giá trị, không cần dòng lặp.
function bars(items, { readout = true } = {}) {
    const max = Math.max(1, ...items.map(item => item.n));
    const rows = items.map((item, index) => {
        const name = item.name || item.label;
        const value = item.text ?? fmt(item.n);
        const color = item.color || colors[index % colors.length];
        const width = Math.max(0, 100 * item.n / max);
        const hoverData = readout
            ? `class="bar-item hover-point bar-hover-point" data-readout="${esc(hoverReadout(name, [value]))}"`
            : 'class="bar-item bar-highlight"';

        return `<div ${hoverData}>
            <div class="list-row"><span>${esc(name)}</span><b>${esc(value)}</b></div>
            <div class="bar-track">
                <div class="bar-fill" style="width:${width}%;background:${color}"></div>
            </div>
        </div>`;
    }).join('');

    const detail = readout ? '<div class="chart-hover-value" hidden></div>' : '';
    return `<div class="bar-hover-group${readout ? ' hover-host' : ''}">${rows}${detail}</div>`;
}

function pcaChart(c = D.cluster) {
    const pts = c.pca;
    const w = 900;
    const h = 360;
    const px = 60;
    const py = 24;
    const xs = pts.map(p => p[0]);
    const ys = pts.map(p => p[1]);
    const xmin = Math.min(...xs);
    const xmax = Math.max(...xs);
    const ymin = Math.min(...ys);
    const ymax = Math.max(...ys);
    const x = v => px + (v - xmin) / (xmax - xmin) * (w - px - 25);
    const y = v => py + (ymax - v) / (ymax - ymin) * (h - py - 45);

    let svg = '';
    for (let i = 0; i <= 5; i++) {
        const xx = px + i * (w - px - 25) / 5;
        const yy = py + i * (h - py - 45) / 5;
        svg += `<line class="axis" x1="${xx}" x2="${xx}" y1="${py}" y2="${h - 45}"/>`;
        svg += `<line class="axis" x1="${px}" x2="${w - 25}" y1="${yy}" y2="${yy}"/>`;
        svg += `<text x="${xx}" y="${h - 25}" text-anchor="middle">${fmt(xmin + i * (xmax - xmin) / 5, 1)}</text>`;
        svg += `<text x="${px - 8}" y="${yy + 4}" text-anchor="end">${fmt(ymax - i * (ymax - ymin) / 5, 1)}</text>`;
    }

    svg += pts.map(p => {
        const readout = hoverReadout(`Khách mẫu • Cụm ${p[2] + 1}`, [
            `PC1: ${fmt(p[0], 2)}`,
            `PC2: ${fmt(p[1], 2)}`
        ]);
        return `<circle class="hover-point pca-point" cx="${x(p[0]).toFixed(1)}" cy="${y(p[1]).toFixed(1)}" r="2.4"
            fill="${colors[p[2] % colors.length]}" opacity=".42" data-readout="${esc(readout)}"></circle>`;
    }).join('');

    c.segments.forEach(s => {
        const readout = hoverReadout(s.name, [
            `Số khách: ${fmt(s.n)}`,
            `Tỷ trọng: ${pct(s.n / c.n)}`,
            `Net: ${money(s.net)}`
        ]);
        svg += `<circle class="hover-point pca-point" cx="${x(s.center[0])}" cy="${y(s.center[1])}" r="7"
            fill="${colors[s.cluster % colors.length]}" stroke="white" stroke-width="2"
            data-readout="${esc(readout)}"></circle>`;
    });

    return `<div class="chart hover-host">
        <svg viewBox="0 0 ${w} ${h}" role="img" aria-label="PCA phân cụm khách hàng">
            ${svg}
            <text x="${w / 2}" y="${h - 5}" text-anchor="middle">PC1 (${pct(c.variance[0])} phương sai)</text>
            <text x="15" y="${h / 2}" transform="rotate(-90 15 ${h / 2})" text-anchor="middle">PC2 (${pct(c.variance[1])})</text>
        </svg>
        <div class="chart-hover-value" hidden></div>
    </div>`;
}

function histChart(values, c = D.cluster) {
    const histogram = bars(values.map(x => ({
        ...x,
        text: `${fmt(x.n)} (${pct(x.n / c.n)})`
    })), { readout: false });
    return histogram + `<div class="chart-footer"><span>Trung vị: ${fmt(c.median[state.hist], 1)}</span><span>Toàn bộ ${fmt(c.n)} khách</span></div>`;
}