"""게시 기록 (data/log.json).

'어느 영상에 · 어느 프로필로 · 무슨 댓글을 · 성공/실패'를 시간순으로 파일에 남기고, 운영 규칙 검사에도 쓴다.
쿠키 같은 브라우저 정보는 저장하지 않는다.

각 기록: {id, time, video_id, title, profile, comment, ok, reason}
  ok = True(성공) / False(실패) / None(진행 중)
"""
import json
import threading
from datetime import datetime

from .config import DATA

PATH = DATA / "log.json"
_lock = threading.Lock()      # 여러 스레드가 동시에 파일을 쓰지 못하게 한다


def _read() -> list:
    """파일에서 기록 전체를 읽는다. 파일이 없거나 깨졌으면 빈 목록."""
    try:
        return json.loads(PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def _write(items: list) -> None:
    DATA.mkdir(exist_ok=True)
    PATH.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")


def all_entries() -> list:
    """기록 전체(오래된 것 → 최신 순)."""
    with _lock:
        return _read()


def start(video_id: str, title: str, profile: str, comment: str) -> int:
    """게시를 시작할 때 '진행 중' 기록을 먼저 남기고 기록 id 를 돌려준다."""
    with _lock:
        items = _read()
        entry = {"id": (items[-1]["id"] + 1) if items else 1,
                 "time": datetime.now().astimezone().isoformat(timespec="seconds"),
                 "video_id": video_id, "title": title, "profile": profile,
                 "comment": comment, "ok": None, "reason": ""}
        items.append(entry)
        _write(items)
        return entry["id"]


def finish(entry_id: int, ok: bool, reason: str = "") -> None:
    """게시가 끝나면 해당 기록을 성공/실패(+사유)로 확정한다."""
    with _lock:
        items = _read()
        for e in items:
            if e["id"] == entry_id:
                e["ok"], e["reason"] = ok, reason
        _write(items)


def posted_video_ids() -> set:
    """이미 댓글을 단(성공했거나 진행 중인) 영상 ID 들 — '영상당 댓글 1개' 규칙에 쓴다."""
    return {e["video_id"] for e in all_entries() if e["ok"] in (True, None)}


def today_count() -> int:
    """오늘(이 컴퓨터의 날짜) 성공했거나 진행 중인 게시 수 — '하루 상한' 규칙에 쓴다."""
    today = datetime.now().astimezone().date()
    return sum(
        1 for e in all_entries()
        if e["ok"] in (True, None) and datetime.fromisoformat(e["time"]).date() == today
    )


def next_auto_profile(names: list) -> str:
    """'자동 배정': 성공 횟수가 가장 적은 프로필을 고른다(동률이면 목록 앞쪽). 계정이 골고루 쓰인다."""
    counts = {n: 0 for n in names}
    for e in all_entries():
        if e["ok"] is True and e["profile"] in counts:
            counts[e["profile"]] += 1
    return min(names, key=lambda n: counts[n])
