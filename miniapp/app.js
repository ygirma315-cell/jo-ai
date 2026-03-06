
(() => {
  "use strict";

  const tg = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;
  const API_BASE_STORAGE_KEY = "jo_api_base";
  const FRONTEND_VERSION = "v1.0.3";

  const elements = {
    welcomeOverlay: document.getElementById("welcomeOverlay"),
    welcomeMessage: document.getElementById("welcomeMessage"),
    openAppBtn: document.getElementById("openAppBtn"),
    status: document.getElementById("status"),
    userInfo: document.getElementById("userInfo"),
    modes: Array.from(document.querySelectorAll(".mode")),
    inputLabel: document.getElementById("inputLabel"),
    aiInput: document.getElementById("aiInput"),
    promptTypeWrap: document.getElementById("promptTypeWrap"),
    promptType: document.getElementById("promptType"),
    imageTypeWrap: document.getElementById("imageTypeWrap"),
    imageType: document.getElementById("imageType"),
    kimiImageWrap: document.getElementById("kimiImageWrap"),
    kimiImage: document.getElementById("kimiImage"),
    uploadInfo: document.getElementById("uploadInfo"),
    sendBtn: document.getElementById("sendBtn"),
    clearBtn: document.getElementById("clearBtn"),
    copyBtn: document.getElementById("copyBtn"),
    downloadImageBtn: document.getElementById("downloadImageBtn"),
    loadingHint: document.getElementById("loadingHint"),
    apiState: document.getElementById("apiState"),
    aiOutput: document.getElementById("aiOutput"),
    imageWrap: document.getElementById("imageWrap"),
    imagePreview: document.getElementById("imagePreview"),
    imageCaption: document.getElementById("imageCaption"),
    versionBadge: document.getElementById("versionBadge"),
    toast: document.getElementById("toast"),
    contactBtn: document.getElementById("contactBtn"),
    reportBtn: document.getElementById("reportBtn"),
  };

  const state = {
    activeMode: "chat",
    apiBase: "",
    loadingTimer: null,
    loadingIndex: 0,
    isBusy: false,
    lastOutputText: "",
    lastImageDataUrl: "",
    toastTimer: null,
  };

  const modeUi = {
    chat: {
      label: "Message",
      placeholder: "Ask anything. Example: Give me a clear explanation of recursion.",
    },
    code: {
      label: "Code request",
      placeholder: "Describe the code you need and include language/framework.",
    },
    deepseek: {
      label: "DeepSeek request",
      placeholder: "Ask for a sharper analytical answer with concise reasoning and a clear final result.",
    },
    research: {
      label: "Research question",
      placeholder: "Ask for a detailed explanation with risks, tradeoffs, and next steps.",
    },
    prompt: {
      label: "Prompt details",
      placeholder: "Explain your goal, audience, tone, and output format.",
    },
    image: {
      label: "Image description",
      placeholder: "Describe subject, style, lighting, mood, and composition.",
    },
    kimi: {
      label: "Describe task",
      placeholder: "Optional instruction. Example: Summarize what this image contains.",
    },
  };

  const loadingMessages = [
    "Generating response...",
    "Thinking deeply...",
    "Processing your request...",
    "Preparing the best output...",
    "Almost done...",
  ];

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
    const result = [];
    for (const value of values) {
      if (!value || seen.has(value)) {
        continue;
      }
      seen.add(value);
      result.push(value);
    }
    return result;
  }

  function normalizeBase(rawBase) {
    const value = String(rawBase || "").trim();
    if (!/^https?:\/\//i.test(value)) {
      return "";
    }
    return value.replace(/\/+$/, "");
  }

  function normalizeSupportUrl(raw) {
    const value = String(raw || "").trim();
    if (!value) {
      return "";
    }
    if (/^https?:\/\//i.test(value)) {
      return value;
    }
    if (/^t\.me\//i.test(value)) {
      return `https://${value}`;
    }
    return "";
  }

  function setStatus(text) {
    if (elements.status) {
      elements.status.textContent = text;
    }
  }

  function setUserInfo(text) {
    if (elements.userInfo) {
      elements.userInfo.textContent = text;
    }
  }

  function setVersionBadge(version) {
    if (!elements.versionBadge) {
      return;
    }
    const safeVersion = String(version || "").trim();
    if (!safeVersion) {
      elements.versionBadge.textContent = `Version: ${FRONTEND_VERSION}`;
      return;
    }
    elements.versionBadge.textContent = `Version: ${safeVersion}`;
  }

  function extractRuntimeInfo(data) {
    const version = data && typeof data.version === "string" ? data.version.trim() : "";
    const models = {};
    const deploy = {};
    const service = {};
    const rawModels = data && typeof data.models === "object" && data.models ? data.models : {};
    const rawDeploy = data && typeof data.deploy === "object" && data.deploy ? data.deploy : {};
    const rawService = data && typeof data.service === "object" && data.service ? data.service : {};

    for (const [key, value] of Object.entries(rawModels)) {
      if (typeof value === "string" && value.trim()) {
        models[key] = value.trim();
      }
    }

    for (const [key, value] of Object.entries(rawDeploy)) {
      if (typeof value === "string" && value.trim()) {
        deploy[key] = value.trim();
      }
    }

    for (const [key, value] of Object.entries(rawService)) {
      if (typeof value === "string" && value.trim()) {
        service[key] = value.trim();
      }
    }

    return { version, models, deploy, service };
  }

  function setApiState(text, variant = "muted") {
    if (!elements.apiState) {
      return;
    }
    elements.apiState.textContent = text;
    elements.apiState.classList.remove("muted", "success", "error");
    elements.apiState.classList.add(variant);
  }

  function setLoadingHint(text) {
    if (elements.loadingHint) {
      elements.loadingHint.textContent = text;
    }
  }

  function setBusy(busy) {
    state.isBusy = busy;
    if (elements.sendBtn) {
      elements.sendBtn.disabled = busy;
    }
    if (elements.clearBtn) {
      elements.clearBtn.disabled = busy;
    }
    if (elements.copyBtn) {
      elements.copyBtn.disabled = busy || !state.lastOutputText;
    }
    if (elements.downloadImageBtn) {
      elements.downloadImageBtn.disabled = busy || !state.lastImageDataUrl;
    }

    if (busy) {
      state.loadingIndex = 0;
      setApiState("processing", "muted");
      setLoadingHint(loadingMessages[state.loadingIndex]);
      clearInterval(state.loadingTimer);
      state.loadingTimer = setInterval(() => {
        state.loadingIndex = (state.loadingIndex + 1) % loadingMessages.length;
        setLoadingHint(loadingMessages[state.loadingIndex]);
      }, 900);
      return;
    }

    clearInterval(state.loadingTimer);
    state.loadingTimer = null;
    setLoadingHint("Ready when you are.");
  }

  function showToast(text, variant = "success", durationMs = 2600) {
    if (!elements.toast) {
      return;
    }
    elements.toast.hidden = false;
    elements.toast.textContent = text;
    elements.toast.classList.remove("success", "error");
    elements.toast.classList.add(variant === "error" ? "error" : "success");
    clearTimeout(state.toastTimer);
    state.toastTimer = setTimeout(() => {
      if (elements.toast) {
        elements.toast.hidden = true;
      }
    }, durationMs);
  }

  function escapeHtml(input) {
    return String(input || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/\"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  async function copyText(text) {
    const value = String(text || "");
    if (!value.trim()) {
      throw new Error("Nothing to copy.");
    }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(value);
      return;
    }

    const buffer = document.createElement("textarea");
    buffer.value = value;
    buffer.setAttribute("readonly", "");
    buffer.style.position = "fixed";
    buffer.style.left = "-9999px";
    document.body.appendChild(buffer);
    buffer.select();
    const ok = document.execCommand("copy");
    document.body.removeChild(buffer);
    if (!ok) {
      throw new Error("Clipboard write failed.");
    }
  }

  function clearOutput() {
    state.lastOutputText = "";
    if (elements.aiOutput) {
      elements.aiOutput.innerHTML = '<p class="placeholder">Your AI response will appear here.</p>';
    }
    if (elements.copyBtn) {
      elements.copyBtn.disabled = true;
    }
  }

  function hideImage() {
    state.lastImageDataUrl = "";
    if (elements.imagePreview) {
      elements.imagePreview.removeAttribute("src");
    }
    if (elements.imageWrap) {
      elements.imageWrap.hidden = true;
    }
    if (elements.downloadImageBtn) {
      elements.downloadImageBtn.disabled = true;
    }
  }

  function normalizeImageUrl(rawImage) {
    const imageValue = String(rawImage || "").trim();
    if (!imageValue) {
      return "";
    }
    if (imageValue.startsWith("data:image")) {
      return imageValue;
    }
    const compact = imageValue.replace(/\s+/g, "");
    return `data:image/png;base64,${compact}`;
  }

  function showImage(base64Payload) {
    const dataUrl = normalizeImageUrl(base64Payload);
    if (!dataUrl || !elements.imagePreview || !elements.imageWrap) {
      hideImage();
      return;
    }

    elements.imagePreview.onload = () => {
      if (elements.imageCaption) {
        elements.imageCaption.textContent = "Generated image preview";
      }
      if (elements.downloadImageBtn) {
        elements.downloadImageBtn.disabled = false;
      }
      state.lastImageDataUrl = dataUrl;
      elements.imageWrap.hidden = false;
    };
    elements.imagePreview.onerror = () => {
      hideImage();
      showToast("Image could not be rendered. Please try again.", "error");
    };
    elements.imagePreview.src = dataUrl;
  }

  function renderTextBlock(text) {
    const fragment = document.createDocumentFragment();
    const lines = text.split(/\r?\n/);
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
        const heading = document.createElement(
          headingMatch[1].length === 1 ? "h3" : headingMatch[1].length === 2 ? "h4" : "h5"
        );
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

  function buildCodeBlock(rawSegment) {
    const normalized = rawSegment.replace(/\r/g, "");
    const lines = normalized.split("\n");
    let language = "code";
    let codeBody = normalized;

    if (lines.length > 1 && /^[A-Za-z0-9_+#.-]{1,20}$/.test(lines[0].trim())) {
      language = lines[0].trim().toLowerCase();
      codeBody = lines.slice(1).join("\n");
    }

    if (!codeBody.trim()) {
      codeBody = normalized;
    }

    const wrapper = document.createElement("section");
    wrapper.className = "code-block";

    const head = document.createElement("header");
    head.className = "code-head";

    const lang = document.createElement("span");
    lang.className = "code-lang";
    lang.textContent = language;

    const copy = document.createElement("button");
    copy.className = "code-copy";
    copy.type = "button";
    copy.textContent = "Copy code";
    copy.addEventListener("click", async () => {
      try {
        await copyText(codeBody);
        showToast("Code copied.");
      } catch (error) {
        showToast(error instanceof Error ? error.message : "Failed to copy code.", "error");
      }
    });

    head.appendChild(lang);
    head.appendChild(copy);

    const pre = document.createElement("pre");
    const code = document.createElement("code");
    code.textContent = codeBody;
    pre.appendChild(code);

    wrapper.appendChild(head);
    wrapper.appendChild(pre);
    return wrapper;
  }
  function renderOutput(text) {
    const raw = String(text || "").trim();
    if (!elements.aiOutput) {
      return;
    }

    elements.aiOutput.innerHTML = "";
    if (!raw) {
      clearOutput();
      return;
    }

    state.lastOutputText = raw;
    if (elements.copyBtn) {
      elements.copyBtn.disabled = false;
    }

    const segments = raw.split(/```/);
    for (let index = 0; index < segments.length; index += 1) {
      const segment = segments[index];
      if (!segment.trim()) {
        continue;
      }
      if (index % 2 === 1) {
        elements.aiOutput.appendChild(buildCodeBlock(segment));
      } else {
        elements.aiOutput.appendChild(renderTextBlock(segment));
      }
    }
  }

  async function fetchJsonWithTimeout(url, options, timeoutMs = 60000) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await fetch(url, { ...options, signal: controller.signal });
      const raw = await response.text();
      let data = {};
      if (raw) {
        try {
          data = JSON.parse(raw);
        } catch (_error) {
          throw new Error("The assistant returned an unexpected response. Please try again.");
        }
      }
      return { response, data };
    } catch (error) {
      if (error && error.name === "AbortError") {
        throw new Error(`Request timed out after ${Math.floor(timeoutMs / 1000)}s.`);
      }
      throw error;
    } finally {
      clearTimeout(timer);
    }
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
    const storedBase = normalizeBase(window.localStorage.getItem(API_BASE_STORAGE_KEY));
    const sameOriginBase = shouldTrySameOriginApi() ? normalizeBase(window.location.origin) : "";
    const localhost8000 = normalizeBase("http://127.0.0.1:8000");
    const localhostAlt = normalizeBase("http://localhost:8000");

    if (queryBase) {
      window.localStorage.setItem(API_BASE_STORAGE_KEY, queryBase);
    }

    return unique([
      queryBase,
      explicitBase,
      storedBase,
      sameOriginBase,
      isLocalHost() ? localhost8000 : "",
      isLocalHost() ? localhostAlt : "",
    ]);
  }

  async function isApiHealthy(base) {
    const checks = ["/api/health", "/health"];
    for (const path of checks) {
      try {
        const { response, data } = await fetchJsonWithTimeout(`${base}${path}`, { method: "GET" }, 5500);
        const info = extractRuntimeInfo(data);
        if (response.ok && data && (data.ok === true || data.status === "ok")) {
          return { ok: true, version: info.version, models: info.models };
        }
      } catch (_error) {
        // try next path
      }
    }
    return { ok: false, version: "", models: {} };
  }

  async function resolveApiBase() {
    setStatus("Starting assistant...");
    const candidates = buildApiBaseCandidates();
    if (!candidates.length) {
      state.apiBase = "";
      setStatus("Assistant unavailable");
      return;
    }

    for (const candidate of candidates) {
      const health = await isApiHealthy(candidate);
      if (health.ok) {
        state.apiBase = candidate;
        window.localStorage.setItem(API_BASE_STORAGE_KEY, candidate);
        setStatus(tg ? "Assistant ready" : "Browser mode ready");
        return;
      }
    }

    state.apiBase = candidates[0];
    setStatus("Assistant connection not verified");
  }

  function endpointAttempts(mode, payload) {
    const basePayload = { ...payload };

    if (mode === "chat") {
      return [
        { path: "/api/chat", payload: basePayload },
        { path: "/chat", payload: basePayload },
      ];
    }
    if (mode === "code") {
      return [
        { path: "/api/code", payload: basePayload },
        { path: "/code", payload: basePayload },
      ];
    }
    if (mode === "deepseek") {
      return [
        {
          path: "/api/chat",
          payload: {
            ...basePayload,
            message:
              "DeepSeek mode.\n" +
              "Respond with concise sections: Summary, Analysis, Final Answer.\n\n" +
              `User request:\n${payload.message}`,
          },
        },
        {
          path: "/chat",
          payload: {
            ...basePayload,
            message:
              "DeepSeek mode.\n" +
              "Respond with concise sections: Summary, Analysis, Final Answer.\n\n" +
              `User request:\n${payload.message}`,
          },
        },
        { path: "/api/research", payload: basePayload },
        { path: "/research", payload: basePayload },
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
            message:
              `Research request:\n${payload.message}\n\n` +
              "Return sections: Summary, Details, Risks/Tradeoffs, Next Steps.",
          },
        },
        {
          path: "/chat",
          payload: {
            ...basePayload,
            message:
              `Research request:\n${payload.message}\n\n` +
              "Return sections: Summary, Details, Risks/Tradeoffs, Next Steps.",
          },
        },
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
            message:
              `Create one optimized ${payload.prompt_type || "general"} prompt.\n` +
              `User requirements:\n${payload.message}\n\n` +
              "Return only the final prompt text.",
          },
        },
        {
          path: "/chat",
          payload: {
            ...basePayload,
            message:
              `Create one optimized ${payload.prompt_type || "general"} prompt.\n` +
              `User requirements:\n${payload.message}\n\n` +
              "Return only the final prompt text.",
          },
        },
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
            message:
              `Generate one high-quality image prompt for:\n${payload.message}\n\n` +
              `Preferred style: ${payload.image_type || "realistic"}.\n` +
              "Return only the optimized prompt text.",
          },
        },
        {
          path: "/chat",
          payload: {
            ...basePayload,
            message:
              `Generate one high-quality image prompt for:\n${payload.message}\n\n` +
              `Preferred style: ${payload.image_type || "realistic"}.\n` +
              "Return only the optimized prompt text.",
          },
        },
      ];
    }
    return [
      { path: "/api/kimi_image_describer", payload: basePayload },
      { path: "/kimi_image_describer", payload: basePayload },
    ];
  }

  async function requestWithFallback(mode, payload) {
    if (!state.apiBase) {
      await resolveApiBase();
    }
    if (!state.apiBase) {
      throw new Error("The assistant is not ready yet.");
    }

    const attempts = endpointAttempts(mode, payload);
    const errors = [];

    for (const attempt of attempts) {
      const url = `${state.apiBase}${attempt.path}`;
      try {
        const { response, data } = await fetchJsonWithTimeout(
          url,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(attempt.payload),
          },
          mode === "image" ? 90000 : 65000
        );

        if (response.ok) {
          return data || {};
        }

        const message =
          (data && typeof data.error === "string" && data.error) ||
          `Request failed with HTTP ${response.status}.`;
        errors.push(`${attempt.path} -> ${message}`);

        if ([404, 405, 501].includes(response.status)) {
          continue;
        }
        if (response.status >= 500 && response.status <= 599) {
          continue;
        }
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        errors.push(`${attempt.path} -> ${message}`);
        continue;
      }
    }

    const fallbackMessage = errors[errors.length - 1] || "No compatible API endpoint responded.";
    throw new Error(fallbackMessage);
  }
  function currentModeConfig() {
    return modeUi[state.activeMode] || modeUi.chat;
  }

  function setMode(mode) {
    state.activeMode = mode;
    for (const modeButton of elements.modes) {
      modeButton.classList.toggle("active", modeButton.dataset.mode === mode);
    }

    const config = currentModeConfig();
    if (elements.inputLabel) {
      elements.inputLabel.textContent = config.label;
    }
    if (elements.aiInput) {
      elements.aiInput.placeholder = config.placeholder;
    }

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
      hideImage();
    }
  }

  async function fileToBase64(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => {
        const raw = String(reader.result || "");
        const comma = raw.indexOf(",");
        resolve(comma >= 0 ? raw.slice(comma + 1) : raw);
      };
      reader.onerror = () => reject(new Error("Failed to read image file."));
      reader.readAsDataURL(file);
    });
  }

  function buildReportText() {
    return [
      "JO AI mini-app issue report",
      `time_utc=${new Date().toISOString()}`,
      `app_version=${FRONTEND_VERSION}`,
      `active_mode=${state.activeMode}`,
      `status=${elements.status ? elements.status.textContent : "unknown"}`,
      `user_agent=${navigator.userAgent}`,
    ].join("\n");
  }

  function configureSupportActions() {
    const querySupport = normalizeSupportUrl(getQueryParam("support_url"));
    if (querySupport && elements.contactBtn) {
      elements.contactBtn.href = querySupport;
    }

    if (elements.reportBtn) {
      elements.reportBtn.addEventListener("click", async () => {
        try {
          await copyText(buildReportText());
          showToast("Support note copied. Paste and send it to the developer.");
        } catch (error) {
          showToast(error instanceof Error ? error.message : "Failed to build support note.", "error");
        }
      });
    }
  }

  function initTelegram() {
    if (!tg) {
      setStatus("Browser mode");
      setUserInfo("Guest mode");
      if (elements.welcomeMessage) {
        elements.welcomeMessage.textContent = "Running in browser mode. AI Studio is ready to use.";
      }
      return;
    }

    tg.ready();
    if (typeof tg.expand === "function") {
      tg.expand();
    }
    const firstName =
      (tg.initDataUnsafe &&
        tg.initDataUnsafe.user &&
        typeof tg.initDataUnsafe.user.first_name === "string" &&
        tg.initDataUnsafe.user.first_name) ||
      "there";
    setUserInfo(`Hi, ${firstName}`);
    if (elements.welcomeMessage) {
      elements.welcomeMessage.textContent = `Ready, ${firstName}. Your JO AI workspace is prepared.`;
    }
  }

  function initWelcomeOverlay() {
    if (!elements.welcomeOverlay || !elements.openAppBtn) {
      return;
    }
    elements.openAppBtn.addEventListener("click", () => {
      elements.welcomeOverlay.classList.add("hidden");
      if (elements.aiInput) {
        elements.aiInput.focus();
      }
    });
  }

  function buildRequestPayload(mode) {
    const message = elements.aiInput ? elements.aiInput.value.trim() : "";
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
        throw new Error("Please enter a prompt type.");
      }
      payload.prompt_type = promptType;
    }

    if (mode === "image") {
      const selected = elements.imageType ? elements.imageType.value : "realistic";
      payload.image_type = selected || "realistic";
    }

    return payload;
  }

  async function callAI() {
    if (state.isBusy) {
      return;
    }

    const mode = state.activeMode;
    let payload;
    try {
      payload = buildRequestPayload(mode);
    } catch (error) {
      renderOutput(`### Validation error\n${error instanceof Error ? error.message : "Invalid request."}`);
      setApiState("invalid input", "error");
      showToast("Please complete the required fields.", "error");
      return;
    }

    if (mode === "kimi") {
      const file = elements.kimiImage && elements.kimiImage.files ? elements.kimiImage.files[0] : null;
      if (!file) {
        renderOutput("### Image required\nUpload an image first for Kimi describe mode.");
        setApiState("missing image", "error");
        return;
      }
      if (!file.type.startsWith("image/")) {
        renderOutput("### Invalid file\nPlease upload a valid image file.");
        setApiState("invalid file", "error");
        return;
      }
      if (file.size > 8 * 1024 * 1024) {
        renderOutput("### File too large\nPlease use an image smaller than 8MB.");
        setApiState("file too large", "error");
        return;
      }
      try {
        payload.image_base64 = await fileToBase64(file);
      } catch (error) {
        renderOutput(`### Upload error\n${error instanceof Error ? error.message : "Failed to read file."}`);
        setApiState("upload failed", "error");
        return;
      }
    }

    setBusy(true);
    try {
      const data = await requestWithFallback(mode, payload);
      if (data && typeof data.error === "string" && data.error.trim()) {
        throw new Error(data.error.trim());
      }

      const output =
        (data && typeof data.output === "string" && data.output) ||
        (data && typeof data.warning === "string" && data.warning) ||
        "No output returned.";
      renderOutput(output);

      if (data && data.image_base64) {
        showImage(data.image_base64);
      } else {
        hideImage();
      }

      if (data && typeof data.warning === "string" && data.warning.trim()) {
        showToast(data.warning, "error", 3200);
      } else {
        showToast("Response ready.");
      }
      setApiState("done", "success");
    } catch (error) {
      const message = error instanceof Error ? error.message : "Unknown request error.";
      renderOutput(`### Request failed\n${message}\n\nTry again, or use Help and Support to report this issue.`);
      hideImage();
      setApiState("failed", "error");
      showToast("Request failed. Check Help and Support.", "error");
    } finally {
      setBusy(false);
    }
  }

  function wireModes() {
    for (const modeButton of elements.modes) {
      modeButton.addEventListener("click", () => {
        const nextMode = modeButton.dataset.mode || "chat";
        setMode(nextMode);
      });
    }
  }

  function wireActions() {
    if (elements.sendBtn) {
      elements.sendBtn.addEventListener("click", callAI);
    }
    if (elements.clearBtn) {
      elements.clearBtn.addEventListener("click", () => {
        if (elements.aiInput) {
          elements.aiInput.value = "";
        }
        if (elements.promptType) {
          elements.promptType.value = "";
        }
        if (elements.kimiImage) {
          elements.kimiImage.value = "";
        }
        if (elements.uploadInfo) {
          elements.uploadInfo.textContent = "No image selected.";
        }
        clearOutput();
        hideImage();
        setApiState("idle", "muted");
        setLoadingHint("Ready when you are.");
      });
    }
    if (elements.copyBtn) {
      elements.copyBtn.addEventListener("click", async () => {
        try {
          await copyText(state.lastOutputText);
          showToast("Full response copied.");
        } catch (error) {
          showToast(error instanceof Error ? error.message : "Copy failed.", "error");
        }
      });
    }
    if (elements.downloadImageBtn) {
      elements.downloadImageBtn.addEventListener("click", () => {
        if (!state.lastImageDataUrl) {
          showToast("No image available to save.", "error");
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
    if (elements.aiInput) {
      elements.aiInput.addEventListener("keydown", (event) => {
        if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
          event.preventDefault();
          callAI();
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
          elements.uploadInfo.textContent = "No image selected.";
          return;
        }
        const sizeMb = (file.size / (1024 * 1024)).toFixed(2);
        elements.uploadInfo.textContent = `${file.name} (${sizeMb} MB)`;
      });
    }
  }

  async function boot() {
    initTelegram();
    initWelcomeOverlay();
    configureSupportActions();
    wireModes();
    wireActions();
    setMode("chat");
    clearOutput();
    hideImage();
    setVersionBadge(FRONTEND_VERSION);
    setApiState("idle", "muted");
    await resolveApiBase();
  }

  boot();
})();
