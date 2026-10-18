"""운영 규칙을 코드로 강제한다 (화면에서 우회할 수 없도록 서버에서 검사).

게시 직전에 check_post 가 아래 네 가지를 순서대로 확인하고, 하나라도 어기면 GuardError 로 막는다.
  1) 허용 범위   : 우리 채널 5개(+본인 테스트 영상)의 영상만
  2) 영상당 1개  : 이미 댓글을 단 영상에는 다시 달지 않는다(프로필이 달라도)
  3) 하루 상한   : 오늘 게시 수가 설정(기본 10개)에 닿으면 중단
  4) 문구 규칙   : 글자 수·링크·해시태그·브랜드 언급·후기 날조 금지 (agent/rules.py)
"""
from . import eventlog
from .agent import rules
from .config import settings
from .youtube_resolve import is_allowed


class GuardError(Exception):
    """규칙 위반. detail 은 화면에 보여 줄 사유, status 는 HTTP 상태 코드."""
    def __init__(self, detail: str, status: int = 400):
        super().__init__(detail)
        self.detail, self.status = detail, status


def check_post(video: dict, comment: str) -> None:
    """게시해도 되는지 검사한다. 통과하면 아무 일도 없고, 위반이면 GuardError 를 던진다."""
    if not is_allowed(video):
        raise GuardError("허용된 채널의 영상이 아닙니다.", 403)
    if video["id"] in eventlog.posted_video_ids():
        raise GuardError("이 영상에는 이미 댓글을 달았습니다. (영상당 1개)", 409)
    if eventlog.today_count() >= settings.daily_max:
        raise GuardError(f"오늘 게시 상한({settings.daily_max}개)에 도달했습니다.", 429)
    problems = rules.validate(comment)
    if problems:
        raise GuardError(" / ".join(problems), 422)
