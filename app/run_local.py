import argparse
import errno
import webbrowser
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


# 1. Cấu hình mặc định
HOST = "127.0.0.1"
DEFAULT_PORT = 8098  # Cổng riêng để tránh mở nhầm phiên bản cũ.
MAX_PORT_ATTEMPTS = 50
WEB_DIR = Path(__file__).resolve().parent / "web"


class AnalytixRequestHandler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store, max-age=0")
        super().end_headers()


def create_server(start_port):
    handler = partial(AnalytixRequestHandler, directory=str(WEB_DIR))

    # Chỉ thử cổng tiếp theo khi cổng hiện tại đã bị chiếm.
    for port in range(start_port, min(start_port + MAX_PORT_ATTEMPTS, 65536)):
        try:
            server = ThreadingHTTPServer((HOST, port), handler)
            return server
        except OSError as error:
            if error.errno != errno.EADDRINUSE and getattr(error, "winerror", None) != 10048:
                raise
            print(f"Cổng {port} đang được sử dụng. Thử cổng tiếp theo...", flush=True)

    raise RuntimeError("Không tìm được cổng trống. Hãy chọn cổng khác bằng --port.")


def main():
    # 2. Đọc tham số dòng lệnh
    parser = argparse.ArgumentParser(description="Chạy Analytix trên máy tính.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Cổng bắt đầu tìm.")
    parser.add_argument("--no-browser", action="store_true", help="Không tự mở trình duyệt.")
    args = parser.parse_args()

    if not 1 <= args.port <= 65535:
        parser.error("--port phải nằm trong khoảng 1 đến 65535.")

    # 3. Kiểm tra file cần thiết trước khi chạy
    required_files = [
        "index.html",
        "style.css",
        "dashboard.json",
        "common.js",
        "charts.js",
        "forecast.js",
        "overview.js",
        "customers.js",
        "clusters.js",
        "models.js",
        "interactions.js",
        "app.js",
    ]
    for filename in required_files:
        if not (WEB_DIR / filename).is_file():
            parser.exit(1, f"Thiếu file: {WEB_DIR / filename}\n")

    # 4. Khởi động server và thông báo đúng đường dẫn thực tế
    try:
        server = create_server(args.port)
    except (OSError, RuntimeError) as error:
        parser.exit(1, f"Không thể khởi động Analytix: {error}\n")

    url = f"http://{HOST}:{server.server_port}"
    print(f"Analytix đang chạy tại: {url}", flush=True)

    # 5. Phục vụ giao diện cho đến khi người dùng dừng chương trình
    with server:
        try:
            if not args.no_browser:
                try:
                    webbrowser.open(url)
                except webbrowser.Error:
                    print("Hãy mở đường dẫn trên bằng trình duyệt.", flush=True)
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nĐã dừng Analytix.", flush=True)

if __name__ == "__main__":
    main()