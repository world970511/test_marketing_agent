"""댓글 게시기: 크롬 프로필을 열어 영상 페이지에서 댓글을 직접 타이핑하고 게시한 뒤, 내 댓글이 보이는지 확인한다.

핵심 방식
  - Playwright 의 launch_persistent_context 로 "프로필 폴더(user_data_dir)"를 지정해 연다.
    (크롬은 평소 쓰는 기본 프로필의 자동 제어를 막기 때문에, 폴더를 지정하는 방식이 필요하다.)
  - **크롬(channel="chrome")만** 사용한다. 크롬이 없으면 다른 브라우저로 대신하지 않고 오류를 낸다.
  - 동기(sync) API 를 별도 스레드에서 실행한다(Windows/Mac 모두 이벤트 루프 문제 없음).

하지 않는 일 (안전 규칙)
  - 쿠키·비밀번호·저장 정보를 읽거나 저장하지 않는다. 프로필 폴더는 크롬에 경로만 전달한다.
  - 좋아요·구독·설정 변경 등 댓글 작성 외의 동작을 하지 않는다.
  - 허용된 영상 페이지 밖으로 이동하지 않는다(그런 이동은 막는다).
"""
import random
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import chrome
from . import selectors as sel
from .config import SCREENSHOTS


class PostError(Exception):
    """게시 실패. 메시지는 그대로 화면의 실패 사유로 보여 준다."""


def _watch_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def _is_allowed_navigation(url: str, video_id: str) -> bool:
    """페이지 이동 허용 여부.

    허용: 대상 영상의 watch 페이지, about/blob/data, 그리고 유튜브의 '로그인 확인' 이동.
    로그인 확인 이동이란, 이미 로그인된 프로필이 유튜브 세션을 이어받으려고 거치는 자동 이동이다.
      watch → accounts.google.com/ServiceLogin?...passive=true → youtube.com/signin?action_handle_signin=true → watch
    passive=true 는 로그인 창을 띄우지 않고 상태만 확인한다는 뜻이다. 계정 입력·비밀번호 같은
    실제 로그인 화면(그 외의 accounts.google.com 주소)은 계속 막는다.
    """
    u = urlparse(url)
    if u.scheme in ("about", "blob", "data"):
        return True
    host = (u.hostname or "").removeprefix("www.").removeprefix("m.")
    q = parse_qs(u.query)
    if host == "youtube.com" and u.path == "/watch" and q.get("v") == [video_id]:
        return True
    # 로그인 확인 이동(자동 확인 용도의 주소만)
    if host == "accounts.google.com" and u.path == "/ServiceLogin" and q.get("passive") == ["true"]:
        return True
    if host == "accounts.google.com" and u.path.startswith("/CheckCookie"):
        return True
    if host == "youtube.com" and u.path == "/signin" and q.get("action_handle_signin") == ["true"]:
        return True
    return False


def post_comment(user_data_dir: str, video_id: str, comment: str, emit) -> dict:
    """크롬 프로필로 영상에 댓글을 단다.

    user_data_dir : 열 크롬 프로필 폴더(config.yaml 의 profiles[].user_data_dir)
    video_id      : 댓글을 달 영상 ID
    comment       : 게시할 댓글 본문
    emit          : emit(단계, 상태, 메시지=None) — 진행 상태를 대시보드로 알리는 콜백
    반환          : {"link": 내 댓글(또는 영상) 주소}.  실패하면 PostError.
    """
    from playwright.sync_api import TimeoutError as PWTimeout
    from playwright.sync_api import sync_playwright

    # 크롬이 없으면 시작하기 전에 분명하게 알린다(다른 브라우저로 대신하지 않는다).
    if not chrome.find_chrome():
        emit("프로필 여는 중", "fail")
        raise PostError(chrome.INSTALL_HINT)

    path = str(Path(user_data_dir).expanduser())
    step = "프로필 여는 중"          # 지금 어느 단계인지(실패 사유에 쓴다)
    ctx = page = None
    with sync_playwright() as p:
        try:
            # --- 1) 프로필 열기: 지정한 폴더로 '크롬'을 실행한다 ---
            emit(step, "active")
            # chromium_sandbox=True : Playwright 기본값은 --no-sandbox 를 붙이는데, 크롬이 이를
            #                         "지원되지 않는 명령줄 플래그" 경고로 보여 주므로 샌드박스를 켠다.
            # ignore_default_args   : "자동화된 소프트웨어가 제어 중" 표시용 플래그를 뺀다.
            ctx = p.chromium.launch_persistent_context(
                path, channel="chrome", headless=False, locale="ko-KR", no_viewport=True,
                chromium_sandbox=True, ignore_default_args=["--enable-automation"],
                args=["--no-first-run", "--no-default-browser-check"],
            )
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.set_default_timeout(20000)

            # 허용된 영상 페이지 밖으로 나가는 '최상위 이동'은 차단한다(광고·다른 페이지로의 이탈 방지).
            # 막은 주소는 blocked 에 모아 두었다가, 실패했을 때 사유로 알려 준다.
            blocked = []

            def guard(route, request):
                if (request.resource_type == "document" and request.frame == page.main_frame
                        and request.is_navigation_request()
                        and not _is_allowed_navigation(request.url, video_id)):
                    u = urlparse(request.url)
                    blocked.append(f"{u.hostname}{u.path}")
                    return route.abort()
                return route.continue_()
            page.route("**/*", guard)
            emit(step, "done")

            # --- 2) 영상 페이지 열기 ---
            step = "영상 여는 중"; emit(step, "active")
            page.goto(_watch_url(video_id), wait_until="domcontentloaded")
            page.wait_for_selector("video", timeout=20000)
            # 로그인 확인: 로그아웃 상태에서도 댓글 입력칸은 보이므로, 상단바의 프로필 아바타로 판단한다.
            # 상단바는 먼저 뜨고 아바타는 조금 뒤에 그려지므로, 아바타가 나타날 때까지 기다린 뒤 판단한다.
            page.wait_for_selector(sel.MASTHEAD, timeout=20000)
            try:
                page.wait_for_selector(sel.AVATAR, timeout=10000)
            except PWTimeout:
                pass  # 끝내 안 나타나면 아래에서 '로그인 안 됨'으로 처리
            if not page.locator(sel.AVATAR).count():
                raise PostError("이 프로필은 유튜브에 로그인되어 있지 않습니다. "
                                "python scripts/login_profile.py 로 로그인한 뒤 크롬 창을 닫고 다시 시도하세요.")
            emit(step, "done")

            # --- 3) 댓글창 찾기: 댓글 영역이 로드될 때까지 조금씩 스크롤 ---
            step = "댓글창 찾는 중"; emit(step, "active")
            for _ in range(12):
                page.mouse.wheel(0, 600)
                time.sleep(0.5)
                if page.locator(sel.PLACEHOLDER).count():
                    break
            # 댓글 입력칸 대신 로그인 버튼이 보이면 이 프로필은 로그인되어 있지 않은 것
            if page.locator(sel.SIGN_IN).count() and not page.locator(sel.PLACEHOLDER).count():
                raise PostError("이 프로필은 유튜브에 로그인되어 있지 않습니다.")
            if not page.locator(sel.PLACEHOLDER).count():
                raise PostError("댓글창을 찾지 못했습니다. (댓글이 막힌 영상이거나 화면 구조가 바뀌었을 수 있습니다)")
            page.locator(sel.PLACEHOLDER).scroll_into_view_if_needed()
            page.locator(sel.PLACEHOLDER).click()
            page.wait_for_selector(sel.EDITOR)
            emit(step, "done")

            # --- 4) 입력: 사람이 치는 것처럼 한 글자씩, 글자마다 60~140ms 쉬면서 ---
            step = "입력 중"; emit(step, "active")
            page.locator(sel.EDITOR).click()
            for ch in comment:
                page.keyboard.type(ch, delay=random.randint(60, 140))
            emit(step, "done")

            # --- 5) 게시 버튼 클릭 ---
            step = "게시 중"; emit(step, "active")
            submit = page.locator(sel.SUBMIT).first
            if not submit.count():  # 셀렉터가 바뀐 경우를 대비해 한국어 버튼 이름으로도 찾는다
                submit = page.get_by_role("button", name=sel.SUBMIT_FALLBACK_NAME, exact=True).last
            submit.click()
            emit(step, "done")

            # --- 6) 확인: 댓글 목록에 내 댓글(앞 20자)이 나타나는지 ---
            step = "확인 중"; emit(step, "active")
            link = _wait_for_comment(page, comment[:20], PWTimeout)
            emit(step, "done")
            time.sleep(1.5)  # 화면에서 결과를 볼 수 있도록 잠깐 유지
            return {"link": link or _watch_url(video_id)}

        # 어떤 실패든 '실패한 단계 표시 + 화면 캡처'를 남기고 PostError 로 통일해 올린다.
        except PostError:
            emit(step, "fail")
            _shot(page, emit)
            raise
        except PWTimeout:
            emit(step, "fail")
            _shot(page, emit)
            raise PostError(f"'{step}' 단계에서 시간이 초과되었습니다.{_blocked_note(locals().get('blocked'))}")
        except Exception as e:
            emit(step, "fail")
            _shot(page, emit)
            if "chrome" in str(e).lower() and "executable" in str(e).lower():
                raise PostError(chrome.INSTALL_HINT)   # 크롬 실행 파일을 못 찾은 경우
            raise PostError(f"'{step}' 단계에서 오류가 났습니다 ({type(e).__name__}).{_blocked_note(locals().get('blocked'))}")
        finally:
            if ctx:  # 성공/실패와 관계없이 크롬을 닫는다
                try:
                    ctx.close()
                except Exception:
                    pass


def _blocked_note(blocked) -> str:
    """안전 규칙으로 막은 이동이 있으면 실패 사유 뒤에 붙일 설명(원인 파악용)."""
    if not blocked:
        return ""
    return " (허용 범위 밖이라 막은 이동: " + ", ".join(dict.fromkeys(blocked)) + ")"


def _wait_for_comment(page, needle: str, PWTimeout):
    """내 댓글(needle 로 시작하는 글)이 댓글 목록에 보일 때까지 기다리고, 그 댓글의 주소를 돌려준다."""
    threads = page.locator(sel.COMMENT_THREADS)
    try:
        page.wait_for_function(
            """([s, n]) => [...document.querySelectorAll(s)].some(e => e.innerText.includes(n))""",
            arg=[sel.COMMENT_THREADS, needle], timeout=15000)
    except PWTimeout:
        raise PostError("게시 후 내 댓글이 목록에서 확인되지 않았습니다.")
    mine = threads.filter(has_text=needle).first
    href = mine.locator(sel.COMMENT_LINK).first.get_attribute("href") if mine.locator(sel.COMMENT_LINK).count() else None
    return f"https://www.youtube.com{href}" if href and href.startswith("/") else href


def _shot(page, emit):
    """실패 화면을 data/screenshots/ 에 저장하고, 대시보드가 보여 줄 수 있게 주소를 emit 에 기록한다."""
    if not page:
        return
    try:
        SCREENSHOTS.mkdir(parents=True, exist_ok=True)
        name = datetime.now().strftime("%Y%m%d-%H%M%S") + ".png"
        page.screenshot(path=str(SCREENSHOTS / name))
        emit.screenshot = f"/screenshots/{name}"
    except Exception:
        pass
