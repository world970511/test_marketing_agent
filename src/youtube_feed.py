"""채널 RSS 로 최신 영상 목록을 가져온다 (API 키 불필요).

유튜브는 채널마다 공개 RSS(https://www.youtube.com/feeds/videos.xml?channel_id=채널ID)를 제공한다.
여기서 영상 ID · 제목 · 올린 날짜 · 썸네일을 읽어, 화면의 '영상 불러오기'에 쓴다.

RSS 가 일시적으로 실패(404 등)하면 채널 페이지(/videos)를 대신 읽는다. RSS 가 정상이면 RSS 를 우선 쓴다.
대체 경로의 올린 날짜는 "3일 전" 같은 표시를 바꾼 대략의 값이다.
"""
import asyncio
import json
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

import httpx

from .config import settings

# RSS(XML) 안의 태그 이름공간
NS = {
    "a": "http://www.w3.org/2005/Atom",
    "yt": "http://www.youtube.com/xml/schemas/2015",
}
FEED_URL = "https://www.youtube.com/feeds/videos.xml?channel_id={}"
CACHE_SECONDS = 300          # 같은 채널을 5분 안에 다시 요청하면 저장해 둔 결과를 쓴다

# 지금까지 본 영상들: video_id → 영상 정보. 게시 전에 "허용 채널의 영상인가?" 확인할 때 쓴다.
known_videos: dict = {}
_cache: dict = {}            # 채널 ID → (가져온 시각, 영상 목록)


def thumbnail(video_id: str) -> str:
    """영상 ID 로 썸네일 주소를 만든다(유튜브 이미지 서버)."""
    return f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"


def _parse(xml_text: str, channel_id: str, channel_name: str, limit: int) -> list:
    """RSS(XML) 글을 읽어 최신 영상 limit 개를 영상 정보 딕셔너리 목록으로 만든다."""
    root = ET.fromstring(xml_text)
    out = []
    for e in root.findall("a:entry", NS)[:limit]:         # RSS 는 최신순
        vid = e.findtext("yt:videoId", namespaces=NS)
        if not vid:
            continue
        out.append({
            "id": vid,
            "title": e.findtext("a:title", default="", namespaces=NS),
            "channel": channel_name,
            "channel_id": channel_id,
            "published": e.findtext("a:published", default="", namespaces=NS),
            "thumbnail": thumbnail(vid),
        })
    return out


# ---------- 대체 경로: 채널 페이지(/videos) ----------
# RSS 가 일시적으로 404 등으로 실패할 때만 쓴다. 채널의 '동영상' 탭 HTML 에 들어 있는 목록을 읽는다.
PAGE_URL = "https://www.youtube.com/channel/{}/videos"
PAGE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36",
    "Accept-Language": "ko-KR,ko;q=0.9",
    "Cookie": "CONSENT=YES+1",   # 유튜브 동의 화면을 넘기기 위한 고정 값(사용자의 쿠키가 아니다)
}
_DATA_RE = re.compile(r"var ytInitialData = (\{.*?\});</script>", re.S)
# "3일 전", "2주 전", "1개월 전", "5시간 전" 같은 표시에서 (숫자, 단위)를 뽑는다
_AGO_RE = re.compile(r"(\d+)\s*(초|분|시간|일|주|개월|달|년)\s*전")
_AGO_SECONDS = {"초": 1, "분": 60, "시간": 3600, "일": 86400, "주": 604800, "개월": 2592000, "달": 2592000, "년": 31536000}


def _ago_to_iso(text: str) -> str:
    """'3일 전' 같은 상대 시간을 대략의 날짜(ISO)로 바꾼다. 해석할 수 없으면 빈 문자열."""
    m = _AGO_RE.search(text or "")
    if not m:
        return ""
    when = datetime.now(timezone.utc) - timedelta(seconds=int(m.group(1)) * _AGO_SECONDS[m.group(2)])
    return when.isoformat(timespec="seconds")


def _parse_channel_page(html: str, channel_id: str, channel_name: str, limit: int) -> list:
    """채널 페이지 HTML 에서 영상(ytInitialData 안의 lockupViewModel)을 읽는다. 목록은 기본이 최신순이다."""
    m = _DATA_RE.search(html)
    if not m:
        raise ValueError("채널 페이지에서 영상 목록을 찾지 못했습니다.")
    data = json.loads(m.group(1))
    out = []

    def walk(o):
        """JSON 을 훑으며 '영상' 항목만 모은다."""
        if len(out) >= limit:
            return
        if isinstance(o, dict):
            lv = o.get("lockupViewModel")
            if lv and lv.get("contentType") == "LOCKUP_CONTENT_TYPE_VIDEO":   # 쇼츠·재생목록은 제외
                meta = lv["metadata"]["lockupMetadataViewModel"]
                rows = meta.get("metadata", {}).get("contentMetadataViewModel", {}).get("metadataRows", [])
                parts = [p.get("text", {}).get("content", "") for r in rows for p in r.get("metadataParts", [])]
                published = next((iso for iso in (_ago_to_iso(t) for t in parts) if iso), "")   # '3일 전' 칸
                vid = lv["contentId"]
                out.append({"id": vid, "title": meta["title"]["content"], "channel": channel_name,
                            "channel_id": channel_id, "published": published, "thumbnail": thumbnail(vid)})
                return
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(data)
    if not out:
        raise ValueError("채널 페이지에 영상이 없습니다.")
    return out


async def _fetch_channel(client: httpx.AsyncClient, ch: dict) -> list:
    """채널 하나의 최신 영상 목록. 5분 안에 받은 적이 있으면 캐시를 돌려준다.

    순서: RSS 를 먼저 시도하고, 실패하면 채널 페이지(/videos)에서 읽는다. 둘 다 실패하면 오류.
    """
    hit = _cache.get(ch["id"])
    if hit and time.time() - hit[0] < CACHE_SECONDS:
        return hit[1]
    try:
        r = await client.get(FEED_URL.format(ch["id"]))
        r.raise_for_status()
        videos = _parse(r.text, ch["id"], ch["name"], settings.videos_per_channel)
    except (httpx.HTTPError, ET.ParseError) as rss_error:
        # RSS 실패 → 대체 경로
        try:
            r = await client.get(PAGE_URL.format(ch["id"]), headers=PAGE_HEADERS)
            r.raise_for_status()
            videos = _parse_channel_page(r.text, ch["id"], ch["name"], settings.videos_per_channel)
        except (httpx.HTTPError, ValueError, KeyError) as page_error:
            raise RuntimeError(f"RSS 와 채널 페이지 모두 실패했습니다 (RSS: {rss_error}; 페이지: {page_error})")
    _cache[ch["id"]] = (time.time(), videos)
    return videos


async def fetch_all() -> list:
    """설정의 모든 채널을 동시에 불러온다.  반환: [{id, name, videos:[...], error}] (설정 순서)."""
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        results = await asyncio.gather(
            *[_fetch_channel(client, ch) for ch in settings.channels], return_exceptions=True
        )
    channels = []
    for ch, res in zip(settings.channels, results):
        # 한 채널이 실패해도 나머지는 보여 준다(실패한 채널은 빈 목록 + error 사유)
        videos = [] if isinstance(res, Exception) else res
        for v in videos:
            known_videos[v["id"]] = v
        channels.append({"id": ch["id"], "name": ch["name"], "videos": videos,
                         "error": str(res) if isinstance(res, Exception) else None})
    return channels
