/**
 * DataAnalytics Embeddable Widget
 *
 * Drop-in chat bot for data analysis. Embed via:
 *   <script src="http://YOUR_HOST:8000/widget/widget.js"
 *           data-api-key="ak_..."
 *           data-theme-color="#7c5cfc"
 *           data-api-url="http://YOUR_HOST:8000"></script>
 *
 * Uses Shadow DOM for full CSS isolation from the host page.
 */
(function () {
  "use strict";

  // ── Read config from script tag ──────────────────────────────────────
  const scriptEl = document.currentScript;
  const API_KEY = scriptEl?.getAttribute("data-api-key") || "";
  const THEME = scriptEl?.getAttribute("data-theme-color") || "#7c5cfc";
  const LOGO_URL = scriptEl?.getAttribute("data-logo-url") || "";
  const API_URL = (
    scriptEl?.getAttribute("data-api-url") ||
    new URL(scriptEl?.src || "http://localhost:8000").origin
  ).replace(/\/$/, "");

  // ── State ────────────────────────────────────────────────────────────
  let sessionId = null;
  let isOpen = false;
  let isUploading = false;
  let isAsking = false;

  // ── Inject container + shadow DOM ────────────────────────────────────
  const host = document.createElement("div");
  host.id = "da-widget-host";
  host.style.cssText = "position:fixed;bottom:0;right:0;z-index:2147483647;font-size:16px;";
  document.body.appendChild(host);
  const shadow = host.attachShadow({ mode: "closed" });

  // ── Styles ───────────────────────────────────────────────────────────
  const style = document.createElement("style");
  style.textContent = `
    :host { all: initial; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

    .da-fab {
      position: fixed; bottom: 24px; right: 24px;
      width: 56px; height: 56px; border-radius: 16px;
      background: ${THEME}; border: none; cursor: pointer;
      box-shadow: 0 4px 20px ${THEME}44;
      display: flex; align-items: center; justify-content: center;
      transition: transform .2s, box-shadow .2s;
      z-index: 2147483647;
    }
    .da-fab:hover { transform: scale(1.08); box-shadow: 0 6px 28px ${THEME}66; }
    .da-fab svg { width: 26px; height: 26px; fill: #fff; }
    .da-fab.hidden { display: none; }

    .da-panel {
      position: fixed; bottom: 24px; right: 24px;
      width: 388px; height: 560px; max-height: calc(100vh - 48px);
      border-radius: 20px; overflow: hidden;
      background: #0e0e16; color: #eee;
      border: 1px solid rgba(255,255,255,.08);
      box-shadow: 0 20px 60px rgba(0,0,0,.5), 0 0 40px ${THEME}15;
      display: flex; flex-direction: column;
      transform: scale(.92) translateY(16px); opacity: 0;
      pointer-events: none; transition: all .3s cubic-bezier(.4,0,.2,1);
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      font-size: 14px; line-height: 1.5; z-index: 2147483647;
    }
    .da-panel.open { transform: scale(1) translateY(0); opacity: 1; pointer-events: all; }

    .da-header {
      padding: 14px 16px; display: flex; align-items: center; justify-content: space-between;
      border-bottom: 1px solid rgba(255,255,255,.06); flex-shrink: 0;
    }
    .da-header-left { display: flex; align-items: center; gap: 10px; }
    .da-logo {
      width: 34px; height: 34px; border-radius: 10px;
      background: ${THEME}; display: flex; align-items: center; justify-content: center;
      font-size: 16px; color: #fff; overflow: hidden;
    }
    .da-logo img { width: 100%; height: 100%; object-fit: cover; }
    .da-header h4 { font-size: 14px; font-weight: 600; color: #f0f0f5; }
    .da-header p { font-size: 11px; color: #34d399; }
    .da-close {
      width: 28px; height: 28px; border-radius: 6px; border: none;
      background: rgba(255,255,255,.05); color: #888; cursor: pointer;
      font-size: 16px; display: flex; align-items: center; justify-content: center;
      transition: background .15s;
    }
    .da-close:hover { background: rgba(255,255,255,.1); color: #ccc; }

    .da-messages {
      flex: 1; overflow-y: auto; padding: 16px 12px;
      display: flex; flex-direction: column; gap: 10px;
      scrollbar-width: thin; scrollbar-color: rgba(255,255,255,.1) transparent;
    }
    .da-messages::-webkit-scrollbar { width: 3px; }
    .da-messages::-webkit-scrollbar-thumb { background: rgba(255,255,255,.1); border-radius: 2px; }

    .da-msg {
      max-width: 88%; padding: 10px 14px; border-radius: 14px;
      font-size: 13px; line-height: 1.55; animation: da-fadeIn .25s ease;
      word-break: break-word;
    }
    @keyframes da-fadeIn { from { opacity:0; transform:translateY(6px); } to { opacity:1; transform:translateY(0); } }

    .da-msg.bot {
      align-self: flex-start; background: rgba(255,255,255,.05);
      border: 1px solid rgba(255,255,255,.06); border-bottom-left-radius: 4px;
    }
    .da-msg.user {
      align-self: flex-end; background: ${THEME}; color: #fff;
      border-bottom-right-radius: 4px;
    }
    .da-msg.system {
      align-self: center; background: ${THEME}10; border: 1px solid ${THEME}25;
      text-align: center; font-size: 12px; color: ${THEME}; max-width: 95%; border-radius: 10px;
    }

    .da-msg strong { font-weight: 600; }
    .da-msg table { width: 100%; border-collapse: collapse; margin: 6px 0; font-size: 12px; }
    .da-msg th, .da-msg td {
      padding: 4px 8px; text-align: left;
      border-bottom: 1px solid rgba(255,255,255,.06);
    }
    .da-msg th { font-weight: 600; color: #5ce1e6; font-size: 11px; text-transform: uppercase; letter-spacing: .3px; }

    .da-confidence {
      display: inline-block; padding: 2px 8px; border-radius: 4px;
      font-size: 11px; font-weight: 600; margin-top: 6px;
    }
    .da-confidence.high { background: rgba(52,211,153,.12); color: #34d399; }
    .da-confidence.low { background: rgba(251,191,36,.12); color: #fbbf24; }

    .da-chart-wrap { margin: 8px 0; }
    .da-chart-bar {
      display: flex; align-items: center; gap: 6px; margin: 3px 0; font-size: 12px;
    }
    .da-chart-bar-label { min-width: 80px; text-align: right; color: #aaa; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .da-chart-bar-fill { height: 16px; border-radius: 3px; background: ${THEME}; transition: width .4s ease; }
    .da-chart-bar-val { font-size: 11px; color: #888; min-width: 40px; }

    .da-line-chart { margin: 8px 0; }
    .da-line-chart svg { width: 100%; }

    .da-typing { display: flex; gap: 4px; padding: 12px 16px; align-self: flex-start;
      background: rgba(255,255,255,.05); border: 1px solid rgba(255,255,255,.06);
      border-radius: 14px; border-bottom-left-radius: 4px;
    }
    .da-typing span {
      width: 6px; height: 6px; border-radius: 50%; background: #555;
      animation: da-bounce 1.4s ease-in-out infinite;
    }
    .da-typing span:nth-child(2) { animation-delay: .15s; }
    .da-typing span:nth-child(3) { animation-delay: .3s; }
    @keyframes da-bounce { 0%,60%,100%{ transform:translateY(0); opacity:.4; } 30%{ transform:translateY(-5px); opacity:1; } }

    .da-upload-zone {
      margin: 8px 0; padding: 18px; border: 2px dashed ${THEME}40;
      border-radius: 10px; text-align: center; cursor: pointer;
      transition: border-color .2s, background .2s; background: ${THEME}05;
    }
    .da-upload-zone:hover, .da-upload-zone.dragover { border-color: ${THEME}; background: ${THEME}12; }
    .da-upload-zone svg { width: 28px; height: 28px; fill: ${THEME}; margin-bottom: 6px; }
    .da-upload-zone p { font-size: 13px; color: #aaa; }
    .da-upload-zone .da-formats { font-size: 11px; color: #666; margin-top: 3px; }

    .da-progress { height: 3px; border-radius: 2px; background: rgba(255,255,255,.05); margin-top: 6px; overflow: hidden; }
    .da-progress-bar { height: 100%; border-radius: 2px; background: ${THEME}; transition: width .3s; }

    .da-input-area {
      padding: 10px 12px; border-top: 1px solid rgba(255,255,255,.06); flex-shrink: 0;
      display: flex; align-items: center; gap: 6px;
    }
    .da-input-wrap {
      flex: 1; display: flex; align-items: center; gap: 6px;
      background: rgba(255,255,255,.04); border: 1px solid rgba(255,255,255,.08);
      border-radius: 12px; padding: 3px 3px 3px 12px; transition: border-color .2s;
    }
    .da-input-wrap:focus-within { border-color: ${THEME}55; }
    .da-input-wrap input {
      flex: 1; background: none; border: none; outline: none;
      color: #eee; font-size: 13px; font-family: inherit;
    }
    .da-input-wrap input::placeholder { color: #555; }

    .da-attach {
      width: 34px; height: 34px; border-radius: 8px; border: none;
      background: transparent; cursor: pointer; display: flex;
      align-items: center; justify-content: center; flex-shrink: 0;
      transition: background .15s;
    }
    .da-attach:hover { background: rgba(255,255,255,.06); }
    .da-attach svg { width: 18px; height: 18px; fill: #888; }

    .da-send {
      width: 34px; height: 34px; border-radius: 8px; border: none;
      background: ${THEME}; cursor: pointer; display: flex;
      align-items: center; justify-content: center; flex-shrink: 0;
      transition: transform .15s;
    }
    .da-send:hover { transform: scale(1.05); }
    .da-send:disabled { opacity: .4; cursor: not-allowed; transform: none; }
    .da-send svg { width: 16px; height: 16px; fill: #fff; }

    @media (max-width: 480px) {
      .da-panel { width: 100%; height: 100%; max-height: 100vh; bottom: 0; right: 0; border-radius: 0; }
      .da-fab { bottom: 16px; right: 16px; }
    }
  `;
  shadow.appendChild(style);

  // ── HTML structure ───────────────────────────────────────────────────
  const container = document.createElement("div");
  container.innerHTML = `
    <button class="da-fab" id="daFab" aria-label="Open analytics bot">
      <svg viewBox="0 0 24 24"><path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zm0 14H6l-2 2V4h16v12z"/></svg>
    </button>
    <div class="da-panel" id="daPanel">
      <div class="da-header">
        <div class="da-header-left">
          <div class="da-logo" id="daLogo">📊</div>
          <div>
            <h4>DaAna</h4>

            <p>Online</p>
          </div>
        </div>
        <button class="da-close" id="daClose" aria-label="Close">✕</button>
      </div>
      <div class="da-messages" id="daMessages"></div>
      <div class="da-input-area">
        <button class="da-attach" id="daAttach" aria-label="Upload file">
          <svg viewBox="0 0 24 24"><path d="M16.5 6v11.5c0 2.21-1.79 4-4 4s-4-1.79-4-4V5a2.5 2.5 0 015 0v10.5c0 .83-.67 1.5-1.5 1.5s-1.5-.67-1.5-1.5V6H9v9.5a3 3 0 006 0V5c0-2.21-1.79-4-4-4S7 2.79 7 5v12.5c0 3.04 2.46 5.5 5.5 5.5s5.5-2.46 5.5-5.5V6h-1.5z"/></svg>
        </button>
        <div class="da-input-wrap">
          <input type="text" id="daInput" placeholder="Ask about your data..." disabled>
        </div>
        <button class="da-send" id="daSend" disabled aria-label="Send">
          <svg viewBox="0 0 24 24"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>
        </button>
      </div>
      <input type="file" id="daFileInput" accept=".csv,.tsv,.xlsx,.xls,.json,.parquet,.pq" style="display:none">
    </div>
  `;
  shadow.appendChild(container);

  // ── DOM refs ─────────────────────────────────────────────────────────
  const fab = shadow.getElementById("daFab");
  const panel = shadow.getElementById("daPanel");
  const closeBtn = shadow.getElementById("daClose");
  const messages = shadow.getElementById("daMessages");
  const input = shadow.getElementById("daInput");
  const sendBtn = shadow.getElementById("daSend");
  const attachBtn = shadow.getElementById("daAttach");
  const fileInput = shadow.getElementById("daFileInput");
  const logo = shadow.getElementById("daLogo");

  if (LOGO_URL) logo.innerHTML = `<img src="${esc(LOGO_URL)}" alt="logo">`;

  // ── Open / Close ────────────────────────────────────────────────────
  fab.onclick = () => {
    isOpen = true;
    panel.classList.add("open");
    fab.classList.add("hidden");
    if (!sessionId) initSession();
    else input.focus();
  };

  closeBtn.onclick = () => {
    isOpen = false;
    panel.classList.remove("open");
    fab.classList.remove("hidden");
  };

  // ── Message helpers ─────────────────────────────────────────────────
  function addMsg(html, type = "bot") {
    const div = document.createElement("div");
    div.className = `da-msg ${type}`;
    div.innerHTML = html;
    messages.appendChild(div);
    messages.scrollTop = messages.scrollHeight;
    return div;
  }

  function showTyping() {
    const d = document.createElement("div");
    d.className = "da-typing"; d.id = "daTyping";
    d.innerHTML = "<span></span><span></span><span></span>";
    messages.appendChild(d);
    messages.scrollTop = messages.scrollHeight;
  }

  function hideTyping() {
    const t = shadow.getElementById("daTyping");
    if (t) t.remove();
  }

  function esc(s) {
    if (s == null) return "";
    return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
  }

  function fmtNum(v) {
    if (typeof v === "number") return v % 1 === 0 ? v.toLocaleString() : v.toFixed(2);
    return String(v ?? "");
  }

  // ── Render analysis response ────────────────────────────────────────
  function renderAnalysis(data) {
    addMsg(`<strong>${data.summary}</strong>`);

    for (const sec of (data.sections || [])) {
      if (sec.type === "table" && Array.isArray(sec.data) && sec.data.length) {
        const keys = Object.keys(sec.data[0]);
        let html = `<strong>${esc(sec.title)}</strong><table><thead><tr>`;
        keys.forEach(k => html += `<th>${esc(k)}</th>`);
        html += "</tr></thead><tbody>";
        sec.data.slice(0, 15).forEach(row => {
          html += "<tr>";
          keys.forEach(k => html += `<td>${esc(fmtNum(row[k]))}</td>`);
          html += "</tr>";
        });
        html += "</tbody></table>";
        addMsg(html);
      } else if (sec.type === "bar_chart" && sec.data) {
        const { labels, values } = sec.data;
        const max = Math.max(...values, 1);
        let html = `<strong>${esc(sec.title)}</strong><div class="da-chart-wrap">`;
        labels.forEach((l, i) => {
          const pct = Math.round((values[i] / max) * 100);
          html += `<div class="da-chart-bar">
            <span class="da-chart-bar-label" title="${esc(l)}">${esc(String(l).slice(0, 16))}</span>
            <div class="da-chart-bar-fill" style="width:${pct}%"></div>
            <span class="da-chart-bar-val">${fmtNum(values[i])}</span>
          </div>`;
        });
        html += "</div>";
        addMsg(html);
      } else if (sec.type === "line_chart" && sec.data) {
        const { labels, values, x_label, y_label } = sec.data;
        const max = Math.max(...values, 1);
        const min = Math.min(...values, 0);
        const range = max - min || 1;
        const w = 300, h = 100, pad = 4;
        const pts = values.map((v, i) => {
          const x = pad + (i / Math.max(labels.length - 1, 1)) * (w - 2 * pad);
          const y = h - pad - ((v - min) / range) * (h - 2 * pad);
          return `${x},${y}`;
        });
        let html = `<strong>${esc(sec.title)}</strong><div class="da-line-chart">
          <svg viewBox="0 0 ${w} ${h + 20}" preserveAspectRatio="none">
            <polyline points="${pts.join(" ")}" fill="none" stroke="${THEME}" stroke-width="2" stroke-linejoin="round"/>
            ${values.map((v, i) => {
              const [x, y] = pts[i].split(",");
              return `<circle cx="${x}" cy="${y}" r="3" fill="${THEME}"/>`;
            }).join("")}
            ${labels.map((l, i) => {
              const x = pad + (i / Math.max(labels.length - 1, 1)) * (w - 2 * pad);
              return i % Math.ceil(labels.length / 5) === 0
                ? `<text x="${x}" y="${h + 14}" fill="#666" font-size="9" text-anchor="middle">${esc(String(l).slice(0,7))}</text>` : "";
            }).join("")}
          </svg>
        </div>`;
        addMsg(html);
      }
    }
  }

  // ── Render Q&A response ─────────────────────────────────────────────
  function renderAnswerHtml(data) {
    let text = esc(data.answer || "");
    // Convert bold markdown **text** -> <strong>text</strong>
    text = text.replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>");
    // Convert newlines -> <br>
    text = text.replace(/\n/g, "<br>");

    let html = `<p>${text}</p>`;
    if (data.confidence && data.confidence !== "n/a") {
      html += `<span class="da-confidence ${data.confidence}">${data.confidence === "high" ? "✓" : "⚠"} ${data.confidence}</span>`;
    }
    if (data.caveats?.length) {
      data.caveats.forEach(c => { html += `<p style="font-size:11px;color:#fbbf24;margin-top:4px;">⚠ ${esc(c)}</p>`; });
    }
    return html;
  }


  function renderAnswer(data) {
    addMsg(renderAnswerHtml(data));
  }

  // ── API calls ───────────────────────────────────────────────────────
  async function api(path, opts = {}) {
    const headers = { "X-API-Key": API_KEY, ...(opts.headers || {}) };
    const res = await fetch(`${API_URL}${path}`, { ...opts, headers });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || "Request failed");
    }
    return res.json();
  }

  async function initSession() {
    if (!API_KEY) {
      addMsg("⚠ No API key configured. Add <code>data-api-key</code> to the script tag.", "system");
      return;
    }
    try {
      const data = await api("/api/v1/session", { method: "POST" });
      sessionId = data.session_id;
      input.disabled = false;
      sendBtn.disabled = false;
      addMsg("👋 Hi! I'm your data analyst. Upload a file (CSV, Excel, JSON, or Parquet) and I'll analyze it for you.");
      showUploadZone();
    } catch (e) {
      addMsg(`❌ ${esc(e.message)}`, "system");
    }
  }

  function showUploadZone() {
    const div = document.createElement("div");
    div.className = "da-msg bot";
    div.innerHTML = `
      <div class="da-upload-zone" id="daDropZone">
        <svg viewBox="0 0 24 24"><path d="M19.35 10.04C18.67 6.59 15.64 4 12 4 9.11 4 6.6 5.64 5.35 8.04 2.34 8.36 0 10.91 0 14c0 3.31 2.69 6 6 6h13c2.76 0 5-2.24 5-5 0-2.64-2.05-4.78-4.65-4.96zM14 13v4h-4v-4H7l5-5 5 5h-3z"/></svg>
        <p>Drop your file here or <strong>click to browse</strong></p>
        <div class="da-formats">CSV, Excel, JSON, Parquet</div>
      </div>
      <div class="da-progress" id="daProgress" style="display:none">
        <div class="da-progress-bar" id="daProgressBar" style="width:0%"></div>
      </div>
    `;
    messages.appendChild(div);
    messages.scrollTop = messages.scrollHeight;

    const zone = shadow.getElementById("daDropZone");
    zone.onclick = () => fileInput.click();
    zone.ondragover = e => { e.preventDefault(); zone.classList.add("dragover"); };
    zone.ondragleave = () => zone.classList.remove("dragover");
    zone.ondrop = e => { e.preventDefault(); zone.classList.remove("dragover"); if (e.dataTransfer.files.length) uploadFile(e.dataTransfer.files[0]); };
  }

  // ── File upload ─────────────────────────────────────────────────────
  attachBtn.onclick = () => fileInput.click();
  fileInput.onchange = () => { if (fileInput.files.length) uploadFile(fileInput.files[0]); fileInput.value = ""; };

  async function uploadFile(file) {
    if (isUploading) return;
    isUploading = true;

    addMsg(`📎 ${esc(file.name)} (${(file.size / 1024).toFixed(1)} KB)`, "user");

    const prog = shadow.getElementById("daProgress");
    const bar = shadow.getElementById("daProgressBar");
    if (prog) prog.style.display = "block";

    let pct = 0;
    const iv = setInterval(() => { pct = Math.min(pct + Math.random() * 25, 90); if (bar) bar.style.width = pct + "%"; }, 150);

    try {
      const form = new FormData();
      form.append("file", file);
      if (sessionId) form.append("session_id", sessionId);

      const data = await api("/api/v1/upload", { method: "POST", body: form, headers: {} });

      clearInterval(iv);
      if (bar) bar.style.width = "100%";

      sessionId = data.session_id;
      setTimeout(() => { renderAnalysis(data); }, 200);
    } catch (e) {
      clearInterval(iv);
      addMsg(`❌ Upload failed: ${esc(e.message)}`, "system");
    } finally {
      isUploading = false;
    }
  }

  // ── SSE streaming (fetch-based, not EventSource) ────────────────────
  //
  // IMPORTANT: EventSource cannot set custom request headers, so it cannot
  // send X-API-Key. We use fetch() + a ReadableStream reader instead, with
  // the same X-API-Key header as every other API call in this widget.
  async function askQuestionStream(text, { onChunk, onFinal, onError }) {
    const res = await fetch(`${API_URL}/api/v1/ask/stream`, {
      method: "POST",
      headers: {
        "X-API-Key": API_KEY,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ session_id: sessionId, question: text }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || "Request failed");
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      // SSE events are separated by a blank line (\n\n)
      const events = buffer.split("\n\n");
      buffer = events.pop();

      for (const evt of events) {
        const line = evt.trim();
        if (!line.startsWith("data:")) continue;
        const payload = JSON.parse(line.slice(5).trim());
        if (payload.type === "chunk") {
          onChunk(payload.text || "");
        } else if (payload.type === "final") {
          onFinal(payload.data || {});
        } else if (payload.type === "error") {
          onError(payload.message || "Streaming error");
        }
      }
    }
  }

  // ── Send message ────────────────────────────────────────────────────
  input.onkeydown = e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(); } };
  sendBtn.onclick = sendMessage;

  async function sendMessage() {
    const text = input.value.trim();
    if (!text || isAsking) return;
    input.value = "";

    if (!sessionId) { addMsg("Please wait — session is being created...", "system"); return; }

    addMsg(esc(text), "user");
    showTyping();
    isAsking = true;
    input.disabled = true;
    sendBtn.disabled = true;

    // Build the bot message bubble now; fill it as chunks arrive.
    const botMsg = addMsg("", "bot");
    let streamedText = "";

    try {
      await askQuestionStream(text, {
        onChunk: (chunk) => {
          hideTyping();
          streamedText += chunk;
          botMsg.innerHTML = `<p>${esc(streamedText)}</p>`;
          messages.scrollTop = messages.scrollHeight;
        },
        onFinal: (data) => {
          // Final structured event: answer + confidence/caveats/lineage.
          hideTyping();
          botMsg.innerHTML = renderAnswerHtml(data);
          messages.scrollTop = messages.scrollHeight;
        },
        onError: (msg) => {
          hideTyping();
          if (msg.includes("Session not found") || msg.includes("404")) {
            sessionId = null;
            botMsg.innerHTML = `<p>⚠️ Session expired or server updated. Please re-upload your file to continue.</p>`;
          } else {
            botMsg.innerHTML = `<p>❌ ${esc(msg)}</p>`;
          }
        },
      });
    } catch (e) {
      hideTyping();
      // Fall back to the blocking JSON endpoint if streaming is unavailable.
      try {
        const data = await api("/api/v1/ask", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ session_id: sessionId, question: text }),
        });
        botMsg.innerHTML = renderAnswerHtml(data);
      } catch (e2) {
        if (e2.message.includes("Session not found") || e2.message.includes("404")) {
          sessionId = null;
          botMsg.innerHTML = `<p>⚠️ Session expired or server updated. Please re-upload your file to continue.</p>`;
        } else {
          botMsg.innerHTML = `<p>❌ ${esc(e2.message)}</p>`;
        }
      }
    }
 finally {
      isAsking = false;
      input.disabled = false;
      sendBtn.disabled = false;
      input.focus();
    }
  }
})();