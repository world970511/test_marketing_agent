"""링크/영상 ID → 영상 정보와 채널 ID.

'이 영상이 우리 채널(허용 범위)의 것인가?'를 확인하는 데 쓴다.
  - extract_video_id : 링크에서 영상 ID 를 뽑는다
  - get_video        : 영상 정보(제목·채널 ID 등)를 얻는다 (목록에서 본 영상이면 그대로, 아니면 영상 페이지에서 읽음)
  - is_allowed       : 허용 채널의 영상(또는 테스트 영상)인지 판정한다
"""
import json
import re
from urllib.parse import parse_qs, urlparse

import httpx

from .config import settings
from .youtube_feed import known_videos, thumbnail

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36",
    "Accept-Language": "ko-KR,ko;q=0.9",
    "Cookie": "CONSENT=YES+1",  # 유튜브 동의 화면을 넘기기 위한 고정 값(사용자의 쿠키가 아니다)
}
ID_RE = re.compile(r"^[\w-]{11}$")      # 유튜브 영상 ID 형식: 영문·숫자·-·_ 11자


class ResolveError(Exception):
    """링크가 잘못됐거나 영상 정보를 확인하지 못했을 때. 메시지는 화면에 그대로 보여 준다."""


def extract_video_id(url: str) -> str:
    """유튜브 링크(youtu.be / watch?v= / shorts / embed / live)에서 영상 ID 를 뽑는다."""
    u = urlparse(url.strip())
    host = (u.hostname or "").lower().removeprefix("www.").removeprefix("m.")
    vid = None
    if host == "youtu.be":
        vid = u.path.strip("/").split("/")[0]
    elif host in ("youtube.com", "music.youtube.com"):
        if u.path == "/watch":
            vid = (parse_qs(u.query).get("v") or [None])[0]
        else:
            m = re.match(r"^/(shorts|embed|live)/([\w-]{11})", u.path)
            vid = m.group(2) if m else None
    if not vid or not ID_RE.match(vid):
        raise ResolveError("유튜브 영상 링크가 아닙니다.")
    return vid


def _meta(html: str, prop: str) -> str:
    """영상 페이지의 <meta itemprop="..." content="..."> 값을 읽는다."""
    m = re.search(r'<meta itemprop="%s" content="([^"]*)"' % prop, html)
    return m.group(1) if m else ""


async def fetch_page(video_id: str) -> str:
    """영상 페이지(공개 HTML)를 받아 온다. 로그인 정보는 쓰지 않는다."""
    async with httpx.AsyncClient(timeout=15, follow_redirects=True, headers=HEADERS) as client:
        r = await client.get(f"https://www.youtube.com/watch?v={video_id}")
        r.raise_for_status()
        return r.text


def _title(html: str) -> str:
    """영상 페이지에서 제목을 읽는다."""
    m = re.search(r'<meta name="title" content="([^"]*)"', html)
    if not m:
        return ""
    import html as h
    return h.unescape(m.group(1))


async def get_video(video_id: str) -> dict:
    """영상 정보를 돌려준다. 목록에서 본 영상이면 저장된 정보를, 아니면 영상 페이지에서 채널 ID 를 읽는다."""
    if video_id in known_videos:
        return known_videos[video_id]
    try:
        page = await fetch_page(video_id)
    except httpx.HTTPError:
        raise ResolveError("영상 정보를 가져오지 못했습니다.")
    # 영상이 속한 채널의 ID(UC...)를 페이지에서 찾는다
    m = re.search(r'"externalChannelId":"(UC[\w-]{22})"', page)
    channel_id = m.group(1) if m else _meta(page, "channelId")
    if not channel_id:
        raise ResolveError("영상의 채널을 확인하지 못했습니다.")
    channel_name = next((c["name"] for c in settings.channels if c["id"] == channel_id), "")
    if not channel_name:  # 우리 채널이 아니면 페이지에 적힌 채널 이름을 쓴다
        m = re.search(r'<link itemprop="name" content="([^"]*)"', page)
        channel_name = m.group(1) if m else "테스트 영상"
    video = {
        "id": video_id,
        "title": _title(page) or video_id,
        "channel": channel_name,
        "channel_id": channel_id,
        "published": _meta(page, "datePublished"),
        "thumbnail": thumbnail(video_id),
    }
    known_videos[video_id] = video
    return video


def is_allowed(video: dict) -> bool:
    """허용 범위 판정: 우리 채널 5개의 영상이거나, 설정에 적은 본인 테스트 영상이어야 한다."""
    return video["channel_id"] in settings.channel_ids or video["id"] in settings.test_videos


def description_from_page(html: str) -> str:
    """영상 페이지에 들어 있는 영상 설명(shortDescription)을 읽는다. AI 에게 줄 영상 정보로 쓴다."""
    m = re.search(r'"shortDescription":"((?:[^"\\]|\\.)*)"', html)
    if not m:
        return ""
    try:
        return json.loads(f'"{m.group(1)}"')     # \n, \uXXXX 같은 이스케이프를 풀어 준다
    except ValueError:
        return ""
