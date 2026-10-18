// ============================================================================
// 대시보드 프론트엔드 (바닐라 JS). 화면을 그리고 서버(src/app.py)와 대화한다.
// 외부 라이브러리·외부 요청은 없다(썸네일만 i.ytimg.com).
//
// 화면 흐름
//   ① [영상 불러오기] → 채널 목록 → 채널 클릭 → 그 채널의 최신 영상 목록
//   ② 영상 선택(또는 링크 입력) → 영상 카드 · 요약 · AI 댓글 초안
//        · [직접 편집]: 초안을 손으로 고침
//        · [AI 재수정]: 수정 요청을 적으면 AI 가 초안을 다시 씀
//   ③ [댓글 달기] → 크롬 프로필이 열리고 게시 → 진행 상태/결과 표시
//   [댓글 기록 확인] → 기록 모달
//
// 서버 API 계약 (서버가 꺼져 있으면 아래 MOCK 데이터로 화면만 동작한다)
//   GET  /api/config                  -> { profiles:[이름], daily_max, comment:{min_chars,max_chars} }
//   GET  /api/channels                -> [{ id, name, videos:[Video] }]
//   POST /api/videos/by-link {url}    -> Video  (허용 채널이 아니면 4xx + {detail})
//   GET  /api/draft/{video_id}        -> { summary, worry, comment }   (AI 초안 작성)
//   POST /api/draft/{video_id}/revise {comment, instruction} -> { comment }   (AI 초안 재작성)
//   POST /api/post {video_id, comment, profile} -> { job_id }
//   GET  /api/post/stream/{job_id}    -> SSE, data: { step, status:"active|done|fail", message?, link?, screenshot? }
//   GET  /api/log                     -> [{ time, video_id, title, profile, comment, ok, reason? }]
// Video = { id, title, channel, channel_id, published, thumbnail, has_draft, posted }
// ============================================================================

// 게시할 때 서버가 알려 주는 진행 단계 이름(서버 src/poster.py 와 같아야 한다). 미리보기에서도 쓴다.
const STEPS = ["프로필 여는 중", "영상 여는 중", "댓글창 찾는 중", "입력 중", "게시 중", "확인 중"];

// 화면이 기억하는 값 한 곳에 모아 둔다.
const state = {
  mock: false,                       // true 면 서버 없이 미리보기 데이터로 동작 중
  cfg: { profiles: ["유튜브1", "유튜브2", "유튜브3"], daily_max: 10, comment: { min_chars: 40, max_chars: 120 } },
  channels: [],                      // 불러온 채널과 영상들
  channelId: null,                   // 지금 선택된 채널 ID ("__extra" = 링크로 추가한 영상 모음)
  extra: [],                         // 링크로 직접 추가한 영상
  video: null,                       // 지금 선택된 영상
  editing: false,                    // 초안을 직접 편집하는 중인지
  posting: false,                    // 게시 진행 중인지(중복 클릭 방지)
  log: [],                           // 게시 기록
};

// 짧은 도우미: $(id) = getElementById, el(태그, 속성, ...자식) = 요소 만들기
// 사용자/외부 문자열은 textContent 로만 넣어서 HTML 로 해석되지 않게 한다.
const $ = (id) => document.getElementById(id);
const el = (tag, props = {}, ...kids) => {
  const n = Object.assign(document.createElement(tag), props);
  kids.forEach((k) => n.append(k));
  return n;
};

/* ---------- 서버 호출 (서버가 없으면 mock 으로 자동 전환) ---------- */
// 서버가 4xx/5xx 로 준 오류 메시지({detail})는 그대로 화면에 보여 주려고 Error 로 던진다.
// 서버 자체가 없으면(네트워크 오류, 또는 정적 서버의 404) mock 모드로 바꾸고 가짜 응답을 쓴다.
async function api(path, opts) {
  if (!state.mock) {
    try {
      const r = await fetch(path, opts);
      if (!r.ok) {
        const body = await r.json().catch(() => ({}));
        // detail 없는 404/405/501 = API 가 없는 정적 서버 → mock 으로 전환
        if (!body.detail && [404, 405, 501].includes(r.status)) throw new TypeError("api unavailable");
        throw Object.assign(new Error(body.detail || `요청 실패 (${r.status})`), { http: true });
      }
      return await r.json();
    } catch (e) {
      if (e.http) throw e;                 // 서버가 준 오류는 그대로 전달
      state.mock = true;                   // 서버에 닿지 않음 → 미리보기 모드
      $("modeBanner").hidden = false;
    }
  }
  return mockApi(path, opts);
}

/* ---------- ① 영상 불러오기 ---------- */
// [영상 불러오기] 버튼: 채널별 최신 영상을 서버에서 받아 채널 목록을 그린다.
async function loadChannels() {
  $("loadBtn").disabled = true;
  $("loadMsg").textContent = "불러오는 중...";
  try {
    state.channels = await api("/api/channels");
    $("loadMsg").textContent = `채널 ${state.channels.length}개 · 채널을 눌러 최신 영상을 확인하세요.`;
    renderChannels();
    if (state.channels.length) selectChannel(state.channels[0].id);   // 첫 채널을 바로 펼친다
  } catch (e) {
    $("loadMsg").textContent = e.message;
  } finally {
    $("loadBtn").disabled = false;
  }
}

// 왼쪽 채널 버튼 목록을 그린다. 선택된 채널은 aria-pressed="true" 로 표시(스타일은 CSS).
function renderChannels() {
  const ul = $("channelList");
  ul.replaceChildren();
  for (const c of state.channels) {
    const b = el("button", { type: "button" }, el("span", { textContent: c.name }), el("span", { className: "cnt", textContent: `${c.videos.length}개` }));
    b.setAttribute("aria-pressed", String(c.id === state.channelId));
    b.onclick = () => selectChannel(c.id);
    ul.append(el("li", {}, b));
  }
}

// 채널을 고르면 그 채널의 영상 목록을 보여 준다(상세 화면이었다면 목록으로 돌아온다).
function selectChannel(id) {
  state.channelId = id;
  renderChannels();
  renderVideos();
  showList();
}

// ② 칸의 두 화면(목록 / 상세)을 전환한다.
function showList() {
  $("listView").hidden = false;
  $("detailView").hidden = true;
  $("step2Title").textContent = "영상 선택";
}

function showDetail() {
  $("listView").hidden = true;
  $("detailView").hidden = false;
  $("step2Title").textContent = "영상 · 요약 · 댓글 초안";
}
$("backBtn").onclick = showList;

// (가점) 링크 직접 입력: 서버가 영상의 채널이 허용 범위인지 확인해 주고, 통과하면 바로 그 영상을 연다.
$("linkForm").onsubmit = async (e) => {
  e.preventDefault();
  const url = $("linkInput").value.trim();
  const msg = $("linkMsg");
  if (!url) return;
  msg.textContent = "확인 중...";
  try {
    const v = await api("/api/videos/by-link", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ url }) });
    if (!state.extra.some((x) => x.id === v.id)) state.extra.unshift(v);
    state.channelId = "__extra";
    msg.textContent = "추가했습니다.";
    $("linkInput").value = "";
    renderChannels();
    renderVideos();
    pickVideo(v);
  } catch (err) {
    msg.textContent = err.message;    // 예: "허용된 채널의 영상이 아닙니다."
  }
};

/* ---------- ② 영상 목록 / 상세 / 초안 ---------- */
// 지금 선택된 채널(또는 링크로 추가한 영상 모음)의 영상 배열.
function currentVideos() {
  if (state.channelId === "__extra") return state.extra;
  const c = state.channels.find((x) => x.id === state.channelId);
  return c ? c.videos : [];
}

// 영상 목록: 썸네일 · 제목 · 채널 · 올린 날짜. "초안"/"게시함" 뱃지도 붙인다.
function renderVideos() {
  const ul = $("videoList");
  ul.replaceChildren();
  const list = currentVideos();
  $("listEmpty").hidden = list.length > 0;
  for (const v of list) {
    const img = el("img", { className: "thumb", src: v.thumbnail, alt: "", loading: "lazy" });
    img.onerror = () => img.removeAttribute("src");   // 썸네일 실패 시 회색 박스로 대체
    const title = el("div", { className: "vtitle", textContent: v.title });
    if (v.posted) title.append(el("span", { className: "badge posted", textContent: "게시함" }));
    else if (v.has_draft) title.append(el("span", { className: "badge", textContent: "초안" }));
    const meta = el("div", { className: "vmeta", textContent: `${v.channel} · ${fmtDate(v.published)}` });
    const b = el("button", { type: "button" }, img, el("div", {}, title, meta));
    b.setAttribute("aria-pressed", String(state.video && state.video.id === v.id));
    b.onclick = () => pickVideo(v);
    ul.append(el("li", {}, b));
  }
}

// 영상을 고르면: 상세 화면으로 바꾸고, 서버에서 요약 + 댓글 초안을 받아 채운다.
// (저장된 초안이 없으면 서버가 AI 로 새로 만들기 때문에 몇 초 걸릴 수 있다.)
async function pickVideo(v) {
  state.video = v;
  renderVideos();
  resetProgress();
  setEditing(false);
  $("reviseMsg").textContent = "";
  $("selectedInfo").replaceChildren(el("strong", { textContent: v.title }), `${v.channel} · ${fmtDate(v.published)}`);

  // 영상 카드(썸네일 + 제목 + 채널/날짜)
  const img = el("img", { className: "thumb", src: v.thumbnail, alt: "" });
  img.onerror = () => img.removeAttribute("src");
  $("videoCard").replaceChildren(img, el("div", {},
    el("div", { className: "vtitle", textContent: v.title }),
    el("div", { className: "vmeta", textContent: `${v.channel} · ${fmtDate(v.published)}` })));

  showDetail();
  $("summaryText").textContent = "AI가 영상 내용을 정리하고 초안을 쓰는 중...";
  $("worryText").textContent = "";
  $("commentText").value = "";
  setDraftBusy(true);
  updateCount();
  try {
    const d = await api(`/api/draft/${v.id}`);
    if (state.video.id !== v.id) return;   // 응답을 기다리는 사이 다른 영상을 골랐다면 버린다
    $("summaryText").textContent = d.summary || "(요약 없음)";
    $("worryText").textContent = d.worry || "(고민 정리 없음)";
    $("commentText").value = d.comment || "";
  } catch (e) {
    // 초안이 없거나 AI 호출 실패: 사유를 보여 주고, [직접 편집]으로 직접 쓸 수 있게 둔다.
    $("summaryText").textContent = e.message || "초안을 만들지 못했습니다. 직접 작성할 수 있습니다.";
  } finally {
    setDraftBusy(false);
  }
  updateCount();
}

/* ----- 초안 편집: [직접 편집] 과 [AI 재수정] ----- */
// 직접 편집 모드를 켜고 끈다. 꺼져 있으면 textarea 는 읽기 전용이다.
function setEditing(on) {
  state.editing = on;
  $("commentText").readOnly = !on;
  $("editBtn").textContent = on ? "편집 완료" : "직접 편집";
  $("editBtn").classList.toggle("active", on);
  if (on) $("commentText").focus();
}
$("editBtn").onclick = () => setEditing(!state.editing);

// AI 가 일하는 동안(초안 작성/재수정) 편집 관련 버튼을 잠근다.
function setDraftBusy(busy) {
  $("editBtn").disabled = busy;
  $("reviseGo").disabled = busy;
  $("reviseInput").disabled = busy;
}

// [AI 재수정]: 현재 초안(직접 고친 내용 포함) + 수정 요청을 서버에 보내 새 초안을 받는다.
// 수정 요청을 비워 두면 서버가 "같은 뜻을 다른 표현으로" 다시 쓴다.
$("reviseForm").onsubmit = async (e) => {
  e.preventDefault();
  if (!state.video) return;
  const id = state.video.id;
  setEditing(false);
  setDraftBusy(true);
  $("reviseMsg").textContent = "AI가 다시 쓰는 중...";
  try {
    const d = await api(`/api/draft/${id}/revise`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ comment: $("commentText").value, instruction: $("reviseInput").value.trim() }),
    });
    if (state.video.id !== id) return;
    $("commentText").value = d.comment;
    $("reviseInput").value = "";
    $("reviseMsg").textContent = "다시 썼습니다. 마음에 들지 않으면 한 번 더 요청하세요.";
  } catch (err) {
    $("reviseMsg").textContent = err.message;
  } finally {
    setDraftBusy(false);
    updateCount();
  }
};

// 댓글 규칙 검사(화면용). 서버가 게시 직전에 같은 규칙으로 다시 검사하므로, 이것은 미리 알려 주는 용도다.
function validateComment(text) {
  const { min_chars, max_chars } = state.cfg.comment;
  const n = [...text].length;     // 이모지 등도 한 글자로 센다
  if (n < min_chars || n > max_chars) return `${min_chars}~${max_chars}자로 작성하세요.`;
  if (/https?:\/\/|www\./i.test(text)) return "링크는 넣을 수 없습니다.";
  if (/#\S/.test(text)) return "해시태그는 넣을 수 없습니다.";
  return "";
}

// 글자 수 표시를 갱신하고, 규칙을 어기면 [댓글 달기] 버튼을 잠근다.
function updateCount() {
  const t = $("commentText").value;
  const err = t ? validateComment(t) : "";
  $("countText").textContent = `${[...t].length}자`;
  $("countText").classList.toggle("bad", !!err);
  $("ruleText").textContent = err || `${state.cfg.comment.min_chars} ~ ${state.cfg.comment.max_chars}자 · 링크/해시태그 금지`;
  $("postBtn").disabled = state.posting || !state.video || !t || !!err;
}
$("commentText").addEventListener("input", updateCount);

/* ---------- 댓글 기록 모달 ---------- */
$("logBtn").onclick = async () => {
  await refreshLog();             // 열 때마다 최신 기록을 받아 온다
  $("logDialog").showModal();
};
$("logClose").onclick = () => $("logDialog").close();
// 모달 바깥(어두운 영역)을 누르면 닫는다.
$("logDialog").addEventListener("click", (e) => { if (e.target === $("logDialog")) $("logDialog").close(); });

/* ---------- ③ 댓글 달기 ---------- */
// 진행 단계 목록과 결과 상자를 비운다(새 영상을 고르거나 새로 게시할 때).
function resetProgress() {
  $("progress").replaceChildren();
  $("result").hidden = true;
}

// 진행 단계 한 줄을 만들거나 갱신한다. status: "active"(진행 중) | "done"(완료) | "fail"(실패)
function setStep(step, status, message) {
  const ol = $("progress");
  let li = [...ol.children].find((x) => x.dataset.step === step);
  if (!li) {
    li = el("li");
    li.dataset.step = step;
    ol.append(li);
  }
  li.className = status;
  li.textContent = message ? `${step} — ${message}` : step;
}

// 최종 결과 표시. 성공이면 "댓글 보기" 링크, 실패면 사유와 화면 캡처(있으면)를 보여 준다.
function showResult(ok, msg, link, shot) {
  const r = $("result");
  r.hidden = false;
  r.className = "result " + (ok ? "ok" : "err");
  r.replaceChildren(msg);
  if (link) r.append(" ", el("a", { href: link, target: "_blank", rel: "noopener", textContent: "댓글 보기" }));
  if (shot) r.append(el("img", { src: shot, alt: "실패 화면 캡처" }));
}

// [댓글 달기]: 실제로 게시되므로 한 번 더 확인받고, 서버에 게시 작업을 요청한 뒤 진행 상태를 따라간다.
$("postBtn").onclick = async () => {
  const text = $("commentText").value.trim();
  const err = validateComment(text);
  if (err || !state.video) return;
  if (!confirm(`"${state.video.title}"\n\n이 영상에 실제로 댓글을 게시합니다. 진행할까요?`)) return;

  state.posting = true;
  updateCount();
  resetProgress();
  try {
    // 서버가 허용 범위·영상당 1개·하루 상한을 검사하고, 어기면 오류(detail)를 돌려준다.
    const { job_id } = await api("/api/post", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ video_id: state.video.id, comment: text, profile: $("profileSelect").value }),
    });
    await watchJob(job_id);
  } catch (e) {
    showResult(false, e.message);
  } finally {
    state.posting = false;
    updateCount();
    refreshLog();
  }
};

// 서버가 보내는 진행 상태(SSE)를 받아 화면에 반영한다. final 이벤트가 오면 끝난다.
function watchJob(jobId) {
  if (state.mock) return mockWatch(jobId);
  return new Promise((resolve) => {
    const es = new EventSource(`/api/post/stream/${jobId}`);
    es.onmessage = (m) => {
      const ev = JSON.parse(m.data);
      if (ev.step) setStep(ev.step, ev.status, ev.message);
      if (ev.final) {
        showResult(ev.status === "done", ev.message || (ev.status === "done" ? "게시 완료" : "실패"), ev.link, ev.screenshot);
        es.close();
        resolve();
      }
    };
    es.onerror = () => {
      es.close();
      showResult(false, "진행 상태 연결이 끊어졌습니다.");
      resolve();
    };
  });
}

/* ---------- 기록 ---------- */
// 서버에서 기록을 받아 모달의 표와 상단의 "오늘 게시 n / 상한"을 갱신한다. 최신 기록이 위로 온다.
async function refreshLog() {
  try {
    state.log = await api("/api/log");
  } catch { /* 기록을 못 받아도 화면은 계속 쓸 수 있다 */ }
  const body = $("logBody");
  body.replaceChildren();
  $("logEmpty").hidden = state.log.length > 0;
  const today = new Date().toDateString();
  $("quotaUsed").textContent = state.log.filter((l) => l.ok && new Date(l.time).toDateString() === today).length;
  for (const l of [...state.log].reverse()) {
    body.append(el("tr", {},
      el("td", { textContent: new Date(l.time).toLocaleString("ko-KR", { hour12: false }) }),
      el("td", { textContent: l.title }),
      el("td", { textContent: l.profile }),
      el("td", { textContent: l.comment }),
      // ok: true=성공, null=진행 중, false=실패(+사유)
      el("td", { className: l.ok ? "ok" : l.ok === null ? "" : "err", textContent: l.ok ? "성공" : l.ok === null ? "진행 중" : `실패${l.reason ? ` · ${l.reason}` : ""}` }),
    ));
  }
}

// ISO 날짜 문자열을 "2026년 10월 13일" 형태로. 해석할 수 없으면 빈 문자열.
function fmtDate(iso) {
  const d = new Date(iso);
  return isNaN(d) ? "" : d.toLocaleDateString("ko-KR", { year: "numeric", month: "long", day: "numeric" });
}

/* ---------- 미리보기용 mock (서버 없이 화면만 열었을 때) ---------- */
// 실제로는 아무것도 게시되지 않는다. UI 모양과 흐름을 확인하는 용도다.
const MOCK_CHANNELS = [
  ["UCxlc0Ky0aWoD8uI09ad44Tg", "외롭여", "akn-AvCeHBI"],
  ["UC-ee_ziASM251TMXe3P3VZA", "리즈시절 LizTV", "JjY09DSdzx0"],
  ["UC09L3JxGVcn7SKLa-pjTEmw", "러브커넥트 유지연", "DvxMfC_KjX0"],
  ["UCVdtDW-HF4KluixGaBAcI4w", "연애데이터 노노", "3K82-PjUeP0"],
  ["UCkGl2jieOVhGiHPdXF77Yyw", "심리조각", "WxXINTXQSd4"],
];
const MOCK_TITLES = ["남자가 갑자기 연락 줄이는 진짜 이유", "썸에서 연애로 넘어가는 결정적 신호", "이별 후 연락, 해도 될까?", "연애가 자꾸 꼬이는 사람의 공통점", "사랑받는 사람들의 대화법"];
const MOCK_COMMENT = "근데 진짜 연락 줄어드는 얘기 나올 때 뜨끔했어요ㅠㅠ 결국 인연이면 만나는 건가 싶기도 하고. 운명원 연애사주가 그렇게 잘 본다던데 나도 언제 짝 만나는지 한번 보고 싶다.";

// 서버 API 를 흉내 내는 가짜 응답. 경로에 따라 위 "API 계약"과 같은 모양의 데이터를 돌려준다.
function mockApi(path, opts) {
  const body = opts && opts.body ? JSON.parse(opts.body) : {};
  const wait = (v, ms = 250) => new Promise((r) => setTimeout(() => r(v), ms));   // 네트워크 지연 흉내
  if (path === "/api/channels") {
    return wait(MOCK_CHANNELS.map(([id, name, vid], ci) => ({
      id, name,
      videos: MOCK_TITLES.map((t, i) => ({
        id: i === 0 ? vid : `mock${ci}${i}`, title: `${t} (예시)`, channel: name, channel_id: id,
        published: new Date(Date.now() - (ci + i * 2) * 86400000).toISOString(),
        thumbnail: `https://i.ytimg.com/vi/${i === 0 ? vid : "none"}/hqdefault.jpg`,
        has_draft: i === 0, posted: false,
      })),
    })));
  }
  if (path.endsWith("/revise")) return wait({ comment: `${body.instruction ? `[${body.instruction}] ` : ""}${MOCK_COMMENT}`.slice(0, 118) }, 900);
  if (path.startsWith("/api/draft/")) return wait({
    summary: "연락이 뜸해진 상대의 속마음을 짚어 주는 영상. 진행자는 연락 빈도보다 관계의 온도를 보라고 말하고, 중간에 '답장이 늦어도 불안해하지 말라'는 장면이 나온다. (예시)",
    worry: "연락이 줄어든 상대의 마음을 몰라 불안해하는 고민 (예시)",
    comment: MOCK_COMMENT,
  }, 700);
  if (path === "/api/videos/by-link") {
    const m = (body.url || "").match(/(?:youtu\.be\/|v=)([\w-]{11})/);
    if (!m) return Promise.reject(Object.assign(new Error("유튜브 링크가 아닙니다."), { http: true }));
    return wait({ id: m[1], title: "직접 추가한 영상 (예시)", channel: "외롭여", channel_id: MOCK_CHANNELS[0][0], published: new Date().toISOString(), thumbnail: `https://i.ytimg.com/vi/${m[1]}/hqdefault.jpg`, has_draft: false, posted: false });
  }
  if (path === "/api/post") return wait({ job_id: "mock" });
  if (path === "/api/log") return wait(state.log);
  return Promise.reject(new Error("알 수 없는 요청"));
}

// 미리보기용 진행 상태: 실제 서버처럼 단계가 차례로 넘어가는 모습을 흉내 낸다.
async function mockWatch() {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  for (const s of STEPS) {
    setStep(s, "active");
    await sleep(s === "입력 중" ? 1500 : 600);
    setStep(s, "done");
  }
  state.log.push({ time: new Date().toISOString(), video_id: state.video.id, title: state.video.title, profile: $("profileSelect").value, comment: $("commentText").value, ok: true });
  showResult(true, "게시 완료 (미리보기: 실제로 게시되지 않았습니다)", `https://www.youtube.com/watch?v=${state.video.id}`);
}

/* ---------- 시작 ---------- */
// 설정(프로필 이름, 하루 상한, 글자 수 규칙)을 받아 화면에 반영하고, 기록을 불러온다.
async function init() {
  $("loadBtn").onclick = loadChannels;   // 설정을 기다리는 동안에도 버튼이 바로 동작하도록 먼저 연결
  try {
    state.cfg = { ...state.cfg, ...(await api("/api/config")) };
  } catch { /* 기본값 사용 */ }
  $("quotaMax").textContent = state.cfg.daily_max;
  const sel = $("profileSelect");
  sel.append(el("option", { value: "auto", textContent: "자동 배정 (돌아가며)" }));
  state.cfg.profiles.forEach((p) => sel.append(el("option", { value: p, textContent: p })));
  sel.value = state.cfg.profiles[0];
  refreshLog();
}
init();
