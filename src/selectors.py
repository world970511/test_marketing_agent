"""유튜브 댓글 화면의 CSS 셀렉터 모음 (한국어 화면 기준).

유튜브 화면 구조가 바뀌면 이 파일만 고치면 된다. poster.py 가 여기 이름들을 가져다 쓴다.
"""
MASTHEAD = "ytd-masthead"                                           # 화면 맨 위 상단바
AVATAR = "ytd-masthead #avatar-btn"                                 # 로그인했을 때만 보이는 내 프로필 사진 버튼
COMMENTS_SECTION ="ytd-comments#comments"                          # 댓글 영역 전체
PLACEHOLDER = "ytd-comments #simple-box #placeholder-area"          # "댓글 추가..." 입력 전 칸 (클릭하면 편집기가 열림)
EDITOR = "ytd-comments #contenteditable-root"                       # 실제로 글자를 치는 입력칸
SUBMIT = "ytd-comments ytd-commentbox #submit-button button, ytd-comments #submit-button button"   # [댓글] 게시 버튼
SUBMIT_FALLBACK_NAME = "댓글"                                        # 위 셀렉터가 안 맞을 때 쓰는 버튼 이름
SIGN_IN = "ytd-comments a[href*='accounts.google.com'], tp-yt-paper-button[aria-label*='로그인']"   # 로그인 안 된 상태에서 보이는 요소
COMMENT_THREADS = "ytd-comments ytd-comment-thread-renderer"        # 댓글 목록의 각 댓글
COMMENT_TEXT = "#content-text"                                       # 댓글 본문
COMMENT_LINK = "a[href*='lc=']"                                      # 개별 댓글 주소(날짜 링크)
