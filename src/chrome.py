"""구글 크롬 전용 도우미.

이 프로그램은 브라우저를 **크롬으로만** 연다.
  - 대시보드를 띄울 때 (src/main.py)
  - 댓글을 게시할 때 (src/poster.py, Playwright 가 이 크롬을 제어)
크롬을 찾지 못하면 다른 브라우저로 대신 열지 않고, 설치가 필요하다고 알린다.
"""
import os
import platform
import shutil
import subprocess
from pathlib import Path

INSTALL_HINT = "Google Chrome 이 설치되어 있지 않습니다. https://www.google.com/chrome 에서 설치한 뒤 다시 실행하세요."


def find_chrome():
    """설치된 크롬 실행 파일 경로를 돌려준다. 없으면 None."""
    system = platform.system()
    if system == "Darwin":  # macOS
        candidates = [Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
                      Path.home() / "Applications/Google Chrome.app/Contents/MacOS/Google Chrome"]
    elif system == "Windows":
        roots = [os.environ.get(k) for k in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA")]
        candidates = [Path(r) / "Google/Chrome/Application/chrome.exe" for r in roots if r]
    else:  # Linux
        found = [shutil.which(n) for n in ("google-chrome", "google-chrome-stable")]
        candidates = [Path(p) for p in found if p]
    return next((str(c) for c in candidates if c.is_file()), None)


def open_url(url: str) -> bool:
    """URL 을 크롬으로 연다(기본 브라우저가 아니라 크롬). 크롬이 없으면 False."""
    chrome = find_chrome()
    if not chrome:
        return False
    subprocess.Popen([chrome, url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return True
