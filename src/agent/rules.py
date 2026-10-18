"""댓글 규칙 검증.

AI 가 쓴 댓글을 걸러 내는 곳(초안 작성·재수정에서 사용)이자, 게시 직전 guard.py 가 다시 검사하는 곳이다.
화면에서 사람이 고친 댓글도 여기서 같은 규칙으로 검사되므로 규칙을 우회할 수 없다.
"""
import re
from difflib import SequenceMatcher

from ..config import settings

URL_RE = re.compile(r"https?://|www\.|\.(com|net|kr|co)\b", re.I)    # 링크처럼 보이는 글
HASHTAG_RE = re.compile(r"#\S")                                       # 해시태그
# "브랜드를 직접 이용해 본 것처럼" 쓰는 과거형 표현(봤다·받았다·다녀왔다·후기 등)
EXPERIENCE_RE = re.compile(r"(봤|받아\s?봤|받았|갔|다녀|이용|상담|후기|맞더|맞았|소름|신기하게도 맞)")
SENTENCE_SPLIT = re.compile(r"[.!?~ㅠㅜ…\n]+")                         # 문장 나누기

# 모델이 가끔 섞어 넣는 깨진 글자를 걸러 내기 위한 패턴
FOREIGN_RE = re.compile(r"[一-鿿぀-ヿЀ-ӿ฀-๿]")   # 한자·일본어·키릴·태국 문자
LATIN_WORD_RE = re.compile(r"[A-Za-z]+")                                              # 영문 단어
JAMO_RUN_RE = re.compile(r"[ㄱ-ㅎㅏ-ㅣ]{4,}")                                          # 자음/모음만 길게 이어진 글(ㅇㄹㄴㅁ…)
ALLOWED_LATIN = {"MBTI", "TV", "SNS", "DM", "AI", "PD", "OK"}               # 댓글에 써도 되는 영문 약어
MBTI_TYPE_RE = re.compile(r"^[EI][NS][TF][JP]$", re.I)                                # ENFP·intj 같은 MBTI 유형
SHARED_PHRASE_MIN = 10       # 다른 영상 댓글과 이 글자 수 이상 똑같은 문구를 쓰면 '틀에 박힌 표현'으로 본다


def _garbled(text: str) -> str:
    """깨진 글자가 있으면 그 내용을 설명하는 문장을, 없으면 빈 문자열을 돌려준다."""
    if FOREIGN_RE.search(text):
        return "한국어 댓글에 한자·외국 문자가 섞였습니다."
    for w in LATIN_WORD_RE.findall(text):
        # 허용하는 약어(MBTI·16가지 유형 코드 등)만 통과, 그 밖의 영문 단어는 깨진 글자로 본다
        if w not in ALLOWED_LATIN and not MBTI_TYPE_RE.match(w):
            return f"영문 단어 '{w}'가 섞였습니다. 한글로만 쓰세요."
    for run in JAMO_RUN_RE.findall(text):
        if len(set(run)) >= 3:                         # ㅋㅋㅋㅋ·ㅠㅠㅠㅠ 는 괜찮고, ㅇㄹㄴㅁ 처럼 제각각이면 깨진 글
            return "의미 없는 자음/모음 나열이 있습니다."
    return ""


def validate(comment: str, others: list = None) -> list:
    """댓글이 규칙을 지키는지 검사한다.  반환: 문제 목록(비어 있으면 통과).

    comment : 검사할 댓글
    others  : 이미 쓴 다른 영상의 댓글들. 너무 비슷하면 '영상마다 다르게' 규칙 위반으로 본다.
    """
    text = comment.strip()
    problems = []
    n = len(text)
    # 1) 글자 수
    if n > settings.max_chars:
        problems.append(f"{n}자로 너무 깁니다. {settings.max_chars}자 이하여야 하니 {n - settings.max_chars + 10}자 이상 줄이세요"
                        f"(문장 하나를 빼거나 줄이세요).")
    elif n < settings.min_chars:
        problems.append(f"{n}자로 너무 짧습니다. {settings.min_chars}자 이상으로 쓰세요.")
    # 2) 링크 금지
    if URL_RE.search(text):
        problems.append("링크를 넣을 수 없습니다.")
    # 3) 해시태그 금지
    if HASHTAG_RE.search(text):
        problems.append("해시태그를 넣을 수 없습니다.")
    # 4) 브랜드 언급 필수
    if settings.brand not in text:
        problems.append(f"'{settings.brand}' 언급이 있어야 합니다.")
    # 5) 직접 이용한 후기처럼 지어내기 금지: 브랜드가 들어간 문장에 경험 표현이 있으면 위반
    for s in SENTENCE_SPLIT.split(text):
        if settings.brand in s and EXPERIENCE_RE.search(s):
            problems.append(f"'{settings.brand}'를 직접 이용한 후기처럼 쓰면 안 됩니다. '잘 본다던데' 같은 들은 이야기 톤으로 쓰세요.")
            break
    # 6) 깨진 글자(한자·영문 단어·자음 나열)
    garbled = _garbled(text)
    if garbled:
        problems.append(garbled)
    # 7) 다른 영상의 댓글과 전체가 70% 넘게 비슷하거나, 같은 문구(10자 이상)를 그대로 쓰면 위반
    # (브랜드 이름과 '연애 사주' 같은 필수 단어는 모든 댓글에 들어가므로, 비교할 때는 빼고 본다)
    norm = _strip_required_words(text)
    for o in others or []:
        if not o:
            continue
        other = _strip_required_words(o)
        sm = SequenceMatcher(None, norm, other, autojunk=False)
        if sm.ratio() > 0.7:
            problems.append("다른 영상의 댓글과 너무 비슷합니다. 완전히 다르게 쓰세요.")
            break
        m = sm.find_longest_match(0, len(norm), 0, len(other))
        if m.size >= SHARED_PHRASE_MIN:
            problems.append(f"다른 영상 댓글과 똑같은 문구 '{norm[m.a:m.a + m.size].strip()}'를 썼습니다. 표현을 바꾸세요.")
            break
    return problems


def _strip_required_words(text: str) -> str:
    """겹침 비교용: 브랜드 이름·'연애 사주'를 빼고 공백을 정리한다(이 단어들은 모든 댓글에 들어가야 하니 겹쳐도 괜찮다)."""
    for w in (settings.brand, "연애 사주", "연애사주", "사주"):
        text = text.replace(w, " ")
    return " ".join(text.split())


class RuleError(Exception):
    """여러 번 다시 써도 규칙을 통과하지 못했을 때."""
    def __init__(self, problems: list):
        super().__init__(" / ".join(problems))
        self.problems = problems


def generate_valid(call, others: list = None, attempts: int = 3) -> str:
    """AI 호출(call)을 규칙을 통과할 때까지 반복한다.

    call(feedback) -> 댓글 : 모델을 한 번 호출해 댓글을 돌려주는 함수. feedback 에는 직전에 어긴 규칙이 들어간다.
    규칙을 어기면 그 사유를 알려 주며 최대 attempts 번까지 다시 쓰게 하고, 끝내 실패하면 RuleError.
    """
    feedback, last = "", []
    for _ in range(attempts):
        text = " ".join(call(feedback).split())           # 줄바꿈·연속 공백을 한 칸으로(유튜브 댓글은 한 단락으로)
        # 모델이 댓글 전체를 따옴표로 감싼 경우에만 벗긴다. 앞뒤가 짝이 아니면(댓글이 인용 문구로 시작하는 경우 등) 그대로 둔다.
        inner = text[1:-1]
        if len(text) >= 2 and text[0] in "\"“'" and text[-1] in "\"”'" and not any(q in inner for q in "\"“”'"):
            text = inner.strip()
        last = validate(text, others)
        if not last:
            return text
        feedback = "직전 시도가 규칙을 어겼습니다: " + " ".join(last) + " 이 문제를 고쳐서 다시 쓰세요."
    raise RuleError(last)
