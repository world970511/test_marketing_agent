"""설정 로드.

config/config.yaml(프로필·채널·글자 수·상한·AI 모델)과 .env(AI 토큰)를 읽어 `settings` 하나로 모아 둔다.
다른 모듈은 `from .config import settings` 로 가져다 쓴다.

안전: 프로젝트 폴더 밖의 파일은 읽지 않는다. (크롬 프로필 폴더 경로는 크롬에만 전달하고, 이 코드는 읽지 않는다.)
"""
import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

# 프로젝트 루트와 자주 쓰는 폴더들
ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"                      # 실행 중에 생기는 파일(게시 기록, 실패 캡처). 커밋하지 않는다.
DRAFTS = ROOT / "drafts"                  # 미리 만들어 둔 영상별 댓글 초안(JSON)
SCREENSHOTS = DATA / "screenshots"        # 게시 실패 화면 캡처


def _load_env() -> None:
    """프로젝트 루트의 .env 파일만 읽어 환경변수로 등록한다. 토큰 값은 어디에도 출력하지 않는다."""
    path = ROOT / ".env"
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:   # 빈 줄·주석 건너뜀
            continue
        k, v = line.split("=", 1)
        if v.strip():
            # 이미 설정된 환경변수는 덮어쓰지 않는다(setdefault)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


@dataclass
class Settings:
    """프로그램 전체 설정. config.yaml 의 항목과 1:1 로 대응한다."""
    profiles: list = field(default_factory=list)       # 크롬 프로필 [{name, user_data_dir}]
    channels: list = field(default_factory=list)       # 허용 채널 [{id, name}] — 불러오기·게시 허용 범위
    test_videos: list = field(default_factory=list)    # 개발 중 게시 테스트용 본인 영상 ID
    videos_per_channel: int = 5                        # 채널마다 불러올 최신 영상 수
    min_chars: int = 40                                # 댓글 최소 글자 수
    max_chars: int = 120                               # 댓글 최대 글자 수
    brand: str = "운명원"                              # 댓글에 반드시 들어가는 브랜드 이름
    daily_max: int = 10                                # 하루 게시 상한
    model: str = "Qwen/Qwen3-235B-A22B-Instruct-2507"  # Hugging Face 모델 이름
    provider: str = "auto"                             # Hugging Face 추론 provider

    @property
    def channel_ids(self) -> set:
        """허용 채널 ID 집합 (영상이 허용 채널의 것인지 빠르게 확인할 때 쓴다)."""
        return {c["id"] for c in self.channels}

    @property
    def ai_token(self) -> str:
        """AI(Hugging Face) 토큰. 없으면 빈 문자열."""
        return os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACEHUB_API_TOKEN") or ""

    @property
    def ai_enabled(self) -> bool:
        """AI 토큰이 있어서 AI 기능(초안 생성·재수정)을 쓸 수 있는지."""
        return bool(self.ai_token)


def load() -> Settings:
    """.env 와 config.yaml 을 읽어 Settings 를 만든다."""
    _load_env()
    raw = yaml.safe_load((ROOT / "config" / "config.yaml").read_text(encoding="utf-8"))
    c = raw.get("comment", {})
    return Settings(
        profiles=raw.get("profiles", []),
        channels=raw.get("channels", []),
        test_videos=[str(v) for v in raw.get("test_videos") or []],
        videos_per_channel=int(raw.get("videos_per_channel", 5)),
        min_chars=int(c.get("min_chars", 40)),
        max_chars=int(c.get("max_chars", 120)),
        brand=c.get("brand", "운명원"),
        daily_max=int(raw.get("limits", {}).get("daily_max_comments", 10)),
        model=raw.get("ai", {}).get("model", "Qwen/Qwen3-235B-A22B-Instruct-2507"),
        provider=raw.get("ai", {}).get("provider", "auto"),
    )


settings = load()   # 프로그램이 시작될 때 한 번 읽어 전역으로 공유한다
