"""AI 초안에 쓸 영상 정보를 모은다: 제목 · 설명 · 자막(있으면) · 인기 댓글.

모두 로그인 없이 유튜브 공개 페이지에서만 읽는다. 하나가 실패해도(자막이 없는 영상 등) 나머지로 계속 진행한다.
"""
import asyncio

from .youtube_resolve import description_from_page, fetch_page


def _transcript_sync(video_id: str) -> str:
    """자막(한국어 우선, 없으면 영어)을 한 덩어리 글로 읽는다. 없거나 막히면 빈 문자열."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:
        return ""
    try:
        try:  # 최신 버전의 사용법
            parts = YouTubeTranscriptApi().fetch(video_id, languages=["ko", "en"])
            texts = [p.text for p in parts]
        except AttributeError:  # 구버전의 사용법
            parts = YouTubeTranscriptApi.get_transcript(video_id, languages=["ko", "en"])
            texts = [p["text"] for p in parts]
        return " ".join(texts)
    except Exception:
        return ""  # 자막 없음/차단 — 제목·설명만으로 진행


def _top_comments_sync(video_id: str, limit: int = 10) -> list:
    """인기순(좋아요 많은 순) 댓글 상위 limit 개. 실패하면 빈 목록."""
    try:
        from itertools import islice

        from youtube_comment_downloader import SORT_BY_POPULAR, YoutubeCommentDownloader
        it = YoutubeCommentDownloader().get_comments_from_url(
            f"https://www.youtube.com/watch?v={video_id}", sort_by=SORT_BY_POPULAR)
        out = []
        for c in islice(it, limit):
            text = " ".join(c.get("text", "").split())     # 줄바꿈·연속 공백을 한 칸으로
            if text:
                out.append(text[:200])                     # 댓글 하나는 200자까지만
        return out
    except Exception:
        return []


async def fetch_context(video: dict) -> dict:
    """영상 하나의 정보를 모아 AI 에게 줄 재료로 만든다.  반환: {title, channel, description, transcript, top_comments}"""
    description = ""
    try:
        description = description_from_page(await fetch_page(video["id"]))
    except Exception:
        pass
    # 자막과 인기 댓글은 느린 작업이라 별도 스레드에서 동시에 가져온다
    transcript, top_comments = await asyncio.gather(
        asyncio.to_thread(_transcript_sync, video["id"]),
        asyncio.to_thread(_top_comments_sync, video["id"]),
    )
    return {"id": video["id"], "title": video["title"], "channel": video["channel"], "description": description,
            "transcript": transcript, "top_comments": top_comments}
