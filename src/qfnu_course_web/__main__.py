from __future__ import annotations

import argparse
import socket
import threading
import webbrowser

import uvicorn


def available_port(start: int = 8765) -> int:
    for port in range(start, start + 50):
        with socket.socket() as sock:
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise RuntimeError("无法找到可用的本地端口")


def main() -> None:
    parser = argparse.ArgumentParser(description="启动 QFNU 选课本地 Web 控制台")
    parser.add_argument("--port", type=int, help="本地端口；默认从 8765 开始选择")
    parser.add_argument("--no-browser", action="store_true", help="启动时不自动打开浏览器")
    args = parser.parse_args()
    port = args.port or available_port()
    url = f"http://127.0.0.1:{port}"
    print(f"QFNU 选课控制台：{url}")
    if not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    uvicorn.run(
        "qfnu_course_web.app:app",
        host="127.0.0.1",
        port=port,
        log_level="info",
        timeout_graceful_shutdown=2,
    )


if __name__ == "__main__":
    main()
