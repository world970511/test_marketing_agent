"""웹 서버(FastAPI). 대시보드 화면(src/static)을 내려주고, 화면이 부르는 API 를 처리한다.

127.0.0.1(이 컴퓨터)에서만 열리며, 각 API 는 다음 모듈에 일을 맡긴다.
  채널/영상 목록   → youtube_feed.py (RSS)          링크 확인 → youtube_resolve.py
  요약·댓글 초안   → draft.py → agent/ (AI 호출)     게시 규칙 → guard.py
  게시(크롬 제어)  → poster.py                       기록      → eventlog.py

API 목록
  GET  /api/config                    화면에 필요한 설정(프로필 이름, 하루 상한, 글자 수 규칙)
  GET  /api/channels                  채널별 최신 영상 목록
  POST /api/videos/by-link            링크로 입력한 영상 확인(허용 채널만 통과)
  GET  /api/draft/{video_id}          영상 요약·고민·댓글 초안
  POST /api/draft/{video_id}/revise   초안 AI 재수정
  POST /api/post                      게시 시작(작업 ID 반환)
  GET  /api/post/stream/{job_id}      게시 진행 상태(SSE 실시간 전송)
  GET  /api/log                       게시 기록
"""
import asyncio
import json
import threading
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import draft as drafts
from . import eventlog, guard, poster, youtube_feed
from .config import SCREENSHOTS, settings
from .youtube_resolve import ResolveError, extract_video_id, get_video, is_allowed

app = FastAPI(title="Youtube Agent", docs_url=None, redoc_url=None)   # 자동 API 문서 화면은 끈다
STATIC = Path(__file__).parent / "static"                              # 대시보드 HTML/CSS/JS 폴더

@app.middleware("http")
async def no_cache_static(request, call_next):
    """화면 파일(HTML/JS/CSS)을 브라우저가 오래된 채로 쓰지 않도록, 항상 서버에서 새로 받게 한다."""
    response = await call_next(request)
    if not request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-cache"
    return response


jobs: dict = {}                  # 진행 중/끝난 게시 작업: job_id → {"events": [...], "done": bool}
post_lock = threading.Lock()       # 동시에 게시는 하나만 (두 개가 겹치면 하루 상한·중복 검사가 어긋난다)


# ---- 요청 본문 형식 (화면이 보내는 JSON) ----
class LinkIn(BaseModel):
    url: str                       # 사용자가 입력한 영상 링크


class PostIn(BaseModel):
    video_id: str
    comment: str                   # 게시할 댓글(화면에서 고친 최종본)
    profile: str = ""              # 프로필 이름. 비우거나 "auto" 면 돌아가며 자동 배정


class ReviseIn(BaseModel):
    comment: str                   # 현재 초안(직접 고친 내용 포함)
    instruction: str = ""          # 수정 요청(비어 있으면 같은 뜻을 다른 표현으로)


async def _allowed_video(video_id: str) -> dict:
    """영상 정보를 확인하고, 허용 범위(우리 채널 + 테스트 영상) 밖이면 403 으로 막는다."""
    try:
        video = await get_video(video_id)
    except ResolveError as e:
        raise HTTPException(400, str(e))
    if not is_allowed(video):
        raise HTTPException(403, "허용된 채널의 영상이 아닙니다.")
    return video


@app.get("/api/config")
def get_config():
    """화면이 시작할 때 받아 가는 설정."""
    return {
        "profiles": [p["name"] for p in settings.profiles],      # 폴더 경로는 내보내지 않고 이름만
        "daily_max": settings.daily_max,
        "comment": {"min_chars": settings.min_chars, "max_chars": settings.max_chars},
        "ai": settings.ai_enabled,                                # AI 토큰이 설정되어 있는지(토큰 값은 내보내지 않는다)
    }


@app.get("/api/channels")
async def get_channels():
    """[영상 불러오기]: 채널별 최신 영상. 각 영상에 '초안 있음'·'이미 게시함' 표시를 붙인다."""
    channels = await youtube_feed.fetch_all()
    posted = eventlog.posted_video_ids()
    for c in channels:
        for v in c["videos"]:
            v["has_draft"] = drafts.load(v["id"]) is not None
            v["posted"] = v["id"] in posted
    return channels


@app.post("/api/videos/by-link")
async def by_link(body: LinkIn):
    """링크로 입력한 영상: 링크에서 영상 ID 를 뽑고, 허용 채널의 영상일 때만 정보를 돌려준다."""
    try:
        video_id = extract_video_id(body.url)
    except ResolveError as e:
        raise HTTPException(400, str(e))
    video = dict(await _allowed_video(video_id))
    video["has_draft"] = drafts.load(video_id) is not None
    video["posted"] = video_id in eventlog.posted_video_ids()
    return video


@app.get("/api/draft/{video_id}")
async def get_draft(video_id: str):
    """영상 요약·고민·댓글 초안. 저장된 초안이 있으면 그것을, 없으면 AI 로 새로 만든다(토큰이 있을 때)."""
    video = await _allowed_video(video_id)
    try:
        d = await drafts.get_or_create(video)
    except drafts.DraftError as e:
        raise HTTPException(e.status, e.detail)
    return {"summary": d.get("summary", ""), "worry": d.get("worry", ""), "comment": d.get("comment", "")}


@app.post("/api/draft/{video_id}/revise")
async def revise_draft(video_id: str, body: ReviseIn):
    """[AI 재수정]: 현재 초안과 수정 요청으로 AI 가 댓글을 다시 쓴다."""
    video = await _allowed_video(video_id)
    try:
        return {"comment": await drafts.revise(video, body.comment, body.instruction)}
    except drafts.DraftError as e:
        raise HTTPException(e.status, e.detail)


@app.get("/api/log")
def get_log():
    """게시 기록 전체(시간순)."""
    return eventlog.all_entries()


@app.post("/api/post")
async def start_post(body: PostIn):
    """[댓글 달기]: 규칙을 검사하고, 통과하면 별도 스레드에서 크롬으로 게시를 시작한다."""
    video = await _allowed_video(body.video_id)

    # 운영 규칙: 허용 범위 · 영상당 1개 · 하루 상한 · 문구 규칙 (어기면 오류로 돌려보낸다)
    try:
        guard.check_post(video, body.comment)
    except guard.GuardError as e:
        raise HTTPException(e.status, e.detail)

    # 프로필 결정: 지정한 이름, 또는 "auto" 면 성공 횟수가 가장 적은 프로필
    names = [p["name"] for p in settings.profiles]
    if not names:
        raise HTTPException(400, "설정에 프로필이 없습니다.")
    profile = eventlog.next_auto_profile(names) if body.profile in ("", "auto") else body.profile
    prof = next((p for p in settings.profiles if p["name"] == profile), None)
    if not prof:
        raise HTTPException(400, "알 수 없는 프로필입니다.")

    if not post_lock.acquire(blocking=False):      # 이미 게시 중이면 거절
        raise HTTPException(409, "다른 댓글을 게시하는 중입니다.")

    job_id = uuid.uuid4().hex[:12]
    job = {"events": [], "done": False}            # 진행 상태 이벤트를 여기에 쌓고, 화면이 SSE 로 읽어 간다
    jobs[job_id] = job
    log_id = eventlog.start(video["id"], video["title"], profile, body.comment)   # '진행 중' 기록 먼저 남김

    def run():
        """게시 작업(스레드). 끝나면 기록을 성공/실패로 확정하고 마지막 이벤트를 남긴다."""
        class Emit:
            """poster 가 진행 단계를 알리는 콜백. 실패 화면 캡처 주소(screenshot)도 여기에 담긴다."""
            screenshot = None

            def __call__(self, step, status, message=None):
                job["events"].append({"step": step, "status": status, "message": message})
        emit = Emit()
        try:
            res = poster.post_comment(prof["user_data_dir"], video["id"], body.comment, emit)
            eventlog.finish(log_id, True)
            job["events"].append({"final": True, "status": "done", "message": f"게시 완료 ({profile})", "link": res["link"]})
        except poster.PostError as e:
            eventlog.finish(log_id, False, str(e))
            job["events"].append({"final": True, "status": "fail", "message": str(e), "screenshot": emit.screenshot})
        except Exception as e:                     # 예상 못 한 오류: 종류만 알린다(내부 정보 노출 방지)
            eventlog.finish(log_id, False, type(e).__name__)
            job["events"].append({"final": True, "status": "fail", "message": f"예상치 못한 오류 ({type(e).__name__})"})
        finally:
            job["done"] = True
            post_lock.release()

    threading.Thread(target=run, daemon=True).start()
    return {"job_id": job_id}


@app.get("/api/post/stream/{job_id}")
async def stream(job_id: str):
    """게시 진행 상태를 SSE(서버→화면 실시간 전송)로 흘려 보낸다. 작업이 끝나고 이벤트를 다 보내면 종료."""
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "없는 작업입니다.")

    async def gen():
        sent = 0                                   # 지금까지 보낸 이벤트 수
        while True:
            while sent < len(job["events"]):
                yield f"data: {json.dumps(job['events'][sent], ensure_ascii=False)}\n\n"
                sent += 1
            if job["done"] and sent >= len(job["events"]):
                return
            await asyncio.sleep(0.3)               # 새 이벤트가 쌓일 때까지 잠깐 대기

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


# 정적 파일: 실패 화면 캡처(/screenshots)와 대시보드 화면(/). "/" 는 API 경로보다 나중에 등록해야 API 를 가리지 않는다.
SCREENSHOTS.mkdir(parents=True, exist_ok=True)
app.mount("/screenshots", StaticFiles(directory=SCREENSHOTS), name="screenshots")
app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
