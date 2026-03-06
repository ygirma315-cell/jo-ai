(() => {
  "use strict";

  const tg = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;
  const FRONTEND_VERSION = "v1.1.0";
  const QUIZ_BANK = Array.isArray(window.JO_QUIZ_BANK) ? window.JO_QUIZ_BANK : [];
  const STORAGE_KEYS = {
    apiBase: "jo_api_base",
    section: "jo_section_v110",
    calcHistory: "jo_calc_history_v110",
    notes: "jo_notes_v110",
    noteDraft: "jo_note_draft_v110",
    textDraft: "jo_text_draft_v110",
    tttScore: "jo_ttt_score_v110",
    rpsScore: "jo_rps_score_v110",
    memoryBest: "jo_memory_best_v110",
    quizBest: "jo_quiz_best_v110",
    quizLast: "jo_quiz_last_v110"
  };

  const converterGroups = {
    length: {
      label: "Length",
      units: {
        meter: { label: "Meters", toBase: (v) => v, fromBase: (v) => v },
        kilometer: { label: "Kilometers", toBase: (v) => v * 1000, fromBase: (v) => v / 1000 },
        centimeter: { label: "Centimeters", toBase: (v) => v / 100, fromBase: (v) => v * 100 },
        mile: { label: "Miles", toBase: (v) => v * 1609.344, fromBase: (v) => v / 1609.344 },
        foot: { label: "Feet", toBase: (v) => v * 0.3048, fromBase: (v) => v / 0.3048 }
      }
    },
    weight: {
      label: "Weight",
      units: {
        kilogram: { label: "Kilograms", toBase: (v) => v, fromBase: (v) => v },
        gram: { label: "Grams", toBase: (v) => v / 1000, fromBase: (v) => v * 1000 },
        pound: { label: "Pounds", toBase: (v) => v * 0.45359237, fromBase: (v) => v / 0.45359237 },
        ounce: { label: "Ounces", toBase: (v) => v * 0.0283495231, fromBase: (v) => v / 0.0283495231 }
      }
    },
    temperature: {
      label: "Temperature",
      units: {
        celsius: { label: "Celsius", toBase: (v) => v, fromBase: (v) => v },
        fahrenheit: { label: "Fahrenheit", toBase: (v) => ((v - 32) * 5) / 9, fromBase: (v) => (v * 9) / 5 + 32 },
        kelvin: { label: "Kelvin", toBase: (v) => v - 273.15, fromBase: (v) => v + 273.15 }
      }
    }
  };

  const assistantModes = {
    chat: {
      label: "Message",
      placeholder: "Ask anything clearly and the assistant will respond.",
      hint: "Great for quick answers and general help."
    },
    code: {
      label: "Code request",
      placeholder: "Describe the code you need and include the language or framework.",
      hint: "Best for snippets, fixes, and implementation ideas."
    },
    deepseek: {
      label: "Deep analysis request",
      placeholder: "Ask for a concise answer with structured reasoning and a clear result.",
      hint: "Use this for sharper analysis."
    },
    research: {
      label: "Research request",
      placeholder: "Ask for summary, details, tradeoffs, and next steps.",
      hint: "Useful for longer, structured explanations."
    },
    prompt: {
      label: "Prompt request",
      placeholder: "Describe what you want the final prompt to do.",
      hint: "Add a prompt type for better results."
    },
    image: {
      label: "Image idea",
      placeholder: "Describe the subject, style, lighting, and mood.",
      hint: "Generates an image or an improved image prompt."
    },
    kimi: {
      label: "Image explanation",
      placeholder: "Add optional instructions such as 'summarize the scene'.",
      hint: "Upload an image before generating."
    }
  };

  const memorySymbols = ["Arc", "Beam", "Cloud", "Drum", "Leaf", "Wave"];
  const loadingMessages = [
    "Preparing your reply...",
    "Thinking through the request...",
    "Formatting the response...",
    "Almost there..."
  ];

  const elements = {
    welcomeOverlay: document.getElementById("welcomeOverlay"),
    welcomeMessage: document.getElementById("welcomeMessage"),
    openAppBtn: document.getElementById("openAppBtn"),
    sessionBadge: document.getElementById("sessionBadge"),
    connectionBadge: document.getElementById("connectionBadge"),
    storageBadge: document.getElementById("storageBadge"),
    sectionTabs: Array.from(document.querySelectorAll(".section-tab")),
    sectionPanels: Array.from(document.querySelectorAll(".section-panel")),
    assistantStatus: document.getElementById("assistantStatus"),
    assistantState: document.getElementById("assistantState"),
    assistantModes: Array.from(document.querySelectorAll(".assistant-mode")),
    assistantInputLabel: document.getElementById("assistantInputLabel"),
    assistantInput: document.getElementById("assistantInput"),
    assistantHint: document.getElementById("assistantHint"),
    assistantSendBtn: document.getElementById("assistantSendBtn"),
    assistantClearBtn: document.getElementById("assistantClearBtn"),
    assistantCopyBtn: document.getElementById("assistantCopyBtn"),
    assistantDownloadImageBtn: document.getElementById("assistantDownloadImageBtn"),
    assistantOutput: document.getElementById("assistantOutput"),
    promptTypeWrap: document.getElementById("promptTypeWrap"),
    promptType: document.getElementById("promptType"),
    imageTypeWrap: document.getElementById("imageTypeWrap"),
    imageType: document.getElementById("imageType"),
    kimiImageWrap: document.getElementById("kimiImageWrap"),
    kimiImage: document.getElementById("kimiImage"),
    uploadInfo: document.getElementById("uploadInfo"),
    imageWrap: document.getElementById("imageWrap"),
    imagePreview: document.getElementById("imagePreview"),
    imageCaption: document.getElementById("imageCaption"),
    calcDisplay: document.getElementById("calcDisplay"),
    calcKeys: Array.from(document.querySelectorAll(".calc-key")),
    calcHistory: document.getElementById("calcHistory"),
    calcHistoryClearBtn: document.getElementById("calcHistoryClearBtn"),
    notesCount: document.getElementById("notesCount"),
    notesList: document.getElementById("notesList"),
    newNoteBtn: document.getElementById("newNoteBtn"),
    noteTitle: document.getElementById("noteTitle"),
    noteBody: document.getElementById("noteBody"),
    saveNoteBtn: document.getElementById("saveNoteBtn"),
    deleteNoteBtn: document.getElementById("deleteNoteBtn"),
    notesMeta: document.getElementById("notesMeta"),
    converterCategory: document.getElementById("converterCategory"),
    converterValue: document.getElementById("converterValue"),
    converterFrom: document.getElementById("converterFrom"),
    converterTo: document.getElementById("converterTo"),
    converterSwapBtn: document.getElementById("converterSwapBtn"),
    converterResult: document.getElementById("converterResult"),
    textLabInput: document.getElementById("textLabInput"),
    textCharCount: document.getElementById("textCharCount"),
    textWordCount: document.getElementById("textWordCount"),
    textReadTime: document.getElementById("textReadTime"),
    textUpperBtn: document.getElementById("textUpperBtn"),
    textLowerBtn: document.getElementById("textLowerBtn"),
    textTitleBtn: document.getElementById("textTitleBtn"),
    textTrimBtn: document.getElementById("textTrimBtn"),
    textCopyBtn: document.getElementById("textCopyBtn"),
    textClearBtn: document.getElementById("textClearBtn"),
    tttBoard: document.getElementById("tttBoard"),
    tttStatus: document.getElementById("tttStatus"),
    tttScore: document.getElementById("tttScore"),
    tttResetBtn: document.getElementById("tttResetBtn"),
    memoryBoard: document.getElementById("memoryBoard"),
    memoryStatus: document.getElementById("memoryStatus"),
    memoryMoves: document.getElementById("memoryMoves"),
    memoryBest: document.getElementById("memoryBest"),
    memoryResetBtn: document.getElementById("memoryResetBtn"),
    rpsScore: document.getElementById("rpsScore"),
    rpsResult: document.getElementById("rpsResult"),
    rpsResetBtn: document.getElementById("rpsResetBtn"),
    rpsChoices: Array.from(document.querySelectorAll(".choice-btn")),
    questionBankCount: document.getElementById("questionBankCount"),
    quizTopicCount: document.getElementById("quizTopicCount"),
    quizCategory: document.getElementById("quizCategory"),
    quizCount: document.getElementById("quizCount"),
    quizStartBtn: document.getElementById("quizStartBtn"),
    quizRestartBtn: document.getElementById("quizRestartBtn"),
    quizSetupHint: document.getElementById("quizSetupHint"),
    quizBestScore: document.getElementById("quizBestScore"),
    quizLastScore: document.getElementById("quizLastScore"),
    quizProgressLabel: document.getElementById("quizProgressLabel"),
    quizScoreBadge: document.getElementById("quizScoreBadge"),
    quizProgressBar: document.getElementById("quizProgressBar"),
    quizQuestionWrap: document.getElementById("quizQuestionWrap"),
    quizSubmitBtn: document.getElementById("quizSubmitBtn"),
    quizNextBtn: document.getElementById("quizNextBtn"),
    quizFeedback: document.getElementById("quizFeedback"),
    feedbackBtn: document.getElementById("feedbackBtn"),
    versionBadge: document.getElementById("versionBadge"),
    toast: document.getElementById("toast")
  };

  const state = {
    activeSection: "apps",
    assistantMode: "chat",
    assistantBusy: false,
    assistantOnline: false,
    apiBase: "",
    loadingTimer: null,
    loadingIndex: 0,
    toastTimer: null,
    lastOutputText: "",
    lastImageDataUrl: "",
    notes: [],
    selectedNoteId: "",
    noteSaveTimer: null,
    calculatorHistory: [],
    ttt: {
      board: Array(9).fill(""),
      finished: false,
      locked: false,
      score: readJson(STORAGE_KEYS.tttScore, { player: 0, bot: 0, draw: 0 })
    },
    memory: {
      cards: [],
      firstId: "",
      secondId: "",
      moves: 0,
      matchedPairs: 0,
      locked: false,
      best: readJson(STORAGE_KEYS.memoryBest, null)
    },
    rpsScore: readJson(STORAGE_KEYS.rpsScore, { player: 0, bot: 0, draw: 0 }),
    quiz: {
      session: null,
      answered: false,
      best: readJson(STORAGE_KEYS.quizBest, null),
      last: readJson(STORAGE_KEYS.quizLast, null)
    }
  };

  function readJson(key, fallbackValue) {
    try {
      const raw = window.localStorage.getItem(key);
      return raw ? JSON.parse(raw) : fallbackValue;
    } catch (_error) {
      return fallbackValue;
    }
  }

  function writeJson(key, value) {
    try {
      window.localStorage.setItem(key, JSON.stringify(value));
    } catch (_error) {
      // Keep the app working even if storage is blocked.
    }
  }

  function readText(key, fallbackValue = "") {
    try {
      const raw = window.localStorage.getItem(key);
      return typeof raw === "string" ? raw : fallbackValue;
    } catch (_error) {
      return fallbackValue;
    }
  }

  function writeText(key, value) {
    try {
      window.localStorage.setItem(key, String(value));
    } catch (_error) {
      // Keep the app working even if storage is blocked.
    }
  }

  function getQueryParam(name) {
    try {
      const params = new URLSearchParams(window.location.search);
      return (params.get(name) || "").trim();
    } catch (_error) {
      return "";
    }
  }

  function unique(values) {
    const seen = new Set();
    return values.filter((value) => {
      if (!value || seen.has(value)) {
        return false;
      }
      seen.add(value);
      return true;
    });
  }

  function normalizeBase(value) {
    const raw = String(value || "").trim();
    if (!/^https?:\/\//i.test(raw)) {
      return "";
    }
    return raw.replace(/\/+$/, "");
  }

  function isLocalHost() {
    const hostname = String(window.location.hostname || "").toLowerCase();
    return hostname === "127.0.0.1" || hostname === "localhost";
  }

  function shouldTrySameOriginApi() {
    if (!window.location.protocol.startsWith("http")) {
      return false;
    }
    if (window.JO_USE_SAME_ORIGIN_API === true) {
      return true;
    }
    return /^https?:\/\/(?:127\.0\.0\.1|localhost):8000$/i.test(window.location.origin);
  }

  function buildApiBaseCandidates() {
    const queryBase = normalizeBase(getQueryParam("api_base"));
    const explicitBase = normalizeBase(window.JO_API_BASE);
    const storedBase = normalizeBase(readText(STORAGE_KEYS.apiBase));
    const sameOriginBase = shouldTrySameOriginApi() ? normalizeBase(window.location.origin) : "";
    const localhost8000 = normalizeBase("http://127.0.0.1:8000");
    const localhostAlt = normalizeBase("http://localhost:8000");

    if (queryBase) {
      writeText(STORAGE_KEYS.apiBase, queryBase);
    }

    return unique([
      queryBase,
      explicitBase,
      storedBase,
      sameOriginBase,
      isLocalHost() ? localhost8000 : "",
      isLocalHost() ? localhostAlt : ""
    ]);
  }

  function escapeHtml(input) {
    return String(input || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/\"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function shuffle(values) {
    const result = [...values];
    for (let index = result.length - 1; index > 0; index -= 1) {
      const swapIndex = Math.floor(Math.random() * (index + 1));
      [result[index], result[swapIndex]] = [result[swapIndex], result[index]];
    }
    return result;
  }

  function makeId(prefix) {
    if (window.crypto && typeof window.crypto.randomUUID === "function") {
      return `${prefix}-${window.crypto.randomUUID()}`;
    }
    return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  }

  function formatDateTime(value) {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
      return "Just now";
    }
    return date.toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
  }

  function formatNumber(value, maxDigits = 4) {
    if (!Number.isFinite(value)) {
      return "--";
    }
    return new Intl.NumberFormat(undefined, { maximumFractionDigits: maxDigits }).format(value);
  }

  function showToast(text, variant = "success", durationMs = 2600) {
    if (!elements.toast) {
      return;
    }
    elements.toast.hidden = false;
    elements.toast.textContent = text;
    elements.toast.className = `toast ${variant === "error" ? "error" : "success"}`;
    clearTimeout(state.toastTimer);
    state.toastTimer = window.setTimeout(() => {
      if (elements.toast) {
        elements.toast.hidden = true;
      }
    }, durationMs);
  }

  async function copyText(text) {
    const value = String(text || "").trim();
    if (!value) {
      throw new Error("There is nothing to copy yet.");
    }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(value);
      return;
    }
    const buffer = document.createElement("textarea");
    buffer.value = value;
    buffer.style.position = "fixed";
    buffer.style.left = "-9999px";
    document.body.appendChild(buffer);
    buffer.select();
    const ok = document.execCommand("copy");
    document.body.removeChild(buffer);
    if (!ok) {
      throw new Error("Copy failed.");
    }
  }

  function setChip(target, text, variant = "muted") {
    if (!target) {
      return;
    }
    target.textContent = text;
    target.classList.remove("muted", "success", "error");
    target.classList.add(variant);
  }

  function updateConnectionBadge() {
    if (!navigator.onLine) {
      setChip(elements.connectionBadge, "Offline mode: local tools only", "error");
      setChip(elements.assistantStatus, "Assistant unavailable offline", "error");
      return;
    }
    if (state.assistantOnline) {
      setChip(elements.connectionBadge, "Assistant online", "success");
      setChip(elements.assistantStatus, "Ready for online requests", "success");
      return;
    }
    setChip(elements.connectionBadge, "Local tools ready", "muted");
    setChip(elements.assistantStatus, "Assistant checking...", "muted");
  }

  function setVersionBadge() {
    if (elements.versionBadge) {
      elements.versionBadge.textContent = FRONTEND_VERSION;
    }
  }

  function initTelegram() {
    if (!tg) {
      setChip(elements.sessionBadge, "Browser mode", "muted");
      if (elements.welcomeMessage) {
        elements.welcomeMessage.textContent = "You can use the apps, games, and education tools directly in your browser.";
      }
      return;
    }
    tg.ready();
    if (typeof tg.expand === "function") {
      tg.expand();
    }
    const firstName = tg.initDataUnsafe && tg.initDataUnsafe.user && typeof tg.initDataUnsafe.user.first_name === "string"
      ? tg.initDataUnsafe.user.first_name
      : "there";
    setChip(elements.sessionBadge, `Telegram session ready for ${firstName}`, "muted");
    if (elements.welcomeMessage) {
      elements.welcomeMessage.textContent = `${firstName}, your workspace is ready. Open any section and continue where you want.`;
    }
  }

  function initWelcomeOverlay() {
    if (!elements.openAppBtn || !elements.welcomeOverlay) {
      return;
    }
    elements.openAppBtn.addEventListener("click", () => {
      elements.welcomeOverlay.classList.add("hidden");
      if (elements.assistantInput) {
        elements.assistantInput.focus();
      }
    });
  }

  function showSection(sectionId) {
    state.activeSection = sectionId;
    writeText(STORAGE_KEYS.section, sectionId);
    elements.sectionTabs.forEach((button) => {
      button.classList.toggle("active", button.dataset.section === sectionId);
    });
    elements.sectionPanels.forEach((panel) => {
      panel.classList.toggle("active", panel.id === `${sectionId}Section`);
    });
  }

  function wireSectionTabs() {
    showSection(readText(STORAGE_KEYS.section, "apps") || "apps");
    elements.sectionTabs.forEach((button) => {
      button.addEventListener("click", () => showSection(button.dataset.section || "apps"));
    });
  }

  function setAssistantHint(text) {
    if (elements.assistantHint) {
      elements.assistantHint.textContent = text;
    }
  }

  function setAssistantState(text, variant = "muted") {
    setChip(elements.assistantState, text, variant);
  }

  function clearAssistantOutput() {
    state.lastOutputText = "";
    if (elements.assistantOutput) {
      elements.assistantOutput.innerHTML = '<p class="placeholder">Your reply will appear here.</p>';
    }
    if (elements.assistantCopyBtn) {
      elements.assistantCopyBtn.disabled = true;
    }
  }

  function hideAssistantImage() {
    state.lastImageDataUrl = "";
    if (elements.imagePreview) {
      elements.imagePreview.removeAttribute("src");
    }
    if (elements.imageWrap) {
      elements.imageWrap.hidden = true;
    }
    if (elements.assistantDownloadImageBtn) {
      elements.assistantDownloadImageBtn.disabled = true;
    }
  }

  function normalizeImageUrl(value) {
    const raw = String(value || "").trim();
    if (!raw) {
      return "";
    }
    if (raw.startsWith("data:image")) {
      return raw;
    }
    return `data:image/png;base64,${raw.replace(/\s+/g, "")}`;
  }

  function showAssistantImage(value) {
    const dataUrl = normalizeImageUrl(value);
    if (!dataUrl || !elements.imagePreview || !elements.imageWrap) {
      hideAssistantImage();
      return;
    }
    elements.imagePreview.onload = () => {
      state.lastImageDataUrl = dataUrl;
      elements.imageWrap.hidden = false;
      if (elements.assistantDownloadImageBtn) {
        elements.assistantDownloadImageBtn.disabled = false;
      }
      if (elements.imageCaption) {
        elements.imageCaption.textContent = "Generated preview";
      }
    };
    elements.imagePreview.onerror = () => {
      hideAssistantImage();
      showToast("The image could not be displayed.", "error");
    };
    elements.imagePreview.src = dataUrl;
  }

  function renderTextBlock(text) {
    const fragment = document.createDocumentFragment();
    const lines = String(text || "").split(/\r?\n/);
    let listElement = null;
    let listType = "";

    const flushList = () => {
      if (listElement) {
        fragment.appendChild(listElement);
        listElement = null;
        listType = "";
      }
    };

    for (const rawLine of lines) {
      const line = rawLine.trimEnd();
      const headingMatch = line.match(/^(#{1,3})\s+(.+)$/);
      const bulletMatch = line.match(/^[-*+]\s+(.+)$/);
      const numberMatch = line.match(/^\d+\.\s+(.+)$/);

      if (!line.trim()) {
        flushList();
        continue;
      }
      if (headingMatch) {
        flushList();
        const tagName = headingMatch[1].length === 1 ? "h3" : headingMatch[1].length === 2 ? "h4" : "h5";
        const heading = document.createElement(tagName);
        heading.innerHTML = escapeHtml(headingMatch[2]);
        fragment.appendChild(heading);
        continue;
      }
      if (bulletMatch) {
        if (!listElement || listType !== "ul") {
          flushList();
          listElement = document.createElement("ul");
          listType = "ul";
        }
        const item = document.createElement("li");
        item.innerHTML = escapeHtml(bulletMatch[1]);
        listElement.appendChild(item);
        continue;
      }
      if (numberMatch) {
        if (!listElement || listType !== "ol") {
          flushList();
          listElement = document.createElement("ol");
          listType = "ol";
        }
        const item = document.createElement("li");
        item.innerHTML = escapeHtml(numberMatch[1]);
        listElement.appendChild(item);
        continue;
      }
      flushList();
      const paragraph = document.createElement("p");
      paragraph.innerHTML = escapeHtml(line);
      fragment.appendChild(paragraph);
    }

    flushList();
    return fragment;
  }

  function buildCodeBlock(segment) {
    const normalized = String(segment || "").replace(/\r/g, "");
    const lines = normalized.split("\n");
    let language = "code";
    let body = normalized;

    if (lines.length > 1 && /^[A-Za-z0-9_+#.-]{1,20}$/.test(lines[0].trim())) {
      language = lines[0].trim().toLowerCase();
      body = lines.slice(1).join("\n");
    }

    const wrapper = document.createElement("section");
    wrapper.className = "code-block";

    const head = document.createElement("header");
    head.className = "code-head";

    const label = document.createElement("span");
    label.className = "code-lang";
    label.textContent = language;

    const copyButton = document.createElement("button");
    copyButton.type = "button";
    copyButton.className = "code-copy";
    copyButton.textContent = "Copy code";
    copyButton.addEventListener("click", async () => {
      try {
        await copyText(body);
        showToast("Code copied.");
      } catch (error) {
        showToast(error instanceof Error ? error.message : "Copy failed.", "error");
      }
    });

    head.appendChild(label);
    head.appendChild(copyButton);

    const pre = document.createElement("pre");
    const code = document.createElement("code");
    code.textContent = body;
    pre.appendChild(code);

    wrapper.appendChild(head);
    wrapper.appendChild(pre);
    return wrapper;
  }

  function renderAssistantOutput(text) {
    const raw = String(text || "").trim();
    if (!elements.assistantOutput) {
      return;
    }
    elements.assistantOutput.innerHTML = "";
    if (!raw) {
      clearAssistantOutput();
      return;
    }
    state.lastOutputText = raw;
    if (elements.assistantCopyBtn) {
      elements.assistantCopyBtn.disabled = false;
    }
    raw.split(/```/).forEach((segment, index) => {
      if (!segment.trim()) {
        return;
      }
      elements.assistantOutput.appendChild(index % 2 === 1 ? buildCodeBlock(segment) : renderTextBlock(segment));
    });
  }

  function setAssistantMode(mode) {
    state.assistantMode = mode;
    elements.assistantModes.forEach((button) => {
      button.classList.toggle("active", button.dataset.mode === mode);
    });
    const config = assistantModes[mode] || assistantModes.chat;
    if (elements.assistantInputLabel) {
      elements.assistantInputLabel.textContent = config.label;
    }
    if (elements.assistantInput) {
      elements.assistantInput.placeholder = config.placeholder;
    }
    setAssistantHint(config.hint);
    if (elements.promptTypeWrap) {
      elements.promptTypeWrap.hidden = mode !== "prompt";
    }
    if (elements.imageTypeWrap) {
      elements.imageTypeWrap.hidden = mode !== "image";
    }
    if (elements.kimiImageWrap) {
      elements.kimiImageWrap.hidden = mode !== "kimi";
    }
    if (mode !== "image") {
      hideAssistantImage();
    }
  }

  function startAssistantLoading() {
    state.loadingIndex = 0;
    setAssistantState(loadingMessages[0], "muted");
    clearInterval(state.loadingTimer);
    state.loadingTimer = window.setInterval(() => {
      state.loadingIndex = (state.loadingIndex + 1) % loadingMessages.length;
      setAssistantState(loadingMessages[state.loadingIndex], "muted");
    }, 950);
  }

  function stopAssistantLoading() {
    clearInterval(state.loadingTimer);
    state.loadingTimer = null;
  }

  function setAssistantBusy(busy) {
    state.assistantBusy = busy;
    if (elements.assistantSendBtn) {
      elements.assistantSendBtn.disabled = busy;
    }
    if (elements.assistantClearBtn) {
      elements.assistantClearBtn.disabled = busy;
    }
    if (elements.assistantCopyBtn) {
      elements.assistantCopyBtn.disabled = busy || !state.lastOutputText;
    }
    if (elements.assistantDownloadImageBtn) {
      elements.assistantDownloadImageBtn.disabled = busy || !state.lastImageDataUrl;
    }
    if (busy) {
      startAssistantLoading();
      return;
    }
    stopAssistantLoading();
    setAssistantState("Ready", state.assistantOnline ? "success" : "muted");
  }

  async function fetchJsonWithTimeout(url, options, timeoutMs = 60000) {
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await fetch(url, { ...options, signal: controller.signal });
      const raw = await response.text();
      let data = {};
      if (raw) {
        try {
          data = JSON.parse(raw);
        } catch (_error) {
          throw new Error("The assistant returned an unreadable response.");
        }
      }
      return { response, data };
    } catch (error) {
      if (error && error.name === "AbortError") {
        throw new Error("The request took too long.");
      }
      throw error;
    } finally {
      clearTimeout(timer);
    }
  }

  async function isApiHealthy(base) {
    for (const path of ["/api/health", "/health"]) {
      try {
        const { response, data } = await fetchJsonWithTimeout(`${base}${path}`, { method: "GET" }, 5000);
        if (response.ok && data && (data.ok === true || data.status === "ok")) {
          return true;
        }
      } catch (_error) {
        // Try the next path.
      }
    }
    return false;
  }

  async function resolveApiBase() {
    const candidates = buildApiBaseCandidates();
    if (!candidates.length) {
      state.apiBase = "";
      state.assistantOnline = false;
      updateConnectionBadge();
      return "";
    }
    for (const candidate of candidates) {
      if (await isApiHealthy(candidate)) {
        state.apiBase = candidate;
        state.assistantOnline = true;
        writeText(STORAGE_KEYS.apiBase, candidate);
        updateConnectionBadge();
        return candidate;
      }
    }
    state.apiBase = candidates[0];
    state.assistantOnline = false;
    updateConnectionBadge();
    return state.apiBase;
  }

  function endpointAttempts(mode, payload) {
    const basePayload = { ...payload };
    if (mode === "chat") {
      return [{ path: "/api/chat", payload: basePayload }, { path: "/chat", payload: basePayload }];
    }
    if (mode === "code") {
      return [{ path: "/api/code", payload: basePayload }, { path: "/code", payload: basePayload }];
    }
    if (mode === "deepseek") {
      return [
        {
          path: "/api/chat",
          payload: {
            ...basePayload,
            message: "Deep analysis mode.\nRespond with concise sections: Summary, Analysis, Final Answer.\n\n" + `User request:\n${payload.message}`
          }
        },
        {
          path: "/chat",
          payload: {
            ...basePayload,
            message: "Deep analysis mode.\nRespond with concise sections: Summary, Analysis, Final Answer.\n\n" + `User request:\n${payload.message}`
          }
        },
        { path: "/api/research", payload: basePayload },
        { path: "/research", payload: basePayload }
      ];
    }
    if (mode === "research") {
      return [
        { path: "/api/research", payload: basePayload },
        { path: "/research", payload: basePayload },
        {
          path: "/api/chat",
          payload: {
            ...basePayload,
            message: `Research request:\n${payload.message}\n\nReturn sections: Summary, Details, Risks/Tradeoffs, Next Steps.`
          }
        },
        {
          path: "/chat",
          payload: {
            ...basePayload,
            message: `Research request:\n${payload.message}\n\nReturn sections: Summary, Details, Risks/Tradeoffs, Next Steps.`
          }
        }
      ];
    }
    if (mode === "prompt") {
      return [
        { path: "/api/prompt", payload: basePayload },
        { path: "/prompt", payload: basePayload },
        {
          path: "/api/chat",
          payload: {
            ...basePayload,
            message: `Create one optimized ${payload.prompt_type || "general"} prompt.\nUser requirements:\n${payload.message}\n\nReturn only the final prompt text.`
          }
        },
        {
          path: "/chat",
          payload: {
            ...basePayload,
            message: `Create one optimized ${payload.prompt_type || "general"} prompt.\nUser requirements:\n${payload.message}\n\nReturn only the final prompt text.`
          }
        }
      ];
    }
    if (mode === "image") {
      return [
        { path: "/api/image", payload: basePayload },
        { path: "/image", payload: basePayload },
        {
          path: "/api/chat",
          payload: {
            ...basePayload,
            message: `Generate one high-quality image prompt for:\n${payload.message}\n\nPreferred style: ${payload.image_type || "realistic"}.\nReturn only the optimized prompt text.`
          }
        },
        {
          path: "/chat",
          payload: {
            ...basePayload,
            message: `Generate one high-quality image prompt for:\n${payload.message}\n\nPreferred style: ${payload.image_type || "realistic"}.\nReturn only the optimized prompt text.`
          }
        }
      ];
    }
    return [
      { path: "/api/kimi_image_describer", payload: basePayload },
      { path: "/kimi_image_describer", payload: basePayload }
    ];
  }

  async function requestWithFallback(mode, payload) {
    if (!state.apiBase) {
      await resolveApiBase();
    }
    if (!state.apiBase) {
      throw new Error("The assistant is not configured.");
    }
    const errors = [];
    for (const attempt of endpointAttempts(mode, payload)) {
      try {
        const { response, data } = await fetchJsonWithTimeout(
          `${state.apiBase}${attempt.path}`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(attempt.payload)
          },
          mode === "image" ? 90000 : 65000
        );
        if (response.ok) {
          state.assistantOnline = true;
          updateConnectionBadge();
          return data || {};
        }
        const message = data && typeof data.error === "string" && data.error.trim()
          ? data.error.trim()
          : "The assistant request could not be completed.";
        errors.push(message);
      } catch (error) {
        errors.push(error instanceof Error ? error.message : "The assistant request failed.");
      }
    }
    state.assistantOnline = false;
    updateConnectionBadge();
    throw new Error(errors[errors.length - 1] || "The assistant is unavailable right now.");
  }

  function buildAssistantPayload(mode) {
    const message = elements.assistantInput ? elements.assistantInput.value.trim() : "";
    const payload = { message };
    if (mode === "kimi") {
      payload.message = message || "Describe this image.";
      return payload;
    }
    if (!message) {
      throw new Error("Please enter a request first.");
    }
    if (mode === "prompt") {
      const promptType = elements.promptType ? elements.promptType.value.trim() : "";
      if (!promptType) {
        throw new Error("Please add a prompt type first.");
      }
      payload.prompt_type = promptType;
    }
    if (mode === "image") {
      payload.image_type = elements.imageType ? elements.imageType.value : "realistic";
    }
    return payload;
  }

  function fileToBase64(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => {
        const raw = String(reader.result || "");
        const commaIndex = raw.indexOf(",");
        resolve(commaIndex >= 0 ? raw.slice(commaIndex + 1) : raw);
      };
      reader.onerror = () => reject(new Error("The image could not be read."));
      reader.readAsDataURL(file);
    });
  }

  async function callAssistant() {
    if (state.assistantBusy) {
      return;
    }
    let payload;
    try {
      payload = buildAssistantPayload(state.assistantMode);
    } catch (error) {
      renderAssistantOutput(`### Input needed\n${error instanceof Error ? error.message : "Please complete the fields."}`);
      setAssistantState("Input needed", "error");
      showToast("Please complete the required fields.", "error");
      return;
    }

    if (state.assistantMode === "kimi") {
      const file = elements.kimiImage && elements.kimiImage.files ? elements.kimiImage.files[0] : null;
      if (!file) {
        renderAssistantOutput("### Upload an image first\nChoose an image and try again.");
        setAssistantState("Image needed", "error");
        showToast("Upload an image before generating.", "error");
        return;
      }
      if (!file.type.startsWith("image/")) {
        renderAssistantOutput("### Unsupported file\nPlease upload a valid image file.");
        setAssistantState("Unsupported file", "error");
        showToast("Only image files are supported.", "error");
        return;
      }
      if (file.size > 8 * 1024 * 1024) {
        renderAssistantOutput("### File too large\nPlease choose an image smaller than 8 MB.");
        setAssistantState("File too large", "error");
        showToast("Please choose a smaller image.", "error");
        return;
      }
      try {
        payload.image_base64 = await fileToBase64(file);
      } catch (error) {
        renderAssistantOutput(`### Upload problem\n${error instanceof Error ? error.message : "The image could not be read."}`);
        setAssistantState("Upload failed", "error");
        return;
      }
    }

    setAssistantBusy(true);
    try {
      const data = await requestWithFallback(state.assistantMode, payload);
      const output = data && typeof data.output === "string" && data.output.trim()
        ? data.output.trim()
        : data && typeof data.warning === "string" && data.warning.trim()
          ? data.warning.trim()
          : "No response was returned.";
      renderAssistantOutput(output);
      if (data && data.image_base64) {
        showAssistantImage(data.image_base64);
      } else {
        hideAssistantImage();
      }
      setAssistantState("Response ready", "success");
      showToast("Response ready.");
    } catch (error) {
      const message = error instanceof Error ? error.message : "The assistant is unavailable right now.";
      renderAssistantOutput(`### Assistant unavailable\n${message}\n\nThe offline apps, games, and education tools still work normally.`);
      hideAssistantImage();
      setAssistantState("Unavailable", "error");
      showToast("The assistant is unavailable right now.", "error");
    } finally {
      setAssistantBusy(false);
    }
  }

  function wireAssistantControls() {
    elements.assistantModes.forEach((button) => {
      button.addEventListener("click", () => setAssistantMode(button.dataset.mode || "chat"));
    });

    if (elements.assistantSendBtn) {
      elements.assistantSendBtn.addEventListener("click", callAssistant);
    }
    if (elements.assistantClearBtn) {
      elements.assistantClearBtn.addEventListener("click", () => {
        if (elements.assistantInput) {
          elements.assistantInput.value = "";
        }
        if (elements.promptType) {
          elements.promptType.value = "";
        }
        if (elements.kimiImage) {
          elements.kimiImage.value = "";
        }
        if (elements.uploadInfo) {
          elements.uploadInfo.textContent = "No image selected yet.";
        }
        clearAssistantOutput();
        hideAssistantImage();
        setAssistantState("Idle", "muted");
        setAssistantHint((assistantModes[state.assistantMode] || assistantModes.chat).hint);
      });
    }
    if (elements.assistantCopyBtn) {
      elements.assistantCopyBtn.disabled = true;
      elements.assistantCopyBtn.addEventListener("click", async () => {
        try {
          await copyText(state.lastOutputText);
          showToast("Reply copied.");
        } catch (error) {
          showToast(error instanceof Error ? error.message : "Copy failed.", "error");
        }
      });
    }
    if (elements.assistantDownloadImageBtn) {
      elements.assistantDownloadImageBtn.disabled = true;
      elements.assistantDownloadImageBtn.addEventListener("click", () => {
        if (!state.lastImageDataUrl) {
          showToast("There is no image to save yet.", "error");
          return;
        }
        const link = document.createElement("a");
        link.href = state.lastImageDataUrl;
        link.download = `jo-ai-image-${Date.now()}.png`;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
      });
    }
    if (elements.assistantInput) {
      elements.assistantInput.addEventListener("keydown", (event) => {
        if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
          event.preventDefault();
          callAssistant();
        }
      });
    }
    if (elements.kimiImage) {
      elements.kimiImage.addEventListener("change", () => {
        const file = elements.kimiImage && elements.kimiImage.files ? elements.kimiImage.files[0] : null;
        if (!elements.uploadInfo) {
          return;
        }
        if (!file) {
          elements.uploadInfo.textContent = "No image selected yet.";
          return;
        }
        elements.uploadInfo.textContent = `${file.name} (${(file.size / (1024 * 1024)).toFixed(2)} MB)`;
      });
    }
  }

  function setCalcDisplay(value) {
    if (elements.calcDisplay) {
      elements.calcDisplay.value = value || "0";
    }
  }

  function renderCalculatorHistory() {
    if (!elements.calcHistory) {
      return;
    }
    elements.calcHistory.innerHTML = "";
    if (!state.calculatorHistory.length) {
      elements.calcHistory.innerHTML = '<p class="empty-copy">No calculations yet.</p>';
      return;
    }
    state.calculatorHistory.forEach((item) => {
      const entry = document.createElement("button");
      entry.type = "button";
      entry.className = "history-item";
      entry.innerHTML = `<strong>${escapeHtml(item.expression)}</strong><small>${escapeHtml(item.result)}</small>`;
      entry.addEventListener("click", () => setCalcDisplay(item.result));
      elements.calcHistory.appendChild(entry);
    });
  }

  function evaluateExpression(expression) {
    const sanitized = String(expression || "").replace(/\s+/g, "");
    if (!sanitized) {
      return "0";
    }
    if (!/^[0-9+\-*/().]+$/.test(sanitized)) {
      throw new Error("Only numbers and basic operators are supported.");
    }
    const value = Function(`"use strict"; return (${sanitized});`)();
    if (!Number.isFinite(value)) {
      throw new Error("That calculation is not valid.");
    }
    return String(Number(value.toFixed(10)));
  }

  function initCalculator() {
    state.calculatorHistory = readJson(STORAGE_KEYS.calcHistory, []);
    renderCalculatorHistory();
    setCalcDisplay("0");
    elements.calcKeys.forEach((button) => {
      button.addEventListener("click", () => {
        const action = button.dataset.action || "";
        const value = button.dataset.value || "";
        const current = elements.calcDisplay ? elements.calcDisplay.value : "0";
        if (action === "clear") {
          setCalcDisplay("0");
          return;
        }
        if (action === "backspace") {
          setCalcDisplay(current.length > 1 ? current.slice(0, -1) : "0");
          return;
        }
        if (action === "equals") {
          try {
            const result = evaluateExpression(current);
            state.calculatorHistory.unshift({ expression: current, result });
            state.calculatorHistory = state.calculatorHistory.slice(0, 6);
            writeJson(STORAGE_KEYS.calcHistory, state.calculatorHistory);
            renderCalculatorHistory();
            setCalcDisplay(result);
          } catch (error) {
            showToast(error instanceof Error ? error.message : "Calculation failed.", "error");
          }
          return;
        }
        const next = current === "0" && /[0-9.]/.test(value) ? value : `${current}${value}`;
        setCalcDisplay(next);
      });
    });
    if (elements.calcHistoryClearBtn) {
      elements.calcHistoryClearBtn.addEventListener("click", () => {
        state.calculatorHistory = [];
        writeJson(STORAGE_KEYS.calcHistory, state.calculatorHistory);
        renderCalculatorHistory();
      });
    }
  }

  function renderNotesList() {
    if (!elements.notesList) {
      return;
    }
    elements.notesList.innerHTML = "";
    if (elements.notesCount) {
      elements.notesCount.textContent = state.notes.length === 1 ? "1 saved" : `${state.notes.length} saved`;
    }
    if (!state.notes.length) {
      elements.notesList.innerHTML = '<p class="empty-copy">Start your first note.</p>';
      return;
    }
    [...state.notes]
      .sort((left, right) => new Date(right.updatedAt) - new Date(left.updatedAt))
      .forEach((note) => {
        const button = document.createElement("button");
        button.type = "button";
        button.className = `note-item${note.id === state.selectedNoteId ? " active" : ""}`;
        button.innerHTML = `
          <strong>${escapeHtml(note.title.trim() || "Untitled note")}</strong>
          <small>${escapeHtml((note.body.trim() || "No content yet.").slice(0, 80))}</small>
          <small>${escapeHtml(formatDateTime(note.updatedAt))}</small>
        `;
        button.addEventListener("click", () => {
          state.selectedNoteId = note.id;
          if (elements.noteTitle) {
            elements.noteTitle.value = note.title;
          }
          if (elements.noteBody) {
            elements.noteBody.value = note.body;
          }
          if (elements.notesMeta) {
            elements.notesMeta.textContent = `Last saved ${formatDateTime(note.updatedAt)}`;
          }
          renderNotesList();
        });
        elements.notesList.appendChild(button);
      });
  }

  function getSelectedNote() {
    return state.notes.find((note) => note.id === state.selectedNoteId) || null;
  }

  function saveCurrentNote(silent = false) {
    if (!elements.noteTitle || !elements.noteBody) {
      return;
    }
    const title = elements.noteTitle.value.trim();
    const body = elements.noteBody.value.trim();
    if (!title && !body) {
      if (!silent) {
        showToast("Add a title or some text first.", "error");
      }
      return;
    }
    const now = new Date().toISOString();
    const current = getSelectedNote();
    if (current) {
      current.title = title;
      current.body = body;
      current.updatedAt = now;
    } else {
      const note = { id: makeId("note"), title, body, updatedAt: now };
      state.notes.unshift(note);
      state.selectedNoteId = note.id;
    }
    writeJson(STORAGE_KEYS.notes, state.notes);
    writeJson(STORAGE_KEYS.noteDraft, { title, body, selectedNoteId: state.selectedNoteId });
    renderNotesList();
    if (elements.notesMeta) {
      elements.notesMeta.textContent = `Last saved ${formatDateTime(now)}`;
    }
    if (!silent) {
      showToast("Note saved.");
    }
  }

  function scheduleNoteSave() {
    clearTimeout(state.noteSaveTimer);
    state.noteSaveTimer = window.setTimeout(() => saveCurrentNote(true), 700);
  }

  function initNotes() {
    state.notes = readJson(STORAGE_KEYS.notes, []);
    const draft = readJson(STORAGE_KEYS.noteDraft, null);
    state.selectedNoteId = draft && draft.selectedNoteId ? draft.selectedNoteId : state.notes[0] ? state.notes[0].id : "";
    renderNotesList();
    const current = getSelectedNote();
    if (current) {
      if (elements.noteTitle) {
        elements.noteTitle.value = current.title;
      }
      if (elements.noteBody) {
        elements.noteBody.value = current.body;
      }
      if (elements.notesMeta) {
        elements.notesMeta.textContent = `Last saved ${formatDateTime(current.updatedAt)}`;
      }
    } else if (draft) {
      if (elements.noteTitle) {
        elements.noteTitle.value = draft.title || "";
      }
      if (elements.noteBody) {
        elements.noteBody.value = draft.body || "";
      }
    }
    if (elements.newNoteBtn) {
      elements.newNoteBtn.addEventListener("click", () => {
        state.selectedNoteId = "";
        if (elements.noteTitle) {
          elements.noteTitle.value = "";
        }
        if (elements.noteBody) {
          elements.noteBody.value = "";
        }
        if (elements.notesMeta) {
          elements.notesMeta.textContent = "Create a new note and save when you are ready.";
        }
        renderNotesList();
      });
    }
    if (elements.saveNoteBtn) {
      elements.saveNoteBtn.addEventListener("click", () => saveCurrentNote(false));
    }
    if (elements.deleteNoteBtn) {
      elements.deleteNoteBtn.addEventListener("click", () => {
        const currentNote = getSelectedNote();
        if (!currentNote) {
          showToast("Select a note to delete.", "error");
          return;
        }
        state.notes = state.notes.filter((note) => note.id !== currentNote.id);
        writeJson(STORAGE_KEYS.notes, state.notes);
        state.selectedNoteId = state.notes[0] ? state.notes[0].id : "";
        if (elements.noteTitle) {
          elements.noteTitle.value = "";
        }
        if (elements.noteBody) {
          elements.noteBody.value = "";
        }
        if (elements.notesMeta) {
          elements.notesMeta.textContent = "Note deleted. Start a new one anytime.";
        }
        renderNotesList();
        showToast("Note deleted.");
      });
    }
    [elements.noteTitle, elements.noteBody].forEach((input) => {
      if (!input) {
        return;
      }
      input.addEventListener("input", () => {
        writeJson(STORAGE_KEYS.noteDraft, {
          title: elements.noteTitle ? elements.noteTitle.value : "",
          body: elements.noteBody ? elements.noteBody.value : "",
          selectedNoteId: state.selectedNoteId
        });
        scheduleNoteSave();
      });
    });
  }

  function populateConverterUnits() {
    if (!elements.converterCategory || !elements.converterFrom || !elements.converterTo) {
      return;
    }
    const group = converterGroups[elements.converterCategory.value || "length"] || converterGroups.length;
    const unitEntries = Object.entries(group.units);
    [elements.converterFrom, elements.converterTo].forEach((select) => {
      select.innerHTML = "";
      unitEntries.forEach(([key, config]) => {
        const option = document.createElement("option");
        option.value = key;
        option.textContent = config.label;
        select.appendChild(option);
      });
    });
    if (unitEntries[1]) {
      elements.converterTo.value = unitEntries[1][0];
    }
  }

  function updateConverter() {
    if (!elements.converterCategory || !elements.converterValue || !elements.converterFrom || !elements.converterTo || !elements.converterResult) {
      return;
    }
    const rawValue = Number(elements.converterValue.value);
    if (!Number.isFinite(rawValue)) {
      elements.converterResult.textContent = "Enter a value to convert.";
      return;
    }
    const group = converterGroups[elements.converterCategory.value || "length"] || converterGroups.length;
    const fromUnit = group.units[elements.converterFrom.value];
    const toUnit = group.units[elements.converterTo.value];
    if (!fromUnit || !toUnit) {
      elements.converterResult.textContent = "Choose valid units.";
      return;
    }
    const baseValue = fromUnit.toBase(rawValue);
    const convertedValue = toUnit.fromBase(baseValue);
    elements.converterResult.textContent = `${formatNumber(rawValue)} ${fromUnit.label} = ${formatNumber(convertedValue)} ${toUnit.label}`;
  }

  function initConverter() {
    if (!elements.converterCategory) {
      return;
    }
    Object.entries(converterGroups).forEach(([key, config]) => {
      const option = document.createElement("option");
      option.value = key;
      option.textContent = config.label;
      elements.converterCategory.appendChild(option);
    });
    populateConverterUnits();
    updateConverter();
    elements.converterCategory.addEventListener("change", () => {
      populateConverterUnits();
      updateConverter();
    });
    elements.converterValue.addEventListener("input", updateConverter);
    elements.converterFrom.addEventListener("change", updateConverter);
    elements.converterTo.addEventListener("change", updateConverter);
    elements.converterSwapBtn.addEventListener("click", () => {
      const from = elements.converterFrom.value;
      elements.converterFrom.value = elements.converterTo.value;
      elements.converterTo.value = from;
      updateConverter();
    });
  }

  function toTitleCase(text) {
    return String(text || "")
      .toLowerCase()
      .replace(/\b([a-z])/g, (match) => match.toUpperCase());
  }

  function updateTextStats() {
    const text = elements.textLabInput ? elements.textLabInput.value : "";
    const words = text.trim() ? text.trim().split(/\s+/).length : 0;
    if (elements.textCharCount) {
      elements.textCharCount.textContent = String(text.length);
    }
    if (elements.textWordCount) {
      elements.textWordCount.textContent = String(words);
    }
    if (elements.textReadTime) {
      elements.textReadTime.textContent = `${words ? Math.max(1, Math.ceil(words / 200)) : 0} min`;
    }
    writeText(STORAGE_KEYS.textDraft, text);
  }

  function initTextUtility() {
    if (!elements.textLabInput) {
      return;
    }
    elements.textLabInput.value = readText(STORAGE_KEYS.textDraft, "");
    updateTextStats();
    elements.textLabInput.addEventListener("input", updateTextStats);
    elements.textUpperBtn.addEventListener("click", () => {
      elements.textLabInput.value = elements.textLabInput.value.toUpperCase();
      updateTextStats();
    });
    elements.textLowerBtn.addEventListener("click", () => {
      elements.textLabInput.value = elements.textLabInput.value.toLowerCase();
      updateTextStats();
    });
    elements.textTitleBtn.addEventListener("click", () => {
      elements.textLabInput.value = toTitleCase(elements.textLabInput.value);
      updateTextStats();
    });
    elements.textTrimBtn.addEventListener("click", () => {
      elements.textLabInput.value = elements.textLabInput.value.replace(/\s+/g, " ").trim();
      updateTextStats();
    });
    elements.textCopyBtn.addEventListener("click", async () => {
      try {
        await copyText(elements.textLabInput ? elements.textLabInput.value : "");
        showToast("Text copied.");
      } catch (error) {
        showToast(error instanceof Error ? error.message : "Copy failed.", "error");
      }
    });
    elements.textClearBtn.addEventListener("click", () => {
      elements.textLabInput.value = "";
      updateTextStats();
    });
  }

  function renderTttScore() {
    if (elements.tttScore) {
      elements.tttScore.textContent = `You ${state.ttt.score.player} | Bot ${state.ttt.score.bot} | Draw ${state.ttt.score.draw}`;
    }
  }

  function tttWinner(board) {
    const lines = [[0,1,2],[3,4,5],[6,7,8],[0,3,6],[1,4,7],[2,5,8],[0,4,8],[2,4,6]];
    for (const line of lines) {
      const [a, b, c] = line;
      if (board[a] && board[a] === board[b] && board[a] === board[c]) {
        return { mark: board[a], line };
      }
    }
    return null;
  }

  function chooseBotMove(board) {
    const lines = [[0,1,2],[3,4,5],[6,7,8],[0,3,6],[1,4,7],[2,5,8],[0,4,8],[2,4,6]];
    const findLineMove = (mark) => {
      for (const [a, b, c] of lines) {
        const values = [board[a], board[b], board[c]];
        const emptyIndex = values.indexOf("");
        if (emptyIndex !== -1 && values.filter((value) => value === mark).length === 2) {
          return [a, b, c][emptyIndex];
        }
      }
      return -1;
    };
    const winningMove = findLineMove("O");
    if (winningMove >= 0) {
      return winningMove;
    }
    const blockMove = findLineMove("X");
    if (blockMove >= 0) {
      return blockMove;
    }
    if (!board[4]) {
      return 4;
    }
    const corners = [0, 2, 6, 8].filter((index) => !board[index]);
    if (corners.length) {
      return corners[Math.floor(Math.random() * corners.length)];
    }
    const sides = [1, 3, 5, 7].filter((index) => !board[index]);
    return sides[Math.floor(Math.random() * sides.length)];
  }

  function finishTttRound(text, type) {
    state.ttt.finished = true;
    state.ttt.locked = false;
    if (elements.tttStatus) {
      elements.tttStatus.textContent = text;
    }
    if (type === "player") {
      state.ttt.score.player += 1;
    } else if (type === "bot") {
      state.ttt.score.bot += 1;
    } else {
      state.ttt.score.draw += 1;
    }
    writeJson(STORAGE_KEYS.tttScore, state.ttt.score);
    renderTttScore();
  }

  function renderTttBoard(line = []) {
    if (!elements.tttBoard) {
      return;
    }
    elements.tttBoard.innerHTML = "";
    state.ttt.board.forEach((mark, index) => {
      const cell = document.createElement("button");
      cell.type = "button";
      cell.className = `ttt-cell${line.includes(index) ? " win" : ""}`;
      cell.textContent = mark;
      cell.disabled = Boolean(mark) || state.ttt.finished || state.ttt.locked;
      cell.addEventListener("click", () => {
        if (state.ttt.finished || state.ttt.locked || state.ttt.board[index]) {
          return;
        }
        state.ttt.board[index] = "X";
        let result = tttWinner(state.ttt.board);
        renderTttBoard(result ? result.line : []);
        if (result) {
          finishTttRound("You won this round.", "player");
          return;
        }
        if (state.ttt.board.every(Boolean)) {
          finishTttRound("Draw round. Try again.", "draw");
          return;
        }
        state.ttt.locked = true;
        if (elements.tttStatus) {
          elements.tttStatus.textContent = "Bot is choosing a move...";
        }
        window.setTimeout(() => {
          const botIndex = chooseBotMove(state.ttt.board);
          if (botIndex >= 0 && !state.ttt.board[botIndex]) {
            state.ttt.board[botIndex] = "O";
          }
          result = tttWinner(state.ttt.board);
          renderTttBoard(result ? result.line : []);
          if (result) {
            finishTttRound("Bot won this round.", "bot");
            return;
          }
          if (state.ttt.board.every(Boolean)) {
            finishTttRound("Draw round. Try again.", "draw");
            return;
          }
          state.ttt.locked = false;
          if (elements.tttStatus) {
            elements.tttStatus.textContent = "Your move starts the round.";
          }
        }, 220);
      });
      elements.tttBoard.appendChild(cell);
    });
  }

  function initTicTacToe() {
    renderTttScore();
    const reset = () => {
      state.ttt.board = Array(9).fill("");
      state.ttt.finished = false;
      state.ttt.locked = false;
      if (elements.tttStatus) {
        elements.tttStatus.textContent = "Your move starts the round.";
      }
      renderTttBoard();
    };
    reset();
    if (elements.tttResetBtn) {
      elements.tttResetBtn.addEventListener("click", reset);
    }
  }

  function renderMemoryMeta() {
    if (elements.memoryMoves) {
      elements.memoryMoves.textContent = `Moves: ${state.memory.moves}`;
    }
    if (elements.memoryBest) {
      elements.memoryBest.textContent = typeof state.memory.best === "number" ? `Best: ${state.memory.best} moves` : "Best: --";
    }
  }

  function buildMemoryDeck() {
    return shuffle(memorySymbols.flatMap((symbol) => [
      { id: makeId("memory"), symbol, revealed: false, matched: false },
      { id: makeId("memory"), symbol, revealed: false, matched: false }
    ]));
  }

  function renderMemoryBoard() {
    if (!elements.memoryBoard) {
      return;
    }
    elements.memoryBoard.innerHTML = "";
    state.memory.cards.forEach((card) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `memory-card${card.revealed ? " revealed" : ""}${card.matched ? " matched" : ""}`;
      button.disabled = card.matched || state.memory.locked;
      const inner = document.createElement("div");
      inner.className = "memory-card-inner";
      inner.textContent = card.revealed || card.matched ? card.symbol : "?";
      button.appendChild(inner);
      button.addEventListener("click", () => revealMemoryCard(card.id));
      elements.memoryBoard.appendChild(button);
    });
  }

  function revealMemoryCard(cardId) {
    if (state.memory.locked) {
      return;
    }
    const card = state.memory.cards.find((item) => item.id === cardId);
    if (!card || card.matched || card.revealed) {
      return;
    }
    card.revealed = true;
    if (!state.memory.firstId) {
      state.memory.firstId = card.id;
      renderMemoryBoard();
      return;
    }
    state.memory.secondId = card.id;
    state.memory.moves += 1;
    state.memory.locked = true;
    renderMemoryMeta();
    renderMemoryBoard();
    const first = state.memory.cards.find((item) => item.id === state.memory.firstId);
    const second = state.memory.cards.find((item) => item.id === state.memory.secondId);
    if (!first || !second) {
      state.memory.locked = false;
      return;
    }
    if (first.symbol === second.symbol) {
      first.matched = true;
      second.matched = true;
      state.memory.firstId = "";
      state.memory.secondId = "";
      state.memory.locked = false;
      state.memory.matchedPairs += 1;
      if (elements.memoryStatus) {
        elements.memoryStatus.textContent = state.memory.matchedPairs === memorySymbols.length
          ? `Completed in ${state.memory.moves} moves.`
          : "Match found. Keep going.";
      }
      if (state.memory.matchedPairs === memorySymbols.length && (typeof state.memory.best !== "number" || state.memory.moves < state.memory.best)) {
        state.memory.best = state.memory.moves;
        writeJson(STORAGE_KEYS.memoryBest, state.memory.best);
        renderMemoryMeta();
      }
      renderMemoryBoard();
      return;
    }
    if (elements.memoryStatus) {
      elements.memoryStatus.textContent = "Not a match. Try again.";
    }
    window.setTimeout(() => {
      first.revealed = false;
      second.revealed = false;
      state.memory.firstId = "";
      state.memory.secondId = "";
      state.memory.locked = false;
      renderMemoryBoard();
    }, 650);
  }

  function initMemoryGame() {
    const reset = () => {
      state.memory.cards = buildMemoryDeck();
      state.memory.firstId = "";
      state.memory.secondId = "";
      state.memory.moves = 0;
      state.memory.matchedPairs = 0;
      state.memory.locked = false;
      if (elements.memoryStatus) {
        elements.memoryStatus.textContent = "Find all matching pairs.";
      }
      renderMemoryMeta();
      renderMemoryBoard();
    };
    reset();
    if (elements.memoryResetBtn) {
      elements.memoryResetBtn.addEventListener("click", reset);
    }
  }

  function renderRpsScore() {
    if (elements.rpsScore) {
      elements.rpsScore.textContent = `You ${state.rpsScore.player} | Bot ${state.rpsScore.bot} | Draw ${state.rpsScore.draw}`;
    }
  }

  function initRps() {
    renderRpsScore();
    if (elements.rpsResetBtn) {
      elements.rpsResetBtn.addEventListener("click", () => {
        state.rpsScore = { player: 0, bot: 0, draw: 0 };
        writeJson(STORAGE_KEYS.rpsScore, state.rpsScore);
        renderRpsScore();
        if (elements.rpsResult) {
          elements.rpsResult.textContent = "Choose one option to start.";
        }
      });
    }
    elements.rpsChoices.forEach((button) => {
      button.addEventListener("click", () => {
        const choice = button.dataset.choice || "rock";
        const options = ["rock", "paper", "scissors"];
        const botChoice = options[Math.floor(Math.random() * options.length)];
        let result = `You chose ${choice}. Bot chose ${botChoice}. `;
        if (choice === botChoice) {
          state.rpsScore.draw += 1;
          result += "Round draw.";
        } else if (
          (choice === "rock" && botChoice === "scissors") ||
          (choice === "paper" && botChoice === "rock") ||
          (choice === "scissors" && botChoice === "paper")
        ) {
          state.rpsScore.player += 1;
          result += "You win.";
        } else {
          state.rpsScore.bot += 1;
          result += "Bot wins.";
        }
        writeJson(STORAGE_KEYS.rpsScore, state.rpsScore);
        renderRpsScore();
        if (elements.rpsResult) {
          elements.rpsResult.textContent = result;
        }
      });
    });
  }

  function normalizedQuizBank() {
    return QUIZ_BANK.filter((question) => (
      question &&
      typeof question.id === "string" &&
      typeof question.category === "string" &&
      typeof question.question === "string" &&
      Array.isArray(question.choices) &&
      question.choices.length >= 2 &&
      Number.isInteger(question.answer) &&
      question.answer >= 0 &&
      question.answer < question.choices.length
    ));
  }

  function categoryLabel(category) {
    const labels = {
      all: "All topics",
      general: "General knowledge",
      science: "Science",
      math: "Math",
      technology: "Technology",
      english: "English"
    };
    return labels[category] || category;
  }

  function renderQuizStats() {
    const bank = normalizedQuizBank();
    if (elements.questionBankCount) {
      elements.questionBankCount.textContent = `${bank.length} questions`;
    }
    if (elements.quizTopicCount) {
      elements.quizTopicCount.textContent = `${new Set(bank.map((question) => question.category)).size} topics`;
    }
    if (elements.quizBestScore) {
      elements.quizBestScore.textContent = state.quiz.best && Number.isFinite(state.quiz.best.percent) ? `${state.quiz.best.percent}%` : "0%";
    }
    if (elements.quizLastScore) {
      elements.quizLastScore.textContent = state.quiz.last && Number.isFinite(state.quiz.last.score) && Number.isFinite(state.quiz.last.total)
        ? `${state.quiz.last.score}/${state.quiz.last.total}`
        : "Not started";
    }
  }

  function setQuizProgress() {
    const session = state.quiz.session;
    if (!session) {
      if (elements.quizProgressBar) {
        elements.quizProgressBar.style.width = "0%";
      }
      if (elements.quizProgressLabel) {
        elements.quizProgressLabel.textContent = "Choose a topic and start.";
      }
      if (elements.quizScoreBadge) {
        elements.quizScoreBadge.textContent = "Score: 0";
        elements.quizScoreBadge.classList.remove("success", "error");
        elements.quizScoreBadge.classList.add("muted");
      }
      return;
    }
    const progressPercent = session.total ? ((session.index + (state.quiz.answered ? 1 : 0)) / session.total) * 100 : 0;
    if (elements.quizProgressBar) {
      elements.quizProgressBar.style.width = `${Math.min(progressPercent, 100)}%`;
    }
    if (elements.quizProgressLabel) {
      elements.quizProgressLabel.textContent = `Question ${session.index + 1} of ${session.total} in ${categoryLabel(session.topic)}`;
    }
    if (elements.quizScoreBadge) {
      elements.quizScoreBadge.textContent = `Score: ${session.score}/${session.total}`;
    }
  }

  function renderQuizFeedback(title, body) {
    if (!elements.quizFeedback) {
      return;
    }
    elements.quizFeedback.hidden = false;
    elements.quizFeedback.innerHTML = `<strong>${escapeHtml(title)}</strong><p>${escapeHtml(body)}</p>`;
  }

  function clearQuizFeedback() {
    if (!elements.quizFeedback) {
      return;
    }
    elements.quizFeedback.hidden = true;
    elements.quizFeedback.innerHTML = "";
  }

  function populateQuizCategoryOptions() {
    if (!elements.quizCategory) {
      return;
    }
    elements.quizCategory.innerHTML = "";
    const allOption = document.createElement("option");
    allOption.value = "all";
    allOption.textContent = categoryLabel("all");
    elements.quizCategory.appendChild(allOption);
    [...new Set(normalizedQuizBank().map((question) => question.category))].sort().forEach((category) => {
      const option = document.createElement("option");
      option.value = category;
      option.textContent = categoryLabel(category);
      elements.quizCategory.appendChild(option);
    });
  }

  function buildSessionQuestion(question) {
    const shuffledChoices = shuffle(question.choices.map((choice, index) => ({ text: choice, isCorrect: index === question.answer })));
    return {
      ...question,
      choices: shuffledChoices.map((item) => item.text),
      answer: shuffledChoices.findIndex((item) => item.isCorrect)
    };
  }

  function renderQuizQuestion() {
    if (!elements.quizQuestionWrap) {
      return;
    }
    clearQuizFeedback();
    setQuizProgress();
    const session = state.quiz.session;
    if (!session) {
      elements.quizQuestionWrap.innerHTML = '<p class="empty-copy">Pick a topic and start a quiz session.</p>';
      elements.quizSubmitBtn.disabled = true;
      elements.quizNextBtn.disabled = true;
      return;
    }
    const question = session.questions[session.index];
    if (!question) {
      elements.quizQuestionWrap.innerHTML = '<p class="empty-copy">No question found for this session.</p>';
      elements.quizSubmitBtn.disabled = true;
      elements.quizNextBtn.disabled = true;
      return;
    }
    elements.quizQuestionWrap.innerHTML = "";
    const pill = document.createElement("span");
    pill.className = "pill";
    pill.textContent = categoryLabel(question.category);
    const text = document.createElement("p");
    text.className = "question-text";
    text.textContent = question.question;
    const options = document.createElement("div");
    options.className = "option-list";
    question.choices.forEach((choice, index) => {
      const label = document.createElement("label");
      label.className = "option-card";
      const input = document.createElement("input");
      input.type = "radio";
      input.name = "quizOption";
      input.value = String(index);
      const copy = document.createElement("span");
      copy.textContent = choice;
      label.appendChild(input);
      label.appendChild(copy);
      options.appendChild(label);
    });
    elements.quizQuestionWrap.appendChild(pill);
    elements.quizQuestionWrap.appendChild(text);
    elements.quizQuestionWrap.appendChild(options);
    state.quiz.answered = false;
    elements.quizSubmitBtn.disabled = false;
    elements.quizNextBtn.disabled = true;
  }

  function finishQuizSession() {
    const session = state.quiz.session;
    if (!session || !elements.quizQuestionWrap) {
      return;
    }
    const percent = Math.round((session.score / session.total) * 100);
    state.quiz.last = { score: session.score, total: session.total, percent };
    writeJson(STORAGE_KEYS.quizLast, state.quiz.last);
    if (!state.quiz.best || percent > state.quiz.best.percent) {
      state.quiz.best = { score: session.score, total: session.total, percent };
      writeJson(STORAGE_KEYS.quizBest, state.quiz.best);
    }
    elements.quizQuestionWrap.innerHTML = `
      <p class="card-eyebrow">Session complete</p>
      <h3>${escapeHtml(`${session.score}/${session.total} correct`)}</h3>
      <p class="support-copy">That run finished at ${percent}%. Start another session for a fresh random set.</p>
    `;
    renderQuizFeedback(
      "Quiz complete",
      percent >= 80 ? "Strong result. Try a different topic or a longer session next." : "Nice work. Restart for a new random session and improve your score."
    );
    elements.quizSubmitBtn.disabled = true;
    elements.quizNextBtn.disabled = true;
    if (elements.quizProgressBar) {
      elements.quizProgressBar.style.width = "100%";
    }
    if (elements.quizProgressLabel) {
      elements.quizProgressLabel.textContent = `Completed ${categoryLabel(session.topic)} quiz`;
    }
    if (elements.quizScoreBadge) {
      elements.quizScoreBadge.textContent = `Score: ${session.score}/${session.total}`;
      elements.quizScoreBadge.classList.remove("muted");
      elements.quizScoreBadge.classList.add("success");
    }
    renderQuizStats();
  }

  function submitQuizAnswer() {
    const session = state.quiz.session;
    if (!session || state.quiz.answered) {
      return;
    }
    const selected = document.querySelector('input[name="quizOption"]:checked');
    if (!selected) {
      showToast("Choose an answer first.", "error");
      return;
    }
    const selectedIndex = Number(selected.value);
    const question = session.questions[session.index];
    document.querySelectorAll(".option-card").forEach((label, index) => {
      const input = label.querySelector("input");
      if (input) {
        input.disabled = true;
      }
      if (index === question.answer) {
        label.classList.add("correct");
      }
      if (index === selectedIndex && selectedIndex !== question.answer) {
        label.classList.add("wrong");
      }
    });
    state.quiz.answered = true;
    if (selectedIndex === question.answer) {
      session.score += 1;
      renderQuizFeedback("Correct", question.fact || "Nice work.");
      showToast("Correct answer.");
    } else {
      renderQuizFeedback("Not quite", `${question.fact || "Review the topic and try again."} Correct answer: ${question.choices[question.answer]}`);
      showToast("That answer was not correct.", "error");
    }
    setQuizProgress();
    elements.quizSubmitBtn.disabled = true;
    if (session.index >= session.total - 1) {
      finishQuizSession();
      return;
    }
    elements.quizNextBtn.disabled = false;
  }

  function nextQuizQuestion() {
    if (!state.quiz.session || !state.quiz.answered) {
      return;
    }
    state.quiz.session.index += 1;
    renderQuizQuestion();
  }

  function startQuizSession() {
    const bank = normalizedQuizBank();
    const topic = elements.quizCategory ? elements.quizCategory.value : "all";
    const requested = Math.min(Number(elements.quizCount ? elements.quizCount.value : 10) || 10, 50);
    const pool = topic === "all" ? bank : bank.filter((question) => question.category === topic);
    if (!pool.length) {
      showToast("No questions are available for that topic.", "error");
      return;
    }
    const total = Math.min(requested, pool.length, 50);
    state.quiz.session = {
      topic,
      total,
      score: 0,
      index: 0,
      questions: shuffle(pool).slice(0, total).map(buildSessionQuestion)
    };
    if (elements.quizSetupHint) {
      elements.quizSetupHint.textContent = total < requested
        ? `This topic currently has ${pool.length} stored questions, so this session will use ${total}.`
        : "Questions are randomized each session, with a maximum of 50 questions in one run.";
    }
    renderQuizQuestion();
    showToast("New quiz session started.");
  }

  function initQuiz() {
    populateQuizCategoryOptions();
    renderQuizStats();
    setQuizProgress();
    if (elements.quizQuestionWrap) {
      elements.quizQuestionWrap.innerHTML = '<p class="empty-copy">Pick a topic and start a quiz session.</p>';
    }
    if (elements.quizStartBtn) {
      elements.quizStartBtn.addEventListener("click", startQuizSession);
    }
    if (elements.quizRestartBtn) {
      elements.quizRestartBtn.addEventListener("click", startQuizSession);
    }
    if (elements.quizSubmitBtn) {
      elements.quizSubmitBtn.addEventListener("click", submitQuizAnswer);
    }
    if (elements.quizNextBtn) {
      elements.quizNextBtn.addEventListener("click", nextQuizQuestion);
    }
  }

  function buildFeedbackTemplate() {
    return [
      "JO AI mini app feedback",
      `Date: ${new Date().toLocaleString()}`,
      `Section: ${state.activeSection}`,
      `Assistant mode: ${state.assistantMode}`,
      "",
      "What happened:",
      "",
      "What did you expect instead:",
      ""
    ].join("\n");
  }

  function initSupport() {
    if (elements.feedbackBtn) {
      elements.feedbackBtn.addEventListener("click", async () => {
        try {
          await copyText(buildFeedbackTemplate());
          showToast("Feedback note copied.");
        } catch (error) {
          showToast(error instanceof Error ? error.message : "Copy failed.", "error");
        }
      });
    }
  }

  async function registerOfflineCache() {
    if (!("serviceWorker" in navigator) || !window.location.protocol.startsWith("http")) {
      return;
    }
    try {
      await navigator.serviceWorker.register("service-worker.js");
    } catch (_error) {
      // Ignore offline cache registration failures.
    }
  }

  function wireOnlineState() {
    window.addEventListener("online", async () => {
      updateConnectionBadge();
      await resolveApiBase();
      setAssistantState("Ready", state.assistantOnline ? "success" : "muted");
    });
    window.addEventListener("offline", () => {
      updateConnectionBadge();
      setAssistantState("Offline", "error");
    });
  }

  async function boot() {
    setVersionBadge();
    initTelegram();
    initWelcomeOverlay();
    wireSectionTabs();
    updateConnectionBadge();
    if (elements.storageBadge) {
      elements.storageBadge.textContent = "Saving notes and scores on this device";
    }
    clearAssistantOutput();
    hideAssistantImage();
    setAssistantMode("chat");
    wireAssistantControls();
    initCalculator();
    initNotes();
    initConverter();
    initTextUtility();
    initTicTacToe();
    initMemoryGame();
    initRps();
    initQuiz();
    initSupport();
    wireOnlineState();
    await registerOfflineCache();
    await resolveApiBase();
    setAssistantState("Ready", state.assistantOnline ? "success" : "muted");
  }

  boot();
})();
