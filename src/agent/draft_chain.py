"""초안 작성 (AI 호출 2번을 순서대로 연결).

  1) understand : 영상 정보(제목·설명·자막·인기 댓글) → {summary(영상 요약), worry(고민 한 줄), moments(영상 속 장면·발언)}
  2) write_draft: 요약·고민·장면 → 영상 속 장면을 짚는 댓글 (규칙을 통과할 때까지 다시 쓰기)
프롬프트 원문은 prompts.py, 규칙 검사는 rules.py 에 있다.
"""
import json
import zlib

from ..config import settings
from . import prompts, rules
from .llm import chat


def _parse_json(text: str) -> dict:
    """모델 답에서 {summary, worry, moments} JSON 을 꺼낸다. 앞뒤에 설명이나 ``` 가 붙어도 첫 { ~ 마지막 } 만 읽는다."""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("JSON 형식이 아닙니다.")
    data = json.loads(text[start:end + 1])
    if not data.get("summary") or not data.get("worry"):
        raise ValueError("summary/worry 가 비어 있습니다.")
    moments = data.get("moments") or []
    if isinstance(moments, str):
        moments = [moments]
    return {"summary": str(data["summary"]).strip(), "worry": str(data["worry"]).strip(),
            "moments": [str(m).strip() for m in moments if str(m).strip()][:3]}


def understand(ctx: dict) -> dict:
    """1단계: 영상 정보를 읽고 {summary, worry, moments} 로 정리한다. 모델이 JSON 형식을 어기면 최대 3번 다시 요청."""
    human = prompts.UNDERSTAND_HUMAN.format(
        title=ctx["title"], channel=ctx.get("channel", ""),
        description=(ctx.get("description") or "(없음)")[:1500],        # 너무 길면 잘라서 보낸다
        transcript=(ctx.get("transcript") or "(없음)")[:6000],
        top_comments="\n".join(f"- {c}" for c in ctx.get("top_comments") or []) or "(없음)",
    )
    last = None
    for _ in range(3):
        try:
            # 정리 작업은 일정한 결과가 좋아서 temperature 를 낮게 쓴다
            return _parse_json(chat(prompts.UNDERSTAND_SYSTEM.format(), human, temperature=0.3))
        except (ValueError, json.JSONDecodeError) as e:
            last = e
    raise ValueError(f"요약 결과를 해석하지 못했습니다: {last}")


def pick_styles(video_id: str, n_others: int) -> tuple:
    """영상마다 댓글 시작 방식·브랜드 언급 방식을 다르게 정한다.

    이미 만든 댓글 수(n_others)와 영상 ID 의 해시를 섞어 돌려 가며 고르므로, 연달아 만들어도 서로 다른 조합이 나온다.
    """
    h = zlib.crc32(video_id.encode("utf-8"))
    opening = prompts.OPENING_STYLES[(n_others + h) % len(prompts.OPENING_STYLES)]
    brand = prompts.BRAND_STYLES[(n_others * 2 + h // 7) % len(prompts.BRAND_STYLES)]
    return opening, brand


def write_draft(ctx: dict, other_comments: list) -> dict:
    """영상 정보로 요약·고민·댓글 초안을 만든다.

    ctx            : {id?, title, channel, description, transcript, top_comments}
    other_comments : 이미 만든 다른 영상 댓글들 — 겹치지 않게 모델에게 알려 주고, 같은 문구를 쓰면 규칙 위반으로 본다.
    반환           : {summary, worry, moments, comment}
    """
    u = understand(ctx)
    system = prompts.COMMENT_SYSTEM.format(
        brand=settings.brand, min_chars=settings.min_chars, max_chars=settings.max_chars)
    others = "\n".join(f"- {c}" for c in other_comments[-8:]) or "(없음)"    # 최근 8개만 참고로 준다
    opening, brand_style = pick_styles(ctx.get("id") or ctx["title"], len(other_comments))
    moments = "\n".join(f"- {m}" for m in u["moments"]) or "(없음: 영상 속 발언이나 장면을 지어내지 말고 제목의 주제만 짚으세요)"

    def call(feedback: str) -> str:
        """규칙 검사에 걸리면 feedback(어긴 규칙)을 넣어 다시 부른다."""
        human = prompts.COMMENT_HUMAN.format(
            title=ctx["title"], summary=u["summary"], worry=u["worry"], moments=moments,
            opening_style=opening, brand=settings.brand, brand_style=brand_style,
            others=others, feedback=feedback)
        return chat(system, human, temperature=0.9)       # 댓글은 다양하게 나오도록 temperature 를 높게

    # 겹침 검사는 '저장된 모든 다른 댓글'을 기준으로 한다(프롬프트에는 최근 8개만 보여 준다)
    return {**u, "comment": rules.generate_valid(call, other_comments, attempts=4)}
