"""크롬 프로필에 구글 계정을 '직접' 로그인해 두는 도우미.

왜 필요한가
  댓글 게시기는 자동 제어 크롬으로 프로필을 열기 때문에, 구글이 그 창에서의 로그인은 막는 경우가 있다
  ("지원되지 않는 명령줄 플래그", "안전하지 않은 브라우저" 등). 그래서 로그인은 평범한 크롬 창으로
  사람이 직접 하고, 로그인 상태는 프로필 폴더에 남겨 두면 게시기가 그 프로필을 그대로 이어 쓴다.

사용:
    python scripts/login_profile.py              # config.yaml 의 첫 번째 프로필
    python scripts/login_profile.py 유튜브2      # 이름으로 지정

순서
  1) 위 명령을 실행하면 크롬 창이 열리고 구글 로그인 페이지가 뜬다.
  2) 사용할 계정으로 로그인한다. 로그인이 끝나면 유튜브 화면으로 이동한다.
  3) 유튜브 화면 오른쪽 위에 내 프로필 사진(아바타)이 보이는지 확인한다.  ← 이게 보여야 로그인된 것이다.
  4) 크롬 창을 모두 닫는다.  ← 닫아야 게시기가 같은 프로필을 열 수 있다.

이 스크립트는 크롬을 실행만 한다. 쿠키·비밀번호 등 프로필 안의 파일은 읽지 않는다.
"""
import subprocess
import sys
from pathlib import Path

# scripts/ 안에서 실행해도 프로젝트의 src 패키지를 불러올 수 있게 프로젝트 루트를 경로에 추가한다
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import chrome  # noqa: E402
from src.config import settings  # noqa: E402


def main() -> int:
    chrome_path = chrome.find_chrome()
    if not chrome_path:
        print(chrome.INSTALL_HINT)
        return 1

    # 로그인할 프로필 찾기: 인자가 없으면 첫 번째
    name = sys.argv[1] if len(sys.argv) > 1 else (settings.profiles[0]["name"] if settings.profiles else "")
    prof = next((p for p in settings.profiles if p["name"] == name), None)
    if not prof:
        print(f"프로필 '{name}' 을(를) config/config.yaml 에서 찾지 못했습니다.")
        print("사용 가능한 프로필:", ", ".join(p["name"] for p in settings.profiles) or "(없음)")
        return 1

    path = Path(prof["user_data_dir"]).expanduser()
    path.mkdir(parents=True, exist_ok=True)
    print(f"[{prof['name']}] {path}")
    print("크롬이 열립니다. 구글 계정에 로그인하면 유튜브로 이동합니다.")
    print("오른쪽 위에 내 프로필 사진이 보이는지 확인한 뒤, 크롬 창을 모두 닫으세요.")

    # 자동 제어 없이 '평범한' 크롬을 해당 프로필 폴더로 연다. 로그인 후 유튜브로 넘어가도록 continue 를 준다.
    login_url = "https://accounts.google.com/ServiceLogin?service=youtube&hl=ko&continue=https%3A%2F%2Fwww.youtube.com%2F"
    subprocess.Popen([chrome_path, f"--user-data-dir={path}", "--no-first-run",
                      "--no-default-browser-check", login_url])
    return 0


if __name__ == "__main__":
    sys.exit(main())
