"""AI 부분.

  prompts.py      AI 에게 주는 프롬프트 원문
  llm.py          Hugging Face InferenceClient 호출
  draft_chain.py  초안 작성(영상 요약·고민 → 댓글)
  revise_chain.py 초안 재작성(수정 요청 반영)
  rules.py        댓글 규칙 검사(글자 수·링크·해시태그·후기 날조 등)
"""
