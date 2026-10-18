"""운명원 댓글 에이전트 본체 패키지.

구성
  main.py            시작점(서버 실행 + 크롬으로 대시보드 열기)
  app.py             웹 서버·API
  config.py          설정 로드
  chrome.py          크롬 전용 도우미
  youtube_feed.py    채널 RSS 로 영상 목록
  youtube_resolve.py 링크 확인·허용 범위 판정
  context_fetch.py   AI 초안용 영상 정보 수집(설명·자막·인기 댓글)
  draft.py           초안 저장소 + AI 호출 연결
  agent/             AI 부분(프롬프트·호출·규칙 검증)
  guard.py           운영 규칙(허용 범위·영상당 1개·하루 상한·문구)
  poster.py          크롬 프로필로 댓글 게시(Playwright)
  selectors.py       유튜브 화면 셀렉터
  eventlog.py        게시 기록
  static/            대시보드 화면(HTML/CSS/JS)
"""
