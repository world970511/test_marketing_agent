"""프로그램 시작점.  실행:  python -m src.main

하는 일
  1) 웹 서버(src/app.py)를 이 컴퓨터(127.0.0.1)에서만 접근 가능하게 띄운다.
  2) 서버가 뜨면 대시보드(http://127.0.0.1:8000)를 **크롬으로** 연다.
     크롬이 없으면 다른 브라우저로 열지 않고 주소만 알려 준다.
"""
import threading
import time

import uvicorn

from . import chrome

HOST, PORT = "127.0.0.1", 8000   # 외부에서 접근할 수 없도록 로컬 주소에만 연다


def _open_dashboard():
    """서버가 뜰 시간을 잠깐 준 뒤 대시보드를 크롬으로 연다."""
    time.sleep(1.2)
    url = f"http://{HOST}:{PORT}"
    if not chrome.open_url(url):
        print(chrome.INSTALL_HINT)
        print(f"설치 후 크롬 주소창에 {url} 을 입력하세요.")


if __name__ == "__main__":
    threading.Thread(target=_open_dashboard, daemon=True).start()   # 서버 실행과 동시에 대기
    uvicorn.run("src.app:app", host=HOST, port=PORT, log_level="warning")
