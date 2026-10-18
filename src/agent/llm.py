"""AI 호출부: Hugging Face InferenceClient 로 채팅 모델을 부른다.

토큰(HF_TOKEN)이 없으면 호출하지 않고 AIUnavailable 을 던진다. 이때는 미리 만들어 둔 초안(drafts/)만 쓰인다.
토큰 값은 로그나 화면에 내보내지 않는다.
"""
from ..config import settings


class AIUnavailable(Exception):
    """AI 토큰이 없어 AI 기능을 쓸 수 없을 때."""


def chat(system: str, human: str, max_tokens: int = 700, temperature: float = 0.8) -> str:
    """모델에게 한 번 묻고 답 글을 돌려준다.

    system      : 역할·규칙을 알려 주는 지시문
    human       : 이번에 처리할 내용(영상 정보 등)
    temperature : 낮을수록 일정한 답, 높을수록 다양한 답
    """
    if not settings.ai_enabled:
        raise AIUnavailable("AI 토큰이 설정되어 있지 않습니다.")
    from huggingface_hub import InferenceClient  # 토큰이 있을 때만 불러온다

    client = InferenceClient(model=settings.model, provider=settings.provider,
                             token=settings.ai_token, timeout=90)
    res = client.chat_completion(
        messages=[{"role": "system", "content": system}, {"role": "user", "content": human}],
        max_tokens=max_tokens, temperature=temperature,
    )
    return (res.choices[0].message.content or "").strip()
