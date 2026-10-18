"""우리 채널 최신 영상의 댓글 초안을 미리 만들어 drafts/ 에 저장한다.

사용:
    python scripts/make_drafts.py              # 채널마다 최신 1개
    python scripts/make_drafts.py -n 3         # 채널마다 최신 3개
    python scripts/make_drafts.py --force      # 이미 있는 초안도 다시 생성
    python scripts/make_drafts.py --video ID   # 특정 영상만 (허용 채널 영상만)

필요: .env 의 HF_TOKEN (값은 출력하지 않는다)
영상은 순서대로 하나씩 만든다 — 앞서 만든 댓글과 겹치지 않게 하기 위해서다.
"""
import argparse
import asyncio
import sys
from pathlib import Path

# scripts/ 안에서 실행해도 프로젝트의 src 패키지를 불러올 수 있게 프로젝트 루트를 경로에 추가한다
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import draft, youtube_feed  # noqa: E402
from src.config import DRAFTS, settings  # noqa: E402
from src.youtube_resolve import ResolveError, get_video, is_allowed  # noqa: E402


async def main() -> int:
    """대상 영상을 정하고 하나씩 초안을 만든다. 반환값: 0=모두 성공, 1=실패가 있거나 토큰 없음."""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-n", type=int, default=1, help="채널마다 만들 최신 영상 수 (기본 1)")
    ap.add_argument("--force", action="store_true", help="이미 있는 초안도 다시 생성")
    ap.add_argument("--video", help="특정 영상 ID 하나만 생성")
    args = ap.parse_args()

    if not settings.ai_enabled:
        print("HF_TOKEN 가 없습니다. 프로젝트 루트의 .env 에 넣고 다시 실행하세요.")
        return 1

    # 대상 영상 정하기: --video 면 그 영상 하나(허용 채널일 때만), 아니면 채널마다 최신 n 개
    if args.video:
        try:
            video = await get_video(args.video)
        except ResolveError as e:
            print(f"실패: {e}")
            return 1
        if not is_allowed(video):
            print("허용된 채널의 영상이 아닙니다.")
            return 1
        targets = [video]
    else:
        targets = []
        for ch in await youtube_feed.fetch_all():
            if ch["error"]:
                print(f"[{ch['name']}] 목록을 가져오지 못했습니다: {ch['error']}")
            targets += ch["videos"][: args.n]

    # 하나씩 순서대로 생성한다(앞서 만든 댓글과 겹치지 않게 하려면 동시에 만들면 안 된다)
    ok = fail = skip = 0
    for v in targets:
        label = f"[{v['channel']}] {v['title'][:40]}"
        if not args.force and draft.load(v["id"]):
            print(f"건너뜀(이미 있음) {label}")
            skip += 1
            continue
        # 다시 만들 때는 옛 초안을 잠시 치워 둔다: 옛 문구가 '다른 영상 댓글'로 취급되어 새 댓글을 방해하지 않게.
        # 실패하면 옛 초안을 원래대로 되돌린다.
        old_path = DRAFTS / f"{v['id']}.json"
        old_text = old_path.read_text(encoding="utf-8") if old_path.is_file() else None
        if old_text is not None:
            old_path.unlink()
        try:
            d = await draft.get_or_create(v, force=True)
            print(f"완료 {label}\n   고민: {d['worry']}\n   댓글: {d['comment']}")
            ok += 1
        except draft.DraftError as e:
            if old_text is not None:
                old_path.write_text(old_text, encoding="utf-8")
            print(f"실패 {label}\n   {e.detail}" + ("  (옛 초안 유지)" if old_text is not None else ""))
            fail += 1

    print(f"\n생성 {ok} · 건너뜀 {skip} · 실패 {fail}  → drafts/")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
