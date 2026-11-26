'use strict';

// ĐIỀU HƯỚNG VÀ HIỂN THỊ TRANG
function render() {
    if (!D)
        return;
    route = location.hash.slice(1) || 'overview';
    if (!pages.some(p => p[0] === route))
        route = 'overview';
    document.title = `Analytix | ${pages.find(p => p[0] === route)[1]}`;
    $('#breadcrumb').textContent = pages.find(p => p[0] === route)[1];
    // Dùng một danh sách để khoảng cách giữa các mục luôn bằng nhau.
    $('#workspace').innerHTML = pages.map(([page, title, ic]) => {
        const active = page === route ? 'aria-current="page" class="active"' : '';
        return `<a href="#${page}" ${active}>${icon(ic)}<span>${title}</span></a>`;
    }).join('');
    let fn = {
        overview, customers: business, clusters, forecast, models
    };
    app.innerHTML = fn[route]();
    document.querySelector('.sidebar').classList.remove('open');
}

// ĐỌC DỮ LIỆU DASHBOARD VÀ KHỞI ĐỘNG
let isLoading = false;
// Giữ bộ lọc đã áp dụng nếu dữ liệu mới vẫn chứa khoảng ngày đó.
function reconcileOverviewDates() {
    const { start, end } = D.dates;
    if (state.overviewStart && (state.overviewStart < start || state.overviewStart > end)) {
        state.overviewStart = null;
    }
    if (state.overviewEnd && (state.overviewEnd < start || state.overviewEnd > end)) {
        state.overviewEnd = null;
    }
}

// Đọc lại JSON từ server, không sử dụng bản lưu trong bộ nhớ đệm.
// Chỉ tải khi khởi động hoặc thử lại sau lỗi tải dữ liệu.
async function load() {
    if (isLoading) return;

    const button = $('#refresh');
    const previousData = D;
    const previousState = { ...state };

    isLoading = true;
    button.disabled = true;
    button.setAttribute('aria-busy', 'true');

    try {
        const response = await fetch('dashboard.json', { cache: 'no-store' });
        if (!response.ok) throw new Error('HTTP ' + response.status);
        const newData = await response.json();
        if (!newData.dates || !newData.forecast || !Array.isArray(newData.history)
            || !Array.isArray(newData.overviewDaily)) {
            throw new Error('dashboard.json thiếu dữ liệu cần thiết.');
        }

        D = newData;
        reconcileOverviewDates();
        state.method ??= D.forecast.best;
        render();

    } catch (error) {
        D = previousData;
        Object.assign(state, previousState);
        if (previousData) {
            render();
            dialog('Không thể làm mới dữ liệu',
                `<p>${esc(error.message)}. Dữ liệu trước đó vẫn được giữ lại.</p>`);
        } else {
            app.innerHTML = `<div class="card error"><h2>Không đọc được dữ liệu</h2>
                <p>${esc(error.message)}. Hãy mở ứng dụng bằng HTTP server và kiểm tra dashboard.json.</p></div>`;
        }
    } finally {
        isLoading = false;
        button.disabled = false;
        button.removeAttribute('aria-busy');
    }
}

// Làm mới: đặt lại bộ lọc của trang hiện tại, không ảnh hưởng trang khác.
function resetCurrentPage() {
    if (!D) {
        load();
        return;
    }

    Object.assign(state, pageDefaults[route] || pageDefaults.overview);
    if (route === 'forecast') {
        state.method = D.forecast.best;
    }
    render();
    window.scrollTo(0, 0);
}

$('#refresh').addEventListener('click', resetCurrentPage);
window.addEventListener('hashchange', () => {
    render();
    window.scrollTo(0, 0);
});

// Khởi động lần đầu.
load();