"""초안 저장소(drafts/*.json)와 AI 호출을 이어 주는 곳.

  - 이미 만든 초안은 drafts/<영상ID>.json 에서 읽는다(AI 토큰이 없어도 동작).
  - 초안이 없으면 영상 정보를 모아 AI 로 새로 만들고 저장한다(토큰이 있을 때만).
  - [AI 재수정]은 현재 댓글을 AI 로 다시 쓴다(저장하지는 않는다 — 게시할 때 화면의 최종본이 쓰인다).
"""
import asyncio
import json
from datetime import datetime

from .agent.llm import AIUnavailable
from .config import DRAFTS, settings


class DraftError(Exception):
    """초안 생성/재수정 실패. detail 은 화면에 보여 줄 사유, status 는 HTTP 상태 코드."""
    def __init__(self, detail: str, status: int = 400):
        super().__init__(detail)
        self.detail, self.status = detail, status


def load(video_id: str):
    """저장된 초안을 읽는다. 없으면 None."""
    p = DRAFTS / f"{video_id}.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def save(video: dict, d: dict) -> dict:
    """초안을 drafts/<영상ID>.json 으로 저장한다(영상 정보와 만든 시각을 함께)."""
    DRAFTS.mkdir(exist_ok=True)
    d = {"video_id": video["id"], "title": video["title"], "channel": video["channel"],
         **d, "created_at": datetime.now().astimezone().isoformat(timespec="seconds")}
    (DRAFTS / f"{video['id']}.json").write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    return d


def other_comments(exclude_id: str) -> list:
    """다른 영상들의 댓글 목록 — AI 가 표현을 겹치지 않게 하고, 규칙 검사가 유사도를 볼 때 쓴다."""
    out = []
    for p in DRAFTS.glob("*.json"):
        d = load(p.stem)
        if d and d.get("video_id") != exclude_id and d.get("comment"):
            out.append(d["comment"])
    return out


async def get_or_create(video: dict, force: bool = False) -> dict:
    """영상의 초안을 돌려준다. 저장본이 있으면 그것을, 없으면(또는 force) AI 로 새로 만든다.

    반환: {summary, worry, comment, ...}.  만들 수 없으면 DraftError.
    """
    existing = None if force else load(video["id"])
    if existing:
        return existing
    if not settings.ai_enabled:  # 토큰이 없으면 영상 정보를 받아 오기 전에 바로 알린다
        raise DraftError("미리 만든 초안이 없고 AI 토큰도 없습니다. '직접 편집'으로 댓글을 작성하세요.", 404)
    # AI 관련 모듈은 필요할 때만 불러온다(토큰이 없는 환경에서도 서버가 뜨도록)
    from .agent.draft_chain import write_draft
    from .agent.rules import RuleError
    from .context_fetch import fetch_context
    try:
        ctx = await fetch_context(video)                                                    # 제목·설명·자막·인기 댓글
        result = await asyncio.to_thread(write_draft, ctx, other_comments(video["id"]))     # AI 호출(느려서 스레드로)
    except AIUnavailable:
        raise DraftError("미리 만든 초안이 없고 AI 토큰도 없습니다. '직접 편집'으로 댓글을 작성하세요.", 404)
    except RuleError as e:
        raise DraftError(f"AI 초안이 규칙을 통과하지 못했습니다: {e}", 502)
    except Exception as e:  # 네트워크/모델 오류. 토큰 값이 섞이지 않도록 오류 종류만 알린다.
        raise DraftError(f"AI 초안 생성에 실패했습니다 ({type(e).__name__}).", 502)
    return save(video, result)


async def revise(video: dict, comment: str, instruction: str) -> str:
    """현재 댓글을 수정 요청대로 AI 가 다시 써서 새 댓글을 돌려준다."""
    from .agent.revise_chain import revise_draft
    from .agent.rules import RuleError
    base = load(video["id"]) or {}      # 저장된 요약·고민이 있으면 참고 자료로 함께 준다
    try:
        return await asyncio.to_thread(
            revise_draft, video["title"], base.get("summary", ""), base.get("worry", ""),
            comment, instruction, other_comments(video["id"]), base.get("moments", []))
    except AIUnavailable:
        raise DraftError("AI 토큰이 없어 재수정할 수 없습니다. '직접 편집'을 사용하세요.", 400)
    except RuleError as e:
        raise DraftError(f"AI 재수정이 규칙을 통과하지 못했습니다: {e}", 502)
    except Exception as e:
        raise DraftError(f"AI 재수정에 실패했습니다 ({type(e).__name__}).", 502)
