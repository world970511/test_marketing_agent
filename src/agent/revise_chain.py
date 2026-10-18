"""초안 재작성: 현재 댓글 + 사용자의 수정 요청 → 새 댓글.

화면의 [AI 재수정] 버튼이 부른다. 직접 고친 내용도 '현재 댓글'로 넘어오며,
수정 요청이 비어 있으면 같은 뜻을 다른 표현으로 다시 쓴다. 결과는 초안 작성과 같은 규칙(rules.py)을 통과해야 한다.
"""
from ..config import settings
from . import prompts, rules
from .llm import chat


def revise_draft(title: str, summary: str, worry: str, comment: str, instruction: str,
                 other_comments: list, moments: list = None) -> str:
    """댓글을 다시 써서 돌려준다.

    title/summary/worry : 영상 정보(요약·고민은 저장된 초안에서 가져옴, 없으면 빈 값)
    comment             : 현재 댓글(사용자가 직접 고친 것 포함)
    instruction         : 수정 요청(예: "더 짧게")
    other_comments      : 다른 영상의 댓글들(겹침 방지)
    moments             : 영상 속 장면·발언(저장된 초안에 있으면). 댓글이 구체적이도록 참고 자료로 준다.
    """
    moments_text = "\n".join(f"- {m}" for m in moments or []) or "(없음)"
    others_text = "\n".join(f"- {c}" for c in other_comments[-8:]) or "(없음)"
    system = prompts.REVISE_SYSTEM.format(
        brand=settings.brand, min_chars=settings.min_chars, max_chars=settings.max_chars)

    def call(feedback: str) -> str:
        human = prompts.REVISE_HUMAN.format(
            title=title, summary=summary or "(없음)", worry=worry or "(없음)",
            moments=moments_text, others=others_text, comment=comment, instruction=instruction or "(없음)", feedback=feedback)
        return chat(system, human)

    return rules.generate_valid(call, other_comments)
