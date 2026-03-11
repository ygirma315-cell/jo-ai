(() => {
  "use strict";

  const tg = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;
  const bootDebug = window.__joMiniAppBoot || null;
  const API_BASE_STORAGE_KEY = "jo_api_base";
  const STORAGE_VERSION_KEY = "jo_frontend_version";
  const HOME_ENTRY_STORAGE_KEY = "jo_home_entered";
  const HISTORY_PREFIX = "jo_history_";
  const REFERRAL_STORAGE_KEY = "jo_referral_code";
  const REFERRAL_CLAIMED_PREFIX = "jo_referral_claimed_";
  const CONVERSATION_STORAGE_PREFIX = "jo_conversation_";
  const FRONTEND_VERSION = "v1.6.0";
  const SITE_BASE_URL = "https://ygirma315-cell.github.io/jo-ai/";
  const MAX_HISTORY_ITEMS = 18;
  const MAX_UPLOAD_BYTES = 8 * 1024 * 1024;
  const MAX_CODE_UPLOAD_BYTES = 1_500_000;
  const SAFE_INTERNAL_DETAILS_REFUSAL =
    "I can't share internal backend or API details. For JO API access, contact the developer @grpbuyer3.";

  const loadingMessages = [
    "Processing...",
    "Generating...",
    "Thinking...",
    "Preparing response...",
  ];

  const STATIC_RELEASES = [
    {
      version: "v1.6.0",
      title: "Mobile stability + referral + Gemini update",
      items: [
        "Added Gemini chat mode in the same JO AI interface with server-side provider routing.",
        "Referral section now loads your personal invite links and tracks referral claims safely.",
        "Mini app now sends frontend source, conversation ID, and referral headers for cleaner analytics across admin and backend.",
      ],
    },
    {
      version: "v1.5.1",
      title: "Stability and readability hardening",
      items: [
        "Chat text colors now use explicit high-contrast fallbacks to prevent washed-out or invisible text on mixed Telegram themes.",
        "Request flow now reports clearer network, timeout, and backend errors instead of one generic failure message.",
        "Frontend request diagnostics and backend request IDs are surfaced to make cross-client failures easier to debug.",
      ],
    },
    {
      version: "v1.5.0",
      title: "Major mini app and bot organization update",
      items: [
        "The mini app now opens directly on AI tool selection, and tool headers use the top white space better with cleaner update access and safer Back-button spacing.",
        "Code Generator now pushes larger requests toward fuller system outputs, with more user-facing examples and a compact inline plus button for uploads.",
        "Telegram bot flow now uses clearer one-step Back behavior inside multi-step tools, a cleaner main-menu order, and richer feature labels across menus.",
      ],
    },
    {
      version: "v1.4.1",
      title: "Fixed stable chat viewport on mobile",
      items: [
        "Tool pages now keep one fixed conversation viewport height on load, so chat panels do not randomly start small or large",
        "Composer stays pinned in a fixed bottom row while only the conversation list scrolls",
        "Keyboard handling now keeps the input visible in Telegram-style webviews by reserving bottom inset space instead of shrinking layout rows",
      ],
    },
    {
      version: "v1.4.0",
      title: "Premium mobile chat refresh",
      items: [
        "All JO AI chat pages now use a cleaner bordered layout with a much larger conversation panel and a smaller pinned composer",
        "Mobile webviews now respect the shrinking visible viewport better, so the input stays visible and part of the conversation remains on-screen above the keyboard",
        "Client-side stale history and cached API base values are reset on new frontend releases, and both the website and bot now show the current version with an update summary",
      ],
    },
    {
      version: "v1.3.2",
      title: "Security hardening and safer public branding",
      items: [
        "Public version info now stays branded while internal backend, model, and API details remain hidden",
        "Vision requests now use generic JO AI routing instead of older provider-specific wording",
        "Support links and public copy now point users to @grpbuyer3 for JO API access",
      ],
    },
    {
      version: "v1.3.1",
      title: "Fixed mobile composer and cleaner welcome polish",
      items: [
        "Tool pages now keep a stable chat view with a fixed bottom composer and a Send button pinned to the right",
        "Only the conversation thread scrolls, while the input area stays compact and clearer inside Telegram mobile",
        "The welcome screen now uses a cleaner JO AI icon treatment instead of the older eye emoji",
      ],
    },
    {
      version: "v1.3.0",
      title: "Shared chat app redesign",
      items: [
        "All AI tool pages now use one clean chat-style layout with a compact header and bottom composer",
        "Message flow, thinking states, and scrolling are smoother on mobile and inside Telegram",
        "Image, prompt, code, research, and vision tools now share the same calmer design system",
      ],
    },
  ];

  const toolConfig = {
    chat: {
      title: "JO AI Chat",
      description: "Fast help for questions, ideas, writing, and everyday tasks.",
      lead: "Ask anything and keep the whole conversation in one calm thread.",
      example: "Explain recursion like I am new to programming.",
      label: "Ask Joe AI chatbot",
      placeholder: "Ask Joe AI chatbot",
      rows: 1,
      maxComposerHeight: 144,
      historyTitle: "Conversation",
      emptyTitle: "Ask Joe AI chatbot",
      emptyCopy: "Fast help for ideas, questions, and tasks.",
    },
    gemini: {
      title: "Gemini Chat",
      description: "Gemini-powered chat routed through JO AI branding and guardrails.",
      lead: "Ask anything and get Gemini capability in the same JO AI interface.",
      example: "Give me a concise plan to improve my study schedule this week.",
      label: "Ask Gemini via JO AI",
      placeholder: "Ask Gemini via JO AI",
      rows: 1,
      maxComposerHeight: 152,
      historyTitle: "Gemini conversation",
      emptyTitle: "Ask Gemini via JO AI",
      emptyCopy: "Gemini responses appear here with JO AI guardrails.",
    },
    code: {
      title: "Code Generator",
      description: "Generate stronger implementation plans, fuller systems, or debug uploaded code in one flow.",
      lead: "Complex code requests are internally refined so JO AI can return more complete architecture and implementation detail.",
      example: "Build a food delivery app with customer accounts, live order tracking, payments, admin dashboard, tests, and deploy steps.",
      label: "Ask Joe AI chatbot for code",
      placeholder: "Ask Joe AI chatbot for code, debugging, or implementation help",
      rows: 1,
      maxComposerHeight: 176,
      historyTitle: "Code chat",
      needsCodeUpload: true,
      supportsCodeSave: true,
      emptyTitle: "Start a code conversation",
      emptyCopy: "Share a bug, spec, or feature request and JO AI will reply in-chat.",
    },
    deepseek: {
      title: "Deep Analysis",
      description: "Structured reasoning for harder questions, tradeoffs, and decisions.",
      lead: "Use this when you want a slower, more deliberate answer in the same thread.",
      example: "Compare SQL and NoSQL for a fast-growing product and explain the tradeoffs.",
      label: "Ask Joe AI chatbot to analyze",
      placeholder: "Ask Joe AI chatbot to compare, reason, or break down a decision",
      rows: 1,
      maxComposerHeight: 152,
      historyTitle: "Analysis thread",
      emptyTitle: "Ask for deeper analysis",
      emptyCopy: "Comparisons, reasoning, and structured tradeoffs show up here.",
    },
    research: {
      title: "Research",
      description: "Focused breakdowns, summaries, practical context, and next steps.",
      lead: "Research questions stay organized in one clean conversation view.",
      example: "Explain the pros and cons of remote teams for a startup and suggest best practices.",
      label: "Ask Joe AI chatbot to research",
      placeholder: "Ask Joe AI chatbot to research a topic, summarize, or suggest next steps",
      rows: 1,
      maxComposerHeight: 160,
      historyTitle: "Research thread",
      emptyTitle: "Start a research thread",
      emptyCopy: "Ask for summaries, risks, tradeoffs, or practical guidance.",
    },
    prompt: {
      title: "Prompt Builder",
      description: "Build stronger prompts without leaving the chat flow.",
      lead: "Describe the goal, optionally add a prompt type, and get one polished prompt back.",
      example: "Create a concise onboarding prompt for a customer support assistant.",
      label: "Ask Joe AI chatbot to build a prompt",
      placeholder: "Ask Joe AI chatbot to build a prompt for your goal",
      rows: 1,
      maxComposerHeight: 160,
      historyTitle: "Prompt results",
      needsPromptType: true,
      examplePromptType: "assistant prompt",
      emptyTitle: "Build a prompt with Joe AI",
      emptyCopy: "Share the goal and JO AI will return a cleaner prompt here.",
    },
    image: {
      title: "Image Generator",
      description: "Describe a visual, choose a style and ratio, and keep the result in the chat.",
      lead: "Write the scene, pick a style and ratio, and save the image once it lands.",
      example: "A cinematic night city street with rain reflections and soft neon lighting.",
      label: "Describe the image you want",
      placeholder: "Describe the image you want Joe AI to create",
      rows: 1,
      maxComposerHeight: 160,
      historyTitle: "Image results",
      needsImageType: true,
      needsImageRatio: true,
      supportsImageSave: true,
      exampleImageType: "cyberpunk",
      exampleImageRatio: "16:9",
      defaultImageRatio: "1:1",
      emptyTitle: "Create an image with Joe AI",
      emptyCopy: "Describe a scene, choose a style, and your image result will appear here.",
    },
    tts: {
      title: "Text-to-Speech",
      description: "Convert text into speech with language, voice, and richer style controls.",
      lead: "Pick your speech settings, submit text, and play or save the generated audio.",
      example: "Welcome to JO AI. Your personalized audio summary is ready.",
      label: "Enter text for speech",
      placeholder: "Type the text you want to convert to speech",
      rows: 1,
      maxComposerHeight: 176,
      historyTitle: "Speech results",
      needsTtsLanguage: true,
      needsTtsVoice: true,
      needsTtsEmotion: true,
      supportsAudioSave: true,
      defaultTtsLanguage: "en",
      defaultTtsVoice: "female",
      defaultTtsEmotion: "natural",
      emptyTitle: "Create speech from text",
      emptyCopy: "Choose language, voice, and style, then generate speech in one step.",
    },
    kimi: {
      title: "JO AI Vision",
      description: "Upload an image and ask Joe AI to describe or explain it.",
      lead: "Add an image, ask a question, and keep every vision reply in the same conversation.",
      example: "Describe the image and point out the main objects and the setting.",
      label: "Ask Joe AI about this image",
      placeholder: "Ask Joe AI about this image",
      rows: 1,
      maxComposerHeight: 144,
      historyTitle: "Vision history",
      needsUpload: true,
      supportsImageSave: false,
      emptyTitle: "Ask Joe AI about an image",
      emptyCopy: "Upload an image and JO AI will describe, summarize, or explain it here.",
    },
  };

  let elements = {};

  const state = {
    apiBase: "",
    isBusy: false,
    loadingTimer: null,
    loadingIndex: 0,
    pendingId: "",
    history: [],
    lastOutputText: "",
    lastImageDataUrl: "",
    lastAudioDataUrl: "",
    lastAudioFileName: "",
    lastCodeFileDataUrl: "",
    lastCodeFileName: "",
    toastTimer: null,
    emptyTemplate: "",
    kimiPreviewUrl: "",
    activeModal: null,
    modalTrigger: null,
    scrollLockY: 0,
    bodyLockStyles: null,
    runtimeInfo: null,
    referralCode: "",
  };

  const sensitiveTargetsPattern =
    /\b(system(?:\s|-)?prompt|hidden(?:\s|-)?prompt|hidden(?:\s|-)?instructions?|developer(?:\s|-)?message|config(?:uration)?|\.env|env(?:ironment)?(?:\s|-)?vars?|environment(?:\s|-)?variables?|api(?:\s|-)?keys?|tokens?|bearer|authorization|headers?|secrets?|credentials?|backend|provider|stack|architecture|endpoints?|runtime|model(?:\s|-)?name|model(?:\s|-)?version|exact(?:\s|-)?model|hidden(?:\s|-)?settings?)\b/i;
  const extractionVerbsPattern =
    /\b(reveal|show|tell|dump|print|display|list|return|output|extract|share|expose|leak|give|send)\b/i;
  const instructionBypassPattern =
    /\b(ignore|bypass|override|forget|disregard)\b[\s\S]{0,80}\b(instructions|rules|system|developer|policy|guardrails?)\b/i;
  const selfContextPattern =
    /\b(you|your|jo\s+ai|this\s+bot|the\s+bot|the\s+website|the\s+mini\s+app|the\s+backend)\b/i;
  const providerNamesPattern = /\b(nvidia|openai|anthropic|moonshot|deepseek|render|onrender|llama|flux|kimi|google|gemini|meta)\b/i;

  function byId(id) {
    return document.getElementById(id);
  }

  function getPage() {
    return document.body.dataset.page || "home";
  }

  function getToolId() {
    return document.body.dataset.tool || "";
  }

  function currentTool() {
    return toolConfig[getToolId()] || null;
  }

  function hasTelegramWebAppContext(candidate) {
    if (!candidate || typeof candidate !== "object") {
      return false;
    }

    const initData = typeof candidate.initData === "string" ? candidate.initData.trim() : "";
    const unsafe = candidate.initDataUnsafe && typeof candidate.initDataUnsafe === "object" ? candidate.initDataUnsafe : null;
    const platform = typeof candidate.platform === "string" ? candidate.platform.toLowerCase() : "";

    if (initData) {
      return true;
    }
    if (unsafe && typeof unsafe.user === "object" && unsafe.user && typeof unsafe.user.id !== "undefined") {
      return true;
    }
    if (unsafe && typeof unsafe.chat === "object" && unsafe.chat && typeof unsafe.chat.id !== "undefined") {
      return true;
    }
    if (unsafe && typeof unsafe.query_id === "string" && unsafe.query_id.trim()) {
      return true;
    }
    return Boolean(platform && platform !== "unknown");
  }

  function reportStartupError(label, error) {
    const reporter = bootDebug && typeof bootDebug.reportError === "function" ? bootDebug.reportError : null;
    if (reporter) {
      reporter(label, error);
      return;
    }
    console.error(`[JO AI Mini App] ${label}`, error);
  }

  function setRootMounted(value) {
    if (bootDebug && typeof bootDebug.setRootMounted === "function") {
      bootDebug.setRootMounted(value);
    }
  }

  function markStartupComplete() {
    if (!bootDebug) {
      return;
    }
    bootDebug.startupComplete = true;
    if (typeof bootDebug.hideFallback === "function") {
      bootDebug.hideFallback();
    }
    if (typeof bootDebug.updateBanner === "function") {
      bootDebug.updateBanner();
    }
  }

  function getStorage(name) {
    try {
      return window[name] || null;
    } catch (_error) {
      return null;
    }
  }

  function getLocalStorage() {
    return getStorage("localStorage");
  }

  function getSessionStorage() {
    return getStorage("sessionStorage");
  }

  function normalizeHostedHomeUrl() {
    if (getPage() !== "home") {
      return;
    }

    try {
      const current = new URL(window.location.href);
      const normalizedPath = current.pathname.replace(/\/+$/, "");
      if (current.hostname !== "ygirma315-cell.github.io") {
        return;
      }
      if (normalizedPath !== "/jo-ai" && normalizedPath !== "/jo-ai/index.html") {
        return;
      }

      const next = new URL(SITE_BASE_URL);
      next.search = current.search;
      next.hash = current.hash;
      if (current.href !== next.href) {
        window.history.replaceState(null, "", next.toString());
      }
    } catch (_error) {
      // ignore URL parsing failures
    }
  }

  function polishStaticUi() {
    document.querySelectorAll(".back-link").forEach((link) => {
      link.textContent = "Back";
      link.setAttribute("aria-label", "Back");
    });

    document.querySelectorAll(".tool-hero").forEach((section) => {
      section.remove();
    });

    document.querySelectorAll('.footer-links a[href="help.html"]').forEach((link) => {
      link.textContent = "Help";
    });

    document.querySelectorAll('.footer-links a[href="index.html"]').forEach((link) => {
      link.remove();
    });
  }

  function collectElements() {
    elements = {
      appRoot: byId("appRoot"),
      welcomeOverlay: byId("welcomeOverlay"),
      welcomeMessage: byId("welcomeMessage"),
      openAppBtn: byId("openAppBtn"),
      status: byId("status"),
      userInfo: byId("userInfo"),
      toolTitle: byId("toolTitle"),
      toolDescription: byId("toolDescription"),
      toolLead: byId("toolLead"),
      toolExample: byId("toolExample"),
      useExampleBtn: byId("useExampleBtn"),
      toolForm: byId("toolForm"),
      inputLabel: byId("inputLabel"),
      aiInput: byId("aiInput"),
      promptTypeWrap: byId("promptTypeWrap"),
      promptType: byId("promptType"),
      imageTypeWrap: byId("imageTypeWrap"),
      imageType: byId("imageType"),
      imageRatioWrap: byId("imageRatioWrap"),
      imageRatio: byId("imageRatio"),
      ttsLanguageWrap: byId("ttsLanguageWrap"),
      ttsLanguage: byId("ttsLanguage"),
      ttsVoiceWrap: byId("ttsVoiceWrap"),
      ttsVoice: byId("ttsVoice"),
      ttsEmotionWrap: byId("ttsEmotionWrap"),
      ttsEmotion: byId("ttsEmotion"),
      codeFileWrap: byId("codeFileWrap"),
      codeFile: byId("codeFile"),
      codeFileInfo: byId("codeFileInfo"),
      kimiImageWrap: byId("kimiImageWrap"),
      kimiImage: byId("kimiImage"),
      kimiPreviewWrap: byId("kimiPreviewWrap"),
      kimiPreview: byId("kimiPreview"),
      uploadInfo: byId("uploadInfo"),
      sendBtn: byId("sendBtn"),
      clearBtn: byId("clearBtn"),
      pastChatsBtn: byId("pastChatsBtn"),
      copyBtn: byId("copyBtn"),
      downloadImageBtn: byId("downloadImageBtn"),
      loadingHint: byId("loadingHint"),
      apiState: byId("apiState"),
      historyList: byId("historyList"),
      emptyState: byId("emptyState"),
      historyTitle: byId("historyTitle"),
      contactBtn: byId("contactBtn"),
      reportBtn: byId("reportBtn"),
      versionBadge: byId("versionBadge"),
      updatesTitle: byId("updatesTitle"),
      updatesSummary: byId("updatesSummary"),
      updatesList: byId("updatesList"),
      updatesModal: byId("updatesModal"),
      updatesClose: byId("updatesClose"),
      comingSoonModal: byId("comingSoonModal"),
      comingSoonClose: byId("comingSoonClose"),
      referralCard: byId("referralCard"),
      referralCode: byId("referralCode"),
      referralTelegramLink: byId("referralTelegramLink"),
      referralMiniappLink: byId("referralMiniappLink"),
      referralStatus: byId("referralStatus"),
      copyReferralCodeBtn: byId("copyReferralCodeBtn"),
      copyReferralLinkBtn: byId("copyReferralLinkBtn"),
      toast: byId("toast"),
    };
  }

  function safeStorageGet(storage, key) {
    if (!storage || typeof storage.getItem !== "function") {
      return "";
    }
    try {
      return storage.getItem(key) || "";
    } catch (_error) {
      return "";
    }
  }

  function safeStorageSet(storage, key, value) {
    if (!storage || typeof storage.setItem !== "function") {
      return;
    }
    try {
      storage.setItem(key, value);
    } catch (_error) {
      // ignore storage failures
    }
  }

  function safeStorageRemove(storage, key) {
    if (!storage || typeof storage.removeItem !== "function") {
      return;
    }
    try {
      storage.removeItem(key);
    } catch (_error) {
      // ignore storage failures
    }
  }

  function safeStorageKeys(storage) {
    if (!storage || typeof storage.length !== "number" || typeof storage.key !== "function") {
      return [];
    }

    const keys = [];
    for (let index = 0; index < storage.length; index += 1) {
      try {
        const key = storage.key(index);
        if (key) {
          keys.push(key);
        }
      } catch (_error) {
        return keys;
      }
    }
    return keys;
  }

  function clearStaleClientState() {
    const local = getLocalStorage();
    const session = getSessionStorage();
    const storedVersion = safeStorageGet(local, STORAGE_VERSION_KEY);

    if (storedVersion === FRONTEND_VERSION) {
      return;
    }

    safeStorageRemove(local, API_BASE_STORAGE_KEY);
    safeStorageSet(local, STORAGE_VERSION_KEY, FRONTEND_VERSION);

    for (const key of safeStorageKeys(session)) {
      if (key.startsWith(HISTORY_PREFIX)) {
        safeStorageRemove(session, key);
      }
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
    return values.filter((value, index, array) => value && array.indexOf(value) === index);
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

  function createId() {
    return `${Date.now()}-${Math.random().toString(16).slice(2, 8)}`;
  }

  function scheduleFrame(task) {
    const runner = () => {
      try {
        task();
      } catch (error) {
        reportStartupError("frame task", error);
      }
    };

    if (typeof window.requestAnimationFrame === "function") {
      window.requestAnimationFrame(runner);
      return;
    }

    window.setTimeout(runner, 16);
  }

  function syncViewportState() {
    if (bootDebug && typeof bootDebug.syncViewportMetrics === "function") {
      bootDebug.syncViewportMetrics();
    }
  }

  function scrollHistoryToBottom(immediate = false) {
    if (!elements.historyList) {
      return;
    }

    const top = elements.historyList.scrollHeight;
    if (immediate || typeof elements.historyList.scrollTo !== "function") {
      elements.historyList.scrollTop = top;
      return;
    }

    try {
      elements.historyList.scrollTo({ top, behavior: "smooth" });
    } catch (_error) {
      elements.historyList.scrollTop = top;
    }
  }

  function scrollComposerIntoView(immediate = false) {
    if (!elements.historyList) {
      return;
    }

    const runner = () => {
      scrollHistoryToBottom(immediate);
    };

    if (immediate) {
      runner();
      return;
    }

    window.setTimeout(runner, 120);
  }

  function getComposerMaxHeight() {
    const config = currentTool();
    return config && Number.isFinite(config.maxComposerHeight) ? Number(config.maxComposerHeight) : 176;
  }

  function resizeComposerInput(reset = false) {
    if (!elements.aiInput) {
      return;
    }

    elements.aiInput.style.height = "auto";
    if (reset) {
      elements.aiInput.style.overflowY = "hidden";
    }

    const nextHeight = Math.min(Math.max(elements.aiInput.scrollHeight, 54), getComposerMaxHeight());
    elements.aiInput.style.height = `${nextHeight}px`;
    elements.aiInput.style.overflowY = elements.aiInput.scrollHeight > nextHeight ? "auto" : "hidden";
  }

  function hasComposerPayload() {
    const mode = getToolId();
    const message = elements.aiInput ? elements.aiInput.value.trim() : "";

    if (mode === "kimi") {
      return Boolean(elements.kimiImage && elements.kimiImage.files && elements.kimiImage.files[0]);
    }
    return Boolean(message);
  }

  function updateSendButtonState() {
    if (!elements.sendBtn) {
      return;
    }
    elements.sendBtn.disabled = state.isBusy || !hasComposerPayload();
  }

  function shouldDismissKeyboardAfterSubmit() {
    return window.matchMedia("(max-width: 900px)").matches || isTelegramMiniApp();
  }

  function isTelegramMiniApp() {
    return hasTelegramWebAppContext(tg);
  }

  function getTelegramWebAppUser() {
    if (!isTelegramMiniApp()) {
      return null;
    }
    if (!tg || !tg.initDataUnsafe || typeof tg.initDataUnsafe !== "object") {
      return null;
    }
    const user = tg.initDataUnsafe.user;
    if (!user || typeof user !== "object") {
      return null;
    }
    return user;
  }

  function buildTrackingPayloadFields() {
    const user = getTelegramWebAppUser();
    const tracking = { frontend_source: "mini_app" };
    if (!user) {
      return tracking;
    }

    const rawId = user.id;
    const parsedId = Number.parseInt(String(rawId), 10);
    if (Number.isFinite(parsedId) && parsedId > 0) {
      tracking.telegram_id = parsedId;
    }
    if (typeof user.username === "string" && user.username.trim()) {
      tracking.username = user.username.trim();
    }
    if (typeof user.first_name === "string" && user.first_name.trim()) {
      tracking.first_name = user.first_name.trim();
    }
    if (typeof user.last_name === "string" && user.last_name.trim()) {
      tracking.last_name = user.last_name.trim();
    }
    return tracking;
  }

  function sanitizeReferralCode(rawValue) {
    const raw = String(rawValue || "").trim().toLowerCase();
    if (!raw) {
      return "";
    }
    const normalized = raw.startsWith("ref_") || raw.startsWith("ref-") ? raw.slice(4) : raw;
    const cleaned = normalized.replace(/[^a-z0-9_-]/g, "");
    return cleaned.slice(0, 64);
  }

  function resolveReferralCode() {
    if (state.referralCode) {
      return state.referralCode;
    }

    const fromUrl = sanitizeReferralCode(
      getQueryParam("ref") ||
      getQueryParam("referral") ||
      getQueryParam("referral_code") ||
      getQueryParam("startapp") ||
      getQueryParam("start")
    );
    const local = getLocalStorage();
    const stored = sanitizeReferralCode(safeStorageGet(local, REFERRAL_STORAGE_KEY));
    const selected = fromUrl || stored;
    if (!selected) {
      return "";
    }
    state.referralCode = selected;
    safeStorageSet(local, REFERRAL_STORAGE_KEY, selected);
    return selected;
  }

  function conversationStorageKey() {
    const tracking = buildTrackingPayloadFields();
    const tool = getToolId() || getPage() || "home";
    const userPart = tracking.telegram_id ? String(tracking.telegram_id) : "anon";
    return `${CONVERSATION_STORAGE_PREFIX}${tool}_${userPart}`;
  }

  function resolveConversationId() {
    const session = getSessionStorage();
    const key = conversationStorageKey();
    const existing = safeStorageGet(session, key).trim();
    if (existing) {
      return existing;
    }

    const tool = getToolId() || getPage() || "home";
    const tracking = buildTrackingPayloadFields();
    const userPart = tracking.telegram_id ? String(tracking.telegram_id) : "anon";
    const generated = `${userPart}:${tool}:${Date.now().toString(36)}`;
    safeStorageSet(session, key, generated);
    return generated;
  }

  function buildTrackingHeaders() {
    const headers = { "Content-Type": "application/json" };
    headers["X-Frontend-Source"] = "mini_app";
    headers["X-Conversation-ID"] = resolveConversationId();

    const initData = tg && typeof tg.initData === "string" ? tg.initData.trim() : "";
    if (initData) {
      headers["X-Telegram-Init-Data"] = initData;
    }

    const tracking = buildTrackingPayloadFields();
    if (tracking.telegram_id) {
      headers["X-Telegram-ID"] = String(tracking.telegram_id);
    }
    if (tracking.username) {
      headers["X-Telegram-Username"] = tracking.username;
    }
    if (tracking.first_name) {
      headers["X-Telegram-First-Name"] = tracking.first_name;
    }
    if (tracking.last_name) {
      headers["X-Telegram-Last-Name"] = tracking.last_name;
    }
    const referralCode = resolveReferralCode();
    if (referralCode) {
      headers["X-Referral-Code"] = referralCode;
    }
    return headers;
  }

  function getDialogElement(modal) {
    if (!modal || typeof modal.querySelector !== "function") {
      return null;
    }
    return modal.querySelector('[role="dialog"], .welcome-card, .updates-card');
  }

  function elementIsVisible(element) {
    return Boolean(element && typeof element.getClientRects === "function" && element.getClientRects().length);
  }

  function getFocusableElements(root) {
    if (!root || typeof root.querySelectorAll !== "function") {
      return [];
    }

    return Array.from(
      root.querySelectorAll(
        [
          'button:not([disabled])',
          '[href]',
          'input:not([disabled]):not([type="hidden"])',
          "select:not([disabled])",
          "textarea:not([disabled])",
          '[tabindex]:not([tabindex="-1"])',
        ].join(",")
      )
    ).filter((element) => {
      if (!(element instanceof HTMLElement)) {
        return false;
      }
      if (element.hidden || element.closest("[hidden]")) {
        return false;
      }
      return elementIsVisible(element);
    });
  }

  function focusElement(element) {
    if (!element || typeof element.focus !== "function") {
      return;
    }

    try {
      element.focus({ preventScroll: true });
    } catch (_error) {
      element.focus();
    }
  }

  function prepareManagedModals() {
    [elements.welcomeOverlay, elements.updatesModal, elements.comingSoonModal].forEach((modal) => {
      if (!modal) {
        return;
      }

      modal.hidden = false;
      modal.classList.remove("open");
      modal.setAttribute("aria-hidden", "true");

      const dialog = getDialogElement(modal);
      if (dialog && !dialog.hasAttribute("tabindex")) {
        dialog.tabIndex = -1;
      }
    });
  }

  function setBackgroundUiBlocked(blocked) {
    if (!elements.appRoot) {
      return;
    }

    if (blocked) {
      elements.appRoot.setAttribute("inert", "");
      elements.appRoot.setAttribute("aria-hidden", "true");
      return;
    }

    elements.appRoot.removeAttribute("inert");
    elements.appRoot.removeAttribute("aria-hidden");
  }

  function lockBodyScroll() {
    const body = document.body;
    if (!body || body.classList.contains("modal-active")) {
      return;
    }

    state.scrollLockY = window.scrollY || window.pageYOffset || 0;
    state.bodyLockStyles = {
      position: body.style.position,
      top: body.style.top,
      left: body.style.left,
      right: body.style.right,
      width: body.style.width,
      overflow: body.style.overflow,
    };

    body.classList.add("modal-active");
    body.style.position = "fixed";
    body.style.top = `-${state.scrollLockY}px`;
    body.style.left = "0";
    body.style.right = "0";
    body.style.width = "100%";
    body.style.overflow = "hidden";
  }

  function unlockBodyScroll() {
    const body = document.body;
    if (!body) {
      return;
    }

    body.classList.remove("modal-active");

    const previous = state.bodyLockStyles || {};
    body.style.position = previous.position || "";
    body.style.top = previous.top || "";
    body.style.left = previous.left || "";
    body.style.right = previous.right || "";
    body.style.width = previous.width || "";
    body.style.overflow = previous.overflow || "";

    const nextScrollY = state.scrollLockY || 0;
    state.scrollLockY = 0;
    state.bodyLockStyles = null;
    window.scrollTo(0, nextScrollY);
  }

  function focusModal(modal) {
    const dialog = getDialogElement(modal) || modal;
    const focusable = getFocusableElements(dialog);
    const target = focusable[0] || dialog;
    scheduleFrame(() => {
      focusElement(target);
    });
  }

  function openManagedModal(modal, trigger = null) {
    if (!modal) {
      return;
    }

    if (state.activeModal && state.activeModal !== modal) {
      closeManagedModal(state.activeModal, { restoreFocus: false });
    }

    state.activeModal = modal;
    state.modalTrigger =
      trigger instanceof HTMLElement
        ? trigger
        : document.activeElement instanceof HTMLElement
          ? document.activeElement
          : null;

    lockBodyScroll();
    setBackgroundUiBlocked(true);
    modal.setAttribute("aria-hidden", "false");
    modal.classList.add("open");
    focusModal(modal);
    syncViewportState();
  }

  function closeManagedModal(modal, options = {}) {
    const target = modal || state.activeModal;
    if (!target) {
      return;
    }

    const restoreFocus = options.restoreFocus !== false;
    const nextFocusTarget = options.nextFocusTarget instanceof HTMLElement ? options.nextFocusTarget : null;
    const trigger = state.activeModal === target ? state.modalTrigger : null;

    target.classList.remove("open");
    target.setAttribute("aria-hidden", "true");

    if (state.activeModal === target) {
      state.activeModal = null;
      state.modalTrigger = null;
      setBackgroundUiBlocked(false);
      unlockBodyScroll();
    }

    if (nextFocusTarget) {
      scheduleFrame(() => {
        focusElement(nextFocusTarget);
      });
    } else if (restoreFocus && trigger) {
      scheduleFrame(() => {
        focusElement(trigger);
      });
    }

    syncViewportState();
  }

  function closeActiveModal(options = {}) {
    if (!state.activeModal) {
      return;
    }
    closeManagedModal(state.activeModal, options);
  }

  function handleActiveModalKeydown(event) {
    const modal = state.activeModal;
    if (!modal) {
      return;
    }

    if (event.key === "Escape") {
      event.preventDefault();
      closeActiveModal();
      return;
    }

    if (event.key !== "Tab") {
      return;
    }

    const dialog = getDialogElement(modal) || modal;
    const focusable = getFocusableElements(dialog);
    if (!focusable.length) {
      event.preventDefault();
      focusElement(dialog);
      return;
    }

    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    const active = document.activeElement;

    if (!(active instanceof HTMLElement) || !dialog.contains(active)) {
      event.preventDefault();
      focusElement(event.shiftKey ? last : first);
      return;
    }

    if (event.shiftKey && active === first) {
      event.preventDefault();
      focusElement(last);
      return;
    }

    if (!event.shiftKey && active === last) {
      event.preventDefault();
      focusElement(first);
    }
  }

  function handleActiveModalFocus(event) {
    const modal = state.activeModal;
    if (!modal || modal.contains(event.target)) {
      return;
    }
    focusModal(modal);
  }

  function hideWelcomeOverlay(options = {}) {
    if (options.rememberEntry) {
      safeStorageSet(getSessionStorage(), HOME_ENTRY_STORAGE_KEY, "yes");
    }

    closeManagedModal(elements.welcomeOverlay, {
      restoreFocus: false,
      nextFocusTarget: options.focusTarget === false ? null : elements.appRoot,
    });
  }

  function showWelcomeOverlay() {
    openManagedModal(elements.welcomeOverlay);
  }

  function normalizeReleaseEntry(entry) {
    if (!entry || typeof entry !== "object") {
      return null;
    }

    const version = typeof entry.version === "string" ? entry.version.trim() : "";
    const title = typeof entry.title === "string" ? entry.title.trim() : "";
    const items = Array.isArray(entry.items)
      ? entry.items.map((item) => String(item || "").trim()).filter(Boolean)
      : [];

    if (!version && !title && !items.length) {
      return null;
    }

    return { version, title, items };
  }

  function normalizeRuntimeInfo(payload) {
    if (!payload || typeof payload !== "object") {
      return null;
    }

    const releases = Array.isArray(payload.releases)
      ? payload.releases.map(normalizeReleaseEntry).filter(Boolean)
      : [];
    const latest = normalizeReleaseEntry(payload.latest_release);

    return {
      version: typeof payload.version === "string" ? payload.version.trim() : "",
      web_version: typeof payload.web_version === "string" ? payload.web_version.trim() : "",
      latest_release: latest,
      releases: releases.length ? releases : latest ? [latest] : [],
    };
  }

  function getReleaseFeed() {
    if (state.runtimeInfo && Array.isArray(state.runtimeInfo.releases) && state.runtimeInfo.releases.length) {
      return state.runtimeInfo.releases;
    }
    return STATIC_RELEASES;
  }

  function getDisplayedWebVersion() {
    if (state.runtimeInfo && typeof state.runtimeInfo.web_version === "string" && state.runtimeInfo.web_version.trim()) {
      return state.runtimeInfo.web_version.trim();
    }
    return FRONTEND_VERSION;
  }

  function ensureToolHeaderUtilitySlot() {
    if (!document.body || document.body.dataset.page !== "tool") {
      return null;
    }
    const main = document.querySelector(".chat-topbar-main");
    if (!main) {
      return null;
    }

    let navRow = main.querySelector(".topbar-nav-row");
    if (!navRow) {
      navRow = document.createElement("div");
      navRow.className = "topbar-nav-row";
      const backLink = main.querySelector(".back-link");
      if (backLink) {
        navRow.appendChild(backLink);
      }
      main.prepend(navRow);
    }

    let slot = navRow.querySelector(".topbar-utility-slot");
    if (!slot) {
      slot = document.createElement("div");
      slot.className = "topbar-utility-slot";
      navRow.appendChild(slot);
    }

    return slot;
  }

  function ensureToolDescriptionElement() {
    const copy = document.querySelector(".chat-brand-copy");
    if (!copy) {
      return null;
    }
    let subtitle = byId("toolDescription");
    if (!subtitle) {
      subtitle = document.createElement("p");
      subtitle.id = "toolDescription";
      subtitle.className = "chat-subtitle";
      copy.appendChild(subtitle);
    }
    return subtitle;
  }

  function getUpdatesReturnLabel() {
    if (document.body && document.body.dataset.page === "tool") {
      const config = currentTool();
      return config && config.title ? config.title : "this tool";
    }
    return "home";
  }

  function syncUpdatesBackButton() {
    if (!elements.updatesClose) {
      return;
    }
    const returnLabel = getUpdatesReturnLabel();
    elements.updatesClose.textContent = "Back";
    elements.updatesClose.setAttribute("aria-label", `Go back to ${returnLabel}`);
    elements.updatesClose.title = `Back to ${returnLabel}`;
  }

  function mountVersionBadge() {
    if (!elements.versionBadge) {
      return;
    }

    const host = ensureToolHeaderUtilitySlot() || document.querySelector(".status-cluster, .chat-topbar-actions");
    if (host && elements.versionBadge.parentElement !== host) {
      host.appendChild(elements.versionBadge);
      return;
    }

    if (!host && elements.versionBadge.parentElement !== document.body) {
      document.body.appendChild(elements.versionBadge);
    }
  }

  function renderUpdatesPanel() {
    if (!elements.updatesList) {
      return;
    }

    const releases = getReleaseFeed();
    const current = releases[0] || null;

    if (elements.updatesTitle) {
      elements.updatesTitle.textContent = `${getDisplayedWebVersion()} release notes`;
    }
    if (elements.updatesSummary) {
      elements.updatesSummary.textContent = current && current.title ? current.title : "Current public JO AI updates.";
    }

    elements.updatesList.innerHTML = "";
    for (const item of releases) {
      const row = document.createElement("section");
      row.className = "updates-item";

      const itemTitle = document.createElement("h3");
      itemTitle.textContent = item.title ? `${item.version} · ${item.title}` : item.version || "Current release";

      const itemList = document.createElement("ul");
      for (const point of item.items) {
        const li = document.createElement("li");
        li.textContent = point;
        itemList.appendChild(li);
      }

      row.appendChild(itemTitle);
      if (item.items.length) {
        row.appendChild(itemList);
      }
      elements.updatesList.appendChild(row);
    }
  }

  function ensureGlobalUi() {
    if (!byId("versionBadge")) {
      const badge = document.createElement("button");
      badge.id = "versionBadge";
      badge.type = "button";
      badge.className = "version-badge";
      document.body.appendChild(badge);
    }

    if (!byId("updatesModal")) {
      const modal = document.createElement("div");
      modal.id = "updatesModal";
      modal.className = "updates-modal";
      modal.hidden = true;
      modal.setAttribute("aria-hidden", "true");

      const card = document.createElement("section");
      card.className = "updates-card";
      card.setAttribute("role", "dialog");
      card.setAttribute("aria-modal", "true");
      card.tabIndex = -1;

      const head = document.createElement("div");
      head.className = "panel-head";

      const copy = document.createElement("div");
      const eyebrow = document.createElement("p");
      eyebrow.className = "section-kicker";
      eyebrow.textContent = "UPDATES";
      const title = document.createElement("h2");
      title.id = "updatesTitle";
      title.textContent = `${FRONTEND_VERSION} release notes`;
      const summary = document.createElement("p");
      summary.id = "updatesSummary";
      summary.className = "hint";
      summary.textContent = "Current public JO AI updates.";
      copy.appendChild(eyebrow);
      copy.appendChild(title);
      copy.appendChild(summary);
      card.setAttribute("aria-labelledby", title.id);

      const close = document.createElement("button");
      close.id = "updatesClose";
      close.type = "button";
      close.className = "btn small";
      close.textContent = "Back";

      head.appendChild(copy);
      head.appendChild(close);
      card.appendChild(head);

      const list = document.createElement("div");
      list.id = "updatesList";
      list.className = "updates-list";
      card.appendChild(list);
      modal.appendChild(card);
      document.body.appendChild(modal);
    }

    if (!byId("comingSoonModal")) {
      const modal = document.createElement("div");
      modal.id = "comingSoonModal";
      modal.className = "updates-modal";
      modal.hidden = true;
      modal.setAttribute("aria-hidden", "true");

      const card = document.createElement("section");
      card.className = "updates-card";
      card.setAttribute("role", "dialog");
      card.setAttribute("aria-modal", "true");
      card.tabIndex = -1;

      const head = document.createElement("div");
      head.className = "panel-head";

      const copy = document.createElement("div");
      const eyebrow = document.createElement("p");
      eyebrow.className = "section-kicker";
      eyebrow.textContent = "PAST CHATS";
      const title = document.createElement("h2");
      title.id = "comingSoonTitle";
      title.textContent = "Coming soon";
      copy.appendChild(eyebrow);
      copy.appendChild(title);
      card.setAttribute("aria-labelledby", title.id);

      const close = document.createElement("button");
      close.id = "comingSoonClose";
      close.type = "button";
      close.className = "btn small";
      close.textContent = "Close";

      const note = document.createElement("p");
      note.className = "hint";
      note.textContent = "Past chats here. Coming soon.";

      head.appendChild(copy);
      head.appendChild(close);
      card.appendChild(head);
      card.appendChild(note);
      modal.appendChild(card);
      document.body.appendChild(modal);
    }

    if (!byId("toast")) {
      const toast = document.createElement("div");
      toast.id = "toast";
      toast.className = "toast";
      toast.hidden = true;
      document.body.appendChild(toast);
    }

    collectElements();
    prepareManagedModals();
    mountVersionBadge();
    renderUpdatesPanel();
    syncUpdatesBackButton();
  }

  function bindGlobalUi() {
    if (elements.versionBadge) {
      elements.versionBadge.addEventListener("click", (event) => {
        openUpdatesModal(event.currentTarget);
      });
    }
    if (elements.updatesClose) {
      elements.updatesClose.addEventListener("click", closeUpdatesModal);
    }
    if (elements.comingSoonClose) {
      elements.comingSoonClose.addEventListener("click", closeComingSoonModal);
    }
    if (elements.updatesModal) {
      elements.updatesModal.addEventListener("click", (event) => {
        if (event.target === elements.updatesModal) {
          closeUpdatesModal();
        }
      });
    }
    if (elements.comingSoonModal) {
      elements.comingSoonModal.addEventListener("click", (event) => {
        if (event.target === elements.comingSoonModal) {
          closeComingSoonModal();
        }
      });
    }
    if (elements.copyReferralCodeBtn) {
      elements.copyReferralCodeBtn.addEventListener("click", async () => {
        const code = elements.referralCode ? String(elements.referralCode.textContent || "").trim() : "";
        if (!code || code === "-") {
          showToast("Referral code is not ready yet.", "error");
          return;
        }
        try {
          await copyText(code);
          showToast("Referral code copied.");
        } catch (error) {
          showToast(error instanceof Error ? error.message : "Copy failed.", "error");
        }
      });
    }
    if (elements.copyReferralLinkBtn) {
      elements.copyReferralLinkBtn.addEventListener("click", async () => {
        const link = elements.referralMiniappLink ? String(elements.referralMiniappLink.textContent || "").trim() : "";
        if (!link || link === "-") {
          showToast("Referral link is not ready yet.", "error");
          return;
        }
        try {
          await copyText(link);
          showToast("Referral link copied.");
        } catch (error) {
          showToast(error instanceof Error ? error.message : "Copy failed.", "error");
        }
      });
    }
    document.addEventListener("keydown", handleActiveModalKeydown);
    document.addEventListener("focusin", handleActiveModalFocus);
  }

  function openUpdatesModal(trigger = null) {
    if (elements.updatesModal) {
      syncUpdatesBackButton();
      openManagedModal(elements.updatesModal, trigger);
    }
  }

  function closeUpdatesModal() {
    if (elements.updatesModal) {
      closeManagedModal(elements.updatesModal);
    }
  }

  function openComingSoonModal(trigger = null) {
    if (elements.comingSoonModal) {
      openManagedModal(elements.comingSoonModal, trigger);
    }
  }

  function closeComingSoonModal() {
    if (elements.comingSoonModal) {
      closeManagedModal(elements.comingSoonModal);
    }
  }

  function setVersionBadge() {
    if (elements.versionBadge) {
      const version = getDisplayedWebVersion();
      elements.versionBadge.textContent = `${version} updates`;
      elements.versionBadge.setAttribute("aria-label", `Open release notes for ${version}`);
    }
    mountVersionBadge();
    renderUpdatesPanel();
    syncUpdatesBackButton();
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

  function copyText(text) {
    const value = String(text || "").trim();
    if (!value) {
      return Promise.reject(new Error("Nothing to copy yet."));
    }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(value);
    }

    return new Promise((resolve, reject) => {
      const buffer = document.createElement("textarea");
      buffer.value = value;
      buffer.setAttribute("readonly", "");
      buffer.style.position = "fixed";
      buffer.style.left = "-9999px";
      document.body.appendChild(buffer);
      buffer.select();
      const copied = typeof document.execCommand === "function" && document.execCommand("copy");
      document.body.removeChild(buffer);
      if (copied) {
        resolve();
      } else {
        reject(new Error("Copy failed."));
      }
    });
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

  function syncOutputButtons() {
    if (elements.copyBtn) {
      elements.copyBtn.disabled = state.isBusy || !state.lastOutputText;
    }
    if (elements.downloadImageBtn) {
      const config = currentTool();
      if (config && (config.supportsImageSave || config.supportsCodeSave || config.supportsAudioSave)) {
        elements.downloadImageBtn.hidden = false;
        const canSaveImage = Boolean(config.supportsImageSave && state.lastImageDataUrl);
        const canSaveAudio = Boolean(config.supportsAudioSave && state.lastAudioDataUrl);
        const canSaveCode = Boolean(config.supportsCodeSave && state.lastCodeFileDataUrl);
        elements.downloadImageBtn.disabled = state.isBusy || (!canSaveImage && !canSaveAudio && !canSaveCode);
        elements.downloadImageBtn.textContent = canSaveCode ? "Save Code" : canSaveAudio ? "Save Audio" : "Save";
      } else {
        elements.downloadImageBtn.hidden = true;
      }
    }
  }

  function setBusy(busy) {
    state.isBusy = busy;
    if (elements.clearBtn) {
      elements.clearBtn.disabled = busy;
    }

    clearInterval(state.loadingTimer);
    state.loadingTimer = null;

    if (busy) {
      state.loadingIndex = 0;
      setApiState("working", "muted");
      setLoadingHint(loadingMessages[0]);
      updatePendingText(loadingMessages[0]);
      state.loadingTimer = setInterval(() => {
        state.loadingIndex = (state.loadingIndex + 1) % loadingMessages.length;
        const nextText = loadingMessages[state.loadingIndex];
        setLoadingHint(nextText);
        updatePendingText(nextText);
      }, 850);
    } else {
      setLoadingHint("Ready when you are.");
    }

    updateSendButtonState();
    syncOutputButtons();
  }

  function initTelegram() {
    try {
      if (bootDebug && typeof bootDebug.applyTheme === "function") {
        bootDebug.applyTheme();
      }

      if (!isTelegramMiniApp()) {
        setUserInfo("Guest mode");
        if (elements.welcomeMessage) {
          elements.welcomeMessage.textContent = "Clean, free, fast, and flexible JO AI tools are ready in browser mode.";
        }
        return;
      }

      const firstName =
        (tg.initDataUnsafe &&
          tg.initDataUnsafe.user &&
          typeof tg.initDataUnsafe.user.first_name === "string" &&
          tg.initDataUnsafe.user.first_name) ||
        "there";

      setUserInfo(`Hi ${firstName}`);
      if (elements.welcomeMessage) {
        elements.welcomeMessage.textContent = `Welcome, ${firstName}. Free, fast, and flexible JO AI tools are ready.`;
      }
    } catch (error) {
      reportStartupError("initTelegram", error);
      setUserInfo("Guest mode");
    }
  }

  function buildSupportNote() {
    const parts = [
      "JO AI mini app support note",
      `time_utc=${new Date().toISOString()}`,
      `page=${getPage()}`,
      getToolId() ? `tool=${getToolId()}` : "",
      `version=${getDisplayedWebVersion()}`,
      `status=${elements.status ? elements.status.textContent : "unknown"}`,
      `user_agent=${navigator.userAgent}`,
    ];
    return parts.filter(Boolean).join("\n");
  }

  function configureSupportActions() {
    const querySupport = normalizeSupportUrl(getQueryParam("support_url"));
    const configuredSupport = normalizeSupportUrl(window.JO_SUPPORT_URL);
    const supportUrl = querySupport || configuredSupport;
    if (supportUrl && elements.contactBtn) {
      elements.contactBtn.href = supportUrl;
    }

    if (elements.reportBtn) {
      elements.reportBtn.addEventListener("click", async () => {
        try {
          await copyText(buildSupportNote());
          showToast("Support note copied.");
        } catch (error) {
          showToast(error instanceof Error ? error.message : "Could not copy support note.", "error");
        }
      });
    }
  }
  function escapeHtml(input) {
    return String(input || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function renderTextBlock(text) {
    const fragment = document.createDocumentFragment();
    const lines = String(text || "").split(/\r?\n/);
    let list = null;
    let listType = "";

    const flushList = () => {
      if (list) {
        fragment.appendChild(list);
        list = null;
        listType = "";
      }
    };

    for (const rawLine of lines) {
      const line = rawLine.trimEnd();
      if (!line.trim()) {
        flushList();
        continue;
      }

      const headingMatch = line.match(/^(#{1,3})\s+(.+)$/);
      const bulletMatch = line.match(/^[-*+]\s+(.+)$/);
      const numberMatch = line.match(/^\d+\.\s+(.+)$/);

      if (headingMatch) {
        flushList();
        const heading = document.createElement(headingMatch[1].length === 1 ? "h3" : "h4");
        heading.innerHTML = escapeHtml(headingMatch[2]);
        fragment.appendChild(heading);
        continue;
      }

      if (bulletMatch) {
        if (!list || listType !== "ul") {
          flushList();
          list = document.createElement("ul");
          listType = "ul";
        }
        const item = document.createElement("li");
        item.innerHTML = escapeHtml(bulletMatch[1]);
        list.appendChild(item);
        continue;
      }

      if (numberMatch) {
        if (!list || listType !== "ol") {
          flushList();
          list = document.createElement("ol");
          listType = "ol";
        }
        const item = document.createElement("li");
        item.innerHTML = escapeHtml(numberMatch[1]);
        list.appendChild(item);
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
    const wrapper = document.createElement("section");
    wrapper.className = "code-block";

    const head = document.createElement("header");
    head.className = "code-head";

    const label = document.createElement("span");
    label.textContent = "code";

    const copy = document.createElement("button");
    copy.type = "button";
    copy.textContent = "Copy code";
    copy.addEventListener("click", async () => {
      try {
        await copyText(segment);
        showToast("Code copied.");
      } catch (error) {
        showToast(error instanceof Error ? error.message : "Copy failed.", "error");
      }
    });

    const pre = document.createElement("pre");
    const code = document.createElement("code");
    code.textContent = segment.replace(/^\n+|\n+$/g, "");
    pre.appendChild(code);

    head.appendChild(label);
    head.appendChild(copy);
    wrapper.appendChild(head);
    wrapper.appendChild(pre);
    return wrapper;
  }

  function renderRichText(container, text) {
    const target = container || document.createElement("div");
    target.innerHTML = "";
    const raw = String(text || "").trim();
    if (!raw) {
      return target;
    }

    const segments = raw.split(/```/);
    segments.forEach((segment, index) => {
      if (!segment.trim()) {
        return;
      }
      if (index % 2 === 1) {
        target.appendChild(buildCodeBlock(segment));
      } else {
        target.appendChild(renderTextBlock(segment));
      }
    });

    return target;
  }

  function normalizeImageUrl(rawImage) {
    const value = String(rawImage || "").trim();
    if (!value) {
      return "";
    }
    if (/^https?:\/\//i.test(value)) {
      return value;
    }
    if (value.startsWith("data:image")) {
      return value;
    }
    return `data:image/png;base64,${value.replace(/\s+/g, "")}`;
  }

  function normalizeCodeFileUrl(rawBase64) {
    const value = String(rawBase64 || "").trim();
    if (!value) {
      return "";
    }
    return `data:text/plain;base64,${value.replace(/\s+/g, "")}`;
  }

  function normalizeAudioUrl(rawAudio, mimeType = "audio/mpeg") {
    const value = String(rawAudio || "").trim();
    if (!value) {
      return "";
    }
    if (/^https?:\/\//i.test(value)) {
      return value;
    }
    if (value.startsWith("data:audio")) {
      return value;
    }
    const normalizedMime = String(mimeType || "audio/mpeg").trim() || "audio/mpeg";
    return `data:${normalizedMime};base64,${value.replace(/\s+/g, "")}`;
  }

  function formatTime(timestamp) {
    try {
      return new Date(timestamp || Date.now()).toLocaleTimeString([], {
        hour: "numeric",
        minute: "2-digit",
      });
    } catch (_error) {
      return "";
    }
  }

  function createMessageElement(entry) {
    const item = document.createElement("article");
    item.className = `message ${entry.role}${entry.pending ? " pending" : ""}`;
    item.dataset.messageId = entry.id;

    const avatar = document.createElement("div");
    avatar.className = "message-avatar";
    avatar.textContent = entry.role === "user" ? "You" : "JO";

    const bubble = document.createElement("div");
    bubble.className = "message-bubble";

    const head = document.createElement("div");
    head.className = "message-head";

    const role = document.createElement("span");
    role.className = "message-role";
    role.textContent = entry.role === "user" ? "You" : "JO AI";

    const meta = document.createElement("div");
    meta.className = "message-meta";
    meta.textContent = formatTime(entry.timestamp);

    head.appendChild(role);
    head.appendChild(meta);

    if (entry.role === "assistant" && !entry.pending && entry.text) {
      const copy = document.createElement("button");
      copy.type = "button";
      copy.className = "bubble-copy";
      copy.textContent = "Copy";
      copy.addEventListener("click", async () => {
        try {
          await copyText(entry.text);
          showToast("Response copied.");
        } catch (error) {
          showToast(error instanceof Error ? error.message : "Copy failed.", "error");
        }
      });
      head.appendChild(copy);
    }

    const body = document.createElement("div");
    body.className = "message-body";

    if (entry.note) {
      const note = document.createElement("p");
      note.className = "message-note";
      note.textContent = entry.note;
      body.appendChild(note);
    }

    if (entry.pending) {
      const pending = document.createElement("div");
      pending.className = "thinking-indicator";

      const dots = document.createElement("div");
      dots.className = "thinking-dots";
      for (let index = 0; index < 3; index += 1) {
        const dot = document.createElement("span");
        dots.appendChild(dot);
      }

      const pendingText = document.createElement("p");
      pendingText.className = "pending-text";
      pendingText.textContent = entry.text || loadingMessages[0];

      pending.appendChild(dots);
      pending.appendChild(pendingText);
      body.appendChild(pending);
    } else {
      renderRichText(body, entry.text);
    }

    if (entry.codeFileDataUrl) {
      const download = document.createElement("a");
      download.className = "btn small";
      download.href = entry.codeFileDataUrl;
      download.download = entry.codeFileName || "output.txt";
      download.textContent = `Download ${entry.codeFileName || "code file"}`;
      body.appendChild(download);
    }

    if (entry.audioDataUrl) {
      const audio = document.createElement("audio");
      audio.className = "message-audio";
      audio.controls = true;
      audio.preload = "metadata";
      audio.src = entry.audioDataUrl;
      body.appendChild(audio);
    }

    if (entry.imageDataUrl) {
      const image = document.createElement("img");
      image.className = "message-image";
      image.alt = "Generated image";
      image.src = entry.imageDataUrl;
      body.appendChild(image);
    }

    bubble.appendChild(head);
    bubble.appendChild(body);
    item.appendChild(avatar);
    item.appendChild(bubble);
    return item;
  }

  function getHistoryKey() {
    return `${HISTORY_PREFIX}${getToolId()}`;
  }

  function persistHistory() {
    if (!getToolId()) {
      return;
    }
    const serializable = state.history
      .filter((entry) => !entry.pending)
      .slice(-MAX_HISTORY_ITEMS)
      .map((entry) => {
        if (!entry || typeof entry !== "object") {
          return entry;
        }
        const normalized = { ...entry };
        if (normalized.codeFileDataUrl) {
          normalized.codeFileDataUrl = "";
        }
        if (normalized.audioDataUrl) {
          normalized.audioDataUrl = "";
        }
        return normalized;
      });
    safeStorageSet(getSessionStorage(), getHistoryKey(), JSON.stringify(serializable));
  }

  function loadHistory() {
    const raw = safeStorageGet(getSessionStorage(), getHistoryKey());
    if (!raw) {
      state.history = [];
      return;
    }

    try {
      const parsed = JSON.parse(raw);
      state.history = Array.isArray(parsed) ? parsed : [];
    } catch (_error) {
      state.history = [];
    }
  }

  function updateLatestOutputFromHistory() {
    const latestAssistant = [...state.history].reverse().find((entry) => entry.role === "assistant" && !entry.pending);
    state.lastOutputText = latestAssistant && latestAssistant.text ? latestAssistant.text : "";
    state.lastImageDataUrl = latestAssistant && latestAssistant.imageDataUrl ? latestAssistant.imageDataUrl : "";
    state.lastAudioDataUrl = latestAssistant && latestAssistant.audioDataUrl ? latestAssistant.audioDataUrl : "";
    state.lastAudioFileName = latestAssistant && latestAssistant.audioFileName ? latestAssistant.audioFileName : "";
    state.lastCodeFileDataUrl = latestAssistant && latestAssistant.codeFileDataUrl ? latestAssistant.codeFileDataUrl : "";
    state.lastCodeFileName = latestAssistant && latestAssistant.codeFileName ? latestAssistant.codeFileName : "";
  }

  function renderHistory() {
    if (!elements.historyList) {
      return;
    }

    elements.historyList.innerHTML = "";
    if (!state.history.length) {
      elements.historyList.innerHTML = state.emptyTemplate;
      state.lastOutputText = "";
      state.lastImageDataUrl = "";
      state.lastAudioDataUrl = "";
      state.lastAudioFileName = "";
      state.lastCodeFileDataUrl = "";
      state.lastCodeFileName = "";
      syncOutputButtons();
      return;
    }

    for (const entry of state.history) {
      elements.historyList.appendChild(createMessageElement(entry));
    }

    updateLatestOutputFromHistory();
    syncOutputButtons();
    scheduleFrame(() => {
      scrollHistoryToBottom(true);
    });
  }

  function pushHistory(entry, persist = true) {
    state.history.push(entry);
    if (persist) {
      persistHistory();
    }
    renderHistory();
  }

  function insertPendingMessage() {
    state.pendingId = createId();
    pushHistory(
      {
        id: state.pendingId,
        role: "assistant",
        text: loadingMessages[0],
        pending: true,
        timestamp: Date.now(),
      },
      false
    );
  }

  function updatePendingText(text) {
    if (!state.pendingId) {
      return;
    }
    const pendingEntry = state.history.find((entry) => entry.id === state.pendingId);
    if (!pendingEntry) {
      return;
    }
    pendingEntry.text = text;
    const node = elements.historyList && elements.historyList.querySelector(`[data-message-id="${state.pendingId}"] .pending-text`);
    if (node) {
      node.textContent = text;
    }
  }

  function replacePendingMessage(entry) {
    const index = state.history.findIndex((item) => item.id === state.pendingId);
    if (index >= 0) {
      state.history[index] = entry;
    } else {
      state.history.push(entry);
    }
    state.pendingId = "";
    persistHistory();
    renderHistory();
  }

  function clearKimiPreview() {
    if (state.kimiPreviewUrl && window.URL && typeof window.URL.revokeObjectURL === "function") {
      URL.revokeObjectURL(state.kimiPreviewUrl);
      state.kimiPreviewUrl = "";
    }
    if (elements.kimiPreview) {
      elements.kimiPreview.removeAttribute("src");
    }
    if (elements.kimiPreviewWrap) {
      elements.kimiPreviewWrap.hidden = true;
    }
  }

  function removeComposerExampleRow() {
    const row = document.querySelector(".composer-meta");
    if (row) {
      row.remove();
    }
    elements.useExampleBtn = null;
    elements.toolExample = null;
  }

  function clearToolWorkspace() {
    state.history = [];
    state.pendingId = "";
    state.lastOutputText = "";
    state.lastImageDataUrl = "";
    state.lastAudioDataUrl = "";
    state.lastAudioFileName = "";
    state.lastCodeFileDataUrl = "";
    state.lastCodeFileName = "";
    persistHistory();
    renderHistory();

    if (elements.aiInput) {
      elements.aiInput.value = "";
      resizeComposerInput(true);
    }
    if (elements.promptType) {
      const config = currentTool();
      elements.promptType.value = config && config.defaultPromptType ? config.defaultPromptType : "";
    }
    if (elements.codeFile) {
      elements.codeFile.value = "";
    }
    if (elements.codeFileInfo) {
      elements.codeFileInfo.textContent = "No code file selected.";
    }
    if (elements.imageType) {
      elements.imageType.selectedIndex = 0;
    }
    if (elements.imageRatio) {
      elements.imageRatio.value = "1:1";
    }
    if (elements.ttsLanguage) {
      elements.ttsLanguage.value = "en";
    }
    if (elements.ttsVoice) {
      elements.ttsVoice.value = "female";
    }
    if (elements.ttsEmotion) {
      elements.ttsEmotion.value = "natural";
    }
    if (elements.kimiImage) {
      elements.kimiImage.value = "";
    }
    if (elements.uploadInfo) {
      elements.uploadInfo.textContent = "No image selected.";
    }
    clearKimiPreview();
    setApiState("idle", "muted");
    setLoadingHint("Ready when you are.");
    updateSendButtonState();
    syncOutputButtons();
    scrollHistoryToBottom(true);
  }
  function delay(ms) {
    const waitMs = Math.max(0, Number(ms) || 0);
    return new Promise((resolve) => {
      setTimeout(resolve, waitMs);
    });
  }

  function isTimeoutMessage(message) {
    return /longer than expected|timed out|timeout/i.test(String(message || ""));
  }

  function isLikelyNetworkMessage(message) {
    return /failed to fetch|network|load failed|internet|connection|disconnected/i.test(String(message || ""));
  }

  function extractBackendErrorMessage(data, statusCode) {
    const fallback = `Request failed with status ${statusCode}.`;
    if (!data || typeof data !== "object") {
      return fallback;
    }

    const candidates = [data.error, data.message, data.reason, data.detail, data.warning];
    for (const candidate of candidates) {
      if (typeof candidate === "string" && candidate.trim()) {
        const requestId = typeof data.request_id === "string" ? data.request_id.trim() : "";
        return requestId ? `${candidate.trim()} (request ${requestId})` : candidate.trim();
      }
    }

    if (Array.isArray(data.detail) && data.detail.length) {
      const first = data.detail[0];
      if (first && typeof first.msg === "string" && first.msg.trim()) {
        return first.msg.trim();
      }
    }
    return fallback;
  }

  function summarizePayloadForLog(payload) {
    const message = typeof payload.message === "string" ? payload.message : "";
    return {
      keys: Object.keys(payload || {}),
      message_length: message.length,
      has_code_file: Boolean(payload && payload.code_file_base64),
      has_image: Boolean(payload && payload.image_base64),
    };
  }

  async function fetchJsonWithTimeout(url, options, timeoutMs = 60000) {
    if (typeof fetch !== "function") {
      throw new Error("This Telegram webview cannot make network requests.");
    }

    const method = (options && options.method) || "GET";
    const startedAt = Date.now();
    console.info("[JO AI Mini App] request.dispatch", { method, url, timeout_ms: timeoutMs });

    const controller = typeof AbortController === "function" ? new AbortController() : null;
    let timer = 0;
    try {
      const request = fetch(url, controller ? { ...options, signal: controller.signal } : { ...options });
      const response = controller
        ? await (() => {
            timer = setTimeout(() => controller.abort(), timeoutMs);
            return request;
          })()
        : await Promise.race([
            request,
            new Promise((_resolve, reject) => {
              timer = setTimeout(() => reject(new Error("The assistant is taking longer than expected.")), timeoutMs);
            }),
          ]);
      const requestId = response && response.headers && typeof response.headers.get === "function"
        ? String(response.headers.get("x-request-id") || "").trim()
        : "";
      const rawText = await response.text();
      let data = {};
      if (rawText) {
        try {
          data = JSON.parse(rawText);
        } catch (_error) {
          console.warn("[JO AI Mini App] request.non_json_response", {
            method,
            url,
            status: response.status,
            request_id: requestId || undefined,
            body_preview: rawText.slice(0, 180),
          });
          if (response.ok) {
            throw new Error(
              requestId
                ? `The backend returned an unexpected response format (request ${requestId}).`
                : "The backend returned an unexpected response format."
            );
          }
        }
      }
      console.info("[JO AI Mini App] request.response", {
        method,
        url,
        status: response.status,
        request_id: requestId || undefined,
        duration_ms: Date.now() - startedAt,
      });
      return { response, data, rawText, requestId };
    } catch (error) {
      if (error && error.name === "AbortError") {
        throw new Error("The assistant is taking longer than expected.");
      }
      throw error;
    } finally {
      clearTimeout(timer);
    }
  }

  function shouldTrySameOriginApi() {
    if (!window.location.protocol.startsWith("http")) {
      return false;
    }
    return window.JO_USE_SAME_ORIGIN_API === true;
  }

  function buildApiBaseCandidates() {
    const queryBase = normalizeBase(getQueryParam("api_base"));
    const explicitBase = normalizeBase(window.JO_API_BASE);
    const storedBase = normalizeBase(safeStorageGet(getLocalStorage(), API_BASE_STORAGE_KEY));
    const sameOriginBase = shouldTrySameOriginApi() ? normalizeBase(window.location.origin) : "";

    if (queryBase) {
      safeStorageSet(getLocalStorage(), API_BASE_STORAGE_KEY, queryBase);
    }

    return unique([
      queryBase,
      explicitBase,
      storedBase,
      sameOriginBase,
    ]);
  }

  async function isApiHealthy(base) {
    const paths = ["/api/health"];
    for (const path of paths) {
      try {
        const { response, data } = await fetchJsonWithTimeout(`${base}${path}`, { method: "GET" }, 3500);
        if (response.ok && data && (data.ok === true || data.status === "ok")) {
          state.runtimeInfo = normalizeRuntimeInfo(data) || state.runtimeInfo;
          setVersionBadge();
          return true;
        }
      } catch (_error) {
        // try the next path
      }
    }
    return false;
  }

  async function resolveApiBase() {
    if (state.apiBase) {
      return state.apiBase;
    }

    setStatus("Checking studio...");
    const candidates = buildApiBaseCandidates();
    if (!candidates.length) {
      setStatus("Studio unavailable");
      return "";
    }

    for (const candidate of candidates) {
      const healthy = await isApiHealthy(candidate);
      if (healthy) {
        state.apiBase = candidate;
        safeStorageSet(getLocalStorage(), API_BASE_STORAGE_KEY, candidate);
        setStatus(getPage() === "home" ? "Studio ready" : "Assistant ready");
        return candidate;
      }
    }

    state.apiBase = candidates[0];
    setStatus("Studio may be waking up");
    return state.apiBase;
  }

  function referralClaimStorageKey(tracking) {
    const userPart = tracking && tracking.telegram_id ? String(tracking.telegram_id) : "anon";
    return `${REFERRAL_CLAIMED_PREFIX}${userPart}`;
  }

  function ownReferralCodeForUser(tracking) {
    if (!tracking || !tracking.telegram_id) {
      return "";
    }
    const numericId = Number.parseInt(String(tracking.telegram_id), 10);
    if (!Number.isFinite(numericId) || numericId <= 0) {
      return "";
    }
    return `jo${numericId.toString(16)}`;
  }

  function setReferralStatus(text, isError = false) {
    if (!elements.referralStatus) {
      return;
    }
    elements.referralStatus.textContent = String(text || "");
    elements.referralStatus.style.color = isError ? "#b42318" : "";
  }

  async function claimReferralIfNeeded(apiBase) {
    const referralCode = resolveReferralCode();
    if (!apiBase || !referralCode) {
      return;
    }

    const tracking = buildTrackingPayloadFields();
    if (!tracking.telegram_id) {
      return;
    }

    const ownCode = sanitizeReferralCode(ownReferralCodeForUser(tracking));
    if (ownCode && ownCode === sanitizeReferralCode(referralCode)) {
      return;
    }

    const local = getLocalStorage();
    const claimKey = referralClaimStorageKey(tracking);
    const alreadyClaimed = sanitizeReferralCode(safeStorageGet(local, claimKey));
    if (alreadyClaimed === sanitizeReferralCode(referralCode)) {
      return;
    }

    try {
      const { response } = await fetchJsonWithTimeout(
        `${apiBase}/api/referral/claim`,
        {
          method: "POST",
          headers: buildTrackingHeaders(),
          body: JSON.stringify({
            ...tracking,
            frontend_source: "mini_app",
            referral_code: referralCode,
          }),
        },
        8000
      );
      if (response && response.ok) {
        safeStorageSet(local, claimKey, referralCode);
      }
    } catch (_error) {
      // Non-blocking: do not break page load if referral claim fails.
    }
  }

  async function loadReferralCard(apiBase) {
    if (!elements.referralCard) {
      return;
    }
    elements.referralCard.hidden = false;

    const tracking = buildTrackingPayloadFields();
    if (!tracking.telegram_id) {
      setReferralStatus("Open from Telegram to load your personal referral links.");
      return;
    }

    if (!apiBase) {
      setReferralStatus("Referral links are unavailable while the backend is waking up.");
      return;
    }

    try {
      await claimReferralIfNeeded(apiBase);
      const { response, data } = await fetchJsonWithTimeout(
        `${apiBase}/api/referral/me`,
        {
          method: "GET",
          headers: buildTrackingHeaders(),
        },
        8000
      );
      if (!response || !response.ok || !data || data.ok !== true) {
        throw new Error("Referral API unavailable");
      }

      const code = sanitizeReferralCode(data.referral_code);
      state.referralCode = code || state.referralCode;
      if (code) {
        safeStorageSet(getLocalStorage(), REFERRAL_STORAGE_KEY, code);
      }

      if (elements.referralCode) {
        elements.referralCode.textContent = code || "-";
      }
      if (elements.referralTelegramLink) {
        elements.referralTelegramLink.textContent = data.telegram_link || "-";
        elements.referralTelegramLink.href = data.telegram_link || "#";
      }
      if (elements.referralMiniappLink) {
        elements.referralMiniappLink.textContent = data.miniapp_link || "-";
        elements.referralMiniappLink.href = data.miniapp_link || "#";
      }
      setReferralStatus("Referral links ready.");
    } catch (_error) {
      setReferralStatus("Could not load referral links right now.", true);
    }
  }

  function endpointAttempts(mode, payload) {
    const basePayload = { ...payload };
    const trackingFields = {};
    for (const key of ["telegram_id", "username", "first_name", "last_name", "frontend_source"]) {
      if (Object.prototype.hasOwnProperty.call(basePayload, key) && basePayload[key] !== undefined) {
        trackingFields[key] = basePayload[key];
      }
    }

    if (mode === "chat") {
      return [
        {
          path: "/api/ai",
          payload: { ...trackingFields, mode: "chat", message: basePayload.message },
        },
        { path: "/api/chat", payload: basePayload },
      ];
    }
    if (mode === "gemini") {
      return [
        { path: "/api/gemini", payload: basePayload },
        { path: "/gemini", payload: basePayload },
      ];
    }
    if (mode === "code") {
      const codePayload = { ...trackingFields, mode: "code", message: basePayload.message };
      if (basePayload.code_file_name && basePayload.code_file_base64) {
        codePayload.code_file_name = basePayload.code_file_name;
        codePayload.code_file_base64 = basePayload.code_file_base64;
      }
      return [
        { path: "/api/ai", payload: codePayload },
        { path: "/ai", payload: codePayload },
        { path: "/api/code", payload: basePayload },
        { path: "/code", payload: basePayload },
      ];
    }
    if (mode === "deepseek") {
      return [
        {
          path: "/api/ai",
          payload: { ...trackingFields, mode: "deep_analysis", message: basePayload.message },
        },
        {
          path: "/ai",
          payload: { ...trackingFields, mode: "deep_analysis", message: basePayload.message },
        },
        {
          path: "/api/ai",
          payload: { ...trackingFields, mode: "research", message: basePayload.message },
        },
        { path: "/api/research", payload: basePayload },
        { path: "/research", payload: basePayload },
      ];
    }
    if (mode === "research") {
      return [
        {
          path: "/api/ai",
          payload: { ...trackingFields, mode: "research", message: basePayload.message },
        },
        {
          path: "/ai",
          payload: { ...trackingFields, mode: "research", message: basePayload.message },
        },
        { path: "/api/research", payload: basePayload },
        { path: "/research", payload: basePayload },
      ];
    }
    if (mode === "prompt") {
      return [
        {
          path: "/api/ai",
          payload: {
            ...trackingFields,
            mode: "prompt",
            message: basePayload.message,
            prompt_type: basePayload.prompt_type || "general",
          },
        },
        {
          path: "/ai",
          payload: {
            ...trackingFields,
            mode: "prompt",
            message: basePayload.message,
            prompt_type: basePayload.prompt_type || "general",
          },
        },
        { path: "/api/prompt", payload: basePayload },
        { path: "/prompt", payload: basePayload },
      ];
    }
    if (mode === "tts") {
      return [
        { path: "/api/tts", payload: basePayload },
        { path: "/tts", payload: basePayload },
      ];
    }
    if (mode === "image") {
      return [
        { path: "/api/image", payload: basePayload },
        { path: "/image", payload: basePayload },
      ];
    }

    return [
      { path: "/api/vision", payload: basePayload },
      { path: "/vision", payload: basePayload },
    ];
  }

  function requestTimeoutMsForMode(mode) {
    if (mode === "image") {
      return 120000;
    }
    if (mode === "gemini") {
      return 90000;
    }
    if (mode === "code" || mode === "research" || mode === "deepseek") {
      return 110000;
    }
    if (mode === "tts") {
      return 90000;
    }
    if (mode === "kimi") {
      return 90000;
    }
    return 70000;
  }

  async function requestWithFallback(mode, payload) {
    const apiBase = await resolveApiBase();
    if (!apiBase) {
      throw new Error("The assistant is not ready yet.");
    }

    let timedOut = false;
    let sawNetworkIssue = false;
    let lastServerMessage = "";
    let lastRequestId = "";
    const diagnostics = [];
    const trackingHeaders = buildTrackingHeaders();
    const shouldTryMinimalHeaders = Object.keys(trackingHeaders).length > 1;
    const attempts = endpointAttempts(mode, payload);
    const timeoutMs = requestTimeoutMsForMode(mode);
    const payloadSummary = summarizePayloadForLog(payload);
    console.info("[JO AI Mini App] request.start", {
      mode,
      api_base: apiBase,
      attempt_count: attempts.length,
      payload: payloadSummary,
      header_keys: Object.keys(trackingHeaders),
    });

    for (const attempt of attempts) {
      const targetUrl = `${apiBase}${attempt.path}`;
      const headerVariants = shouldTryMinimalHeaders
        ? [
            { name: "tracking", headers: { ...trackingHeaders } },
            { name: "minimal", headers: { "Content-Type": "application/json" } },
          ]
        : [{ name: "tracking", headers: { ...trackingHeaders } }];

      let skipToNextEndpoint = false;
      for (const variant of headerVariants) {
        if (skipToNextEndpoint) {
          break;
        }

        for (let tryIndex = 0; tryIndex < 2; tryIndex += 1) {
          const startedAt = Date.now();
          try {
            const { response, data, requestId } = await fetchJsonWithTimeout(
              targetUrl,
              {
                method: "POST",
                headers: { ...variant.headers },
                body: JSON.stringify(attempt.payload),
              },
              timeoutMs
            );

            const elapsedMs = Date.now() - startedAt;
            const backendMessage = extractBackendErrorMessage(data, response.status);
            diagnostics.push({
              path: attempt.path,
              header_variant: variant.name,
              try_index: tryIndex,
              status: response.status,
              request_id: requestId || "",
              duration_ms: elapsedMs,
              message: backendMessage,
            });

            if (response.ok) {
              console.info("[JO AI Mini App] request.success", {
                mode,
                path: attempt.path,
                header_variant: variant.name,
                request_id: requestId || undefined,
                duration_ms: elapsedMs,
              });
              const payloadData = data && typeof data === "object" ? data : {};
              return {
                ...payloadData,
                _request_id: requestId || (typeof payloadData.request_id === "string" ? payloadData.request_id : ""),
                _endpoint: attempt.path,
              };
            }

            if (requestId) {
              lastRequestId = requestId;
            }
            if (backendMessage) {
              lastServerMessage = backendMessage;
            }

            console.warn("[JO AI Mini App] request.http_error", {
              mode,
              path: attempt.path,
              status: response.status,
              request_id: requestId || undefined,
              header_variant: variant.name,
              message: backendMessage,
            });

            if ([404, 405, 501].includes(response.status)) {
              skipToNextEndpoint = true;
              break;
            }

            if (response.status >= 500 || response.status === 408 || response.status === 429) {
              break;
            }

            throw new Error(backendMessage || `Request failed with status ${response.status}.`);
          } catch (error) {
            const message = error instanceof Error ? error.message : String(error);
            const timeoutHit = isTimeoutMessage(message);
            const networkHit = isLikelyNetworkMessage(message);
            timedOut = timedOut || timeoutHit;
            sawNetworkIssue = sawNetworkIssue || networkHit;

            diagnostics.push({
              path: attempt.path,
              header_variant: variant.name,
              try_index: tryIndex,
              status: "request_error",
              request_id: "",
              duration_ms: Date.now() - startedAt,
              message,
            });

            console.error("[JO AI Mini App] request.error", {
              mode,
              path: attempt.path,
              header_variant: variant.name,
              try_index: tryIndex,
              message,
            });

            const retryable = tryIndex === 0 && (timeoutHit || networkHit);
            if (retryable) {
              await delay(220);
              continue;
            }
            break;
          }
        }
      }
    }

    let userMessage = "";
    if (timedOut) {
      userMessage = "The assistant is taking longer than expected. Please try again.";
    } else if (sawNetworkIssue) {
      userMessage =
        "Could not reach the JO AI backend from this Telegram client. Check your connection and reopen the mini app.";
    } else if (lastServerMessage) {
      userMessage = lastServerMessage;
    } else {
      userMessage = "The assistant could not complete this request right now.";
    }
    if (lastRequestId && !userMessage.includes("request ")) {
      userMessage = `${userMessage} (request ${lastRequestId})`;
    }

    const finalError = new Error(userMessage);
    finalError.details = diagnostics;
    throw finalError;
  }
  function applyToolConfig() {
    const config = currentTool();
    if (!config) {
      return;
    }

    const toolDescription = ensureToolDescriptionElement();
    elements.toolDescription = toolDescription;

    document.title = `${config.title} | JO AI Chat Bot`;
    if (elements.toolTitle) {
      elements.toolTitle.textContent = config.title;
    }
    if (toolDescription) {
      toolDescription.textContent = config.description;
    }
    if (elements.toolLead) {
      elements.toolLead.textContent = config.lead;
    }
    if (elements.toolExample) {
      elements.toolExample.textContent = config.example;
    }
    if (elements.inputLabel) {
      elements.inputLabel.textContent = config.label;
    }
    if (elements.aiInput) {
      elements.aiInput.placeholder = config.placeholder;
      elements.aiInput.rows = config.rows;
    }
    if (elements.historyTitle) {
      elements.historyTitle.textContent = config.historyTitle;
    }
    if (elements.emptyState) {
      elements.emptyState.innerHTML = `
        <div class="empty-state-mark" aria-hidden="true">JO</div>
        <h3>${escapeHtml(config.emptyTitle || "Ask Joe AI chatbot")}</h3>
        <p>${escapeHtml(config.emptyCopy || "Fast help for ideas, questions, and tasks.")}</p>
      `;
    }
    if (elements.promptTypeWrap) {
      elements.promptTypeWrap.hidden = !config.needsPromptType;
      const promptTypeLabel = elements.promptTypeWrap.querySelector("label");
      if (promptTypeLabel) {
        promptTypeLabel.textContent = config.promptTypeLabel || "Prompt type";
      }
    }
    if (elements.promptType) {
      elements.promptType.placeholder = config.promptTypePlaceholder || "e.g. assistant prompt";
      if (config.defaultPromptType && !elements.promptType.value.trim()) {
        elements.promptType.value = config.defaultPromptType;
      }
    }
    if (elements.imageTypeWrap) {
      elements.imageTypeWrap.hidden = !config.needsImageType;
    }
    if (elements.imageRatioWrap) {
      elements.imageRatioWrap.hidden = !config.needsImageRatio;
    }
    if (elements.imageRatio && config.defaultImageRatio && !elements.imageRatio.value) {
      elements.imageRatio.value = config.defaultImageRatio;
    }
    if (elements.ttsLanguageWrap) {
      elements.ttsLanguageWrap.hidden = !config.needsTtsLanguage;
    }
    if (elements.ttsLanguage && config.defaultTtsLanguage && !elements.ttsLanguage.value) {
      elements.ttsLanguage.value = config.defaultTtsLanguage;
    }
    if (elements.ttsVoiceWrap) {
      elements.ttsVoiceWrap.hidden = !config.needsTtsVoice;
    }
    if (elements.ttsVoice && config.defaultTtsVoice && !elements.ttsVoice.value) {
      elements.ttsVoice.value = config.defaultTtsVoice;
    }
    if (elements.ttsEmotionWrap) {
      elements.ttsEmotionWrap.hidden = !config.needsTtsEmotion;
    }
    if (elements.ttsEmotion && config.defaultTtsEmotion && !elements.ttsEmotion.value) {
      elements.ttsEmotion.value = config.defaultTtsEmotion;
    }
    if (elements.codeFileWrap) {
      elements.codeFileWrap.hidden = !config.needsCodeUpload;
    }
    if (elements.codeFileInfo && config.needsCodeUpload && !(elements.codeFile && elements.codeFile.files && elements.codeFile.files[0])) {
      elements.codeFileInfo.textContent = "No code file selected.";
    }
    if (elements.kimiImageWrap) {
      elements.kimiImageWrap.hidden = !config.needsUpload;
    }
    resizeComposerInput(true);
    updateSendButtonState();
  }

  function fillExample() {
    const config = currentTool();
    if (!config || !elements.aiInput) {
      return;
    }
    elements.aiInput.value = config.example;
    if (config.examplePromptType && elements.promptType) {
      elements.promptType.value = config.examplePromptType;
    } else if (config.defaultPromptType && elements.promptType) {
      elements.promptType.value = config.defaultPromptType;
    }
    if (config.exampleImageType && elements.imageType) {
      elements.imageType.value = config.exampleImageType;
    }
    if (config.exampleImageRatio && elements.imageRatio) {
      elements.imageRatio.value = config.exampleImageRatio;
    } else if (config.defaultImageRatio && elements.imageRatio) {
      elements.imageRatio.value = config.defaultImageRatio;
    }
    if (config.defaultTtsLanguage && elements.ttsLanguage) {
      elements.ttsLanguage.value = config.defaultTtsLanguage;
    }
    if (config.defaultTtsVoice && elements.ttsVoice) {
      elements.ttsVoice.value = config.defaultTtsVoice;
    }
    if (config.defaultTtsEmotion && elements.ttsEmotion) {
      elements.ttsEmotion.value = config.defaultTtsEmotion;
    }
    resizeComposerInput();
    updateSendButtonState();
    elements.aiInput.focus();
  }

  function updateKimiSelection() {
    const file = elements.kimiImage && elements.kimiImage.files ? elements.kimiImage.files[0] : null;
    if (!file) {
      if (elements.uploadInfo) {
        elements.uploadInfo.textContent = "No image selected.";
      }
      clearKimiPreview();
      return;
    }

    const sizeMb = (file.size / (1024 * 1024)).toFixed(2);
    if (elements.uploadInfo) {
      elements.uploadInfo.textContent = `${file.name} (${sizeMb} MB)`;
    }

    clearKimiPreview();
    if (
      elements.kimiPreview &&
      elements.kimiPreviewWrap &&
      window.URL &&
      typeof window.URL.createObjectURL === "function"
    ) {
      state.kimiPreviewUrl = URL.createObjectURL(file);
      elements.kimiPreview.src = state.kimiPreviewUrl;
      elements.kimiPreviewWrap.hidden = false;
    }
  }

  function isDebugIntent(text) {
    return /\b(debug|fix|error|exception|traceback|bug|issue|crash|failing|failure|broken|not working)\b/i.test(
      String(text || "")
    );
  }

  function updateCodeFileSelection() {
    const file = elements.codeFile && elements.codeFile.files ? elements.codeFile.files[0] : null;
    if (!elements.codeFileInfo) {
      return;
    }
    if (!file) {
      elements.codeFileInfo.textContent = "No code file selected.";
      return;
    }
    const sizeKb = Math.max(1, Math.round(file.size / 1024));
    elements.codeFileInfo.textContent = `${file.name} (${sizeKb} KB)`;
  }

  function fileToBase64(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => {
        const raw = String(reader.result || "");
        const comma = raw.indexOf(",");
        resolve(comma >= 0 ? raw.slice(comma + 1) : raw);
      };
      reader.onerror = () => reject(new Error("Could not read the image."));
      reader.readAsDataURL(file);
    });
  }

  async function buildRequestPayload() {
    const mode = getToolId();
    const message = elements.aiInput ? elements.aiInput.value.trim() : "";
    const payload = { message };

    if (mode !== "kimi" && !message) {
      throw new Error("Please enter a request first.");
    }

    if (mode === "prompt") {
      const promptType = elements.promptType ? elements.promptType.value.trim() : "";
      if (promptType) {
        payload.prompt_type = promptType;
      }
    }

    if (mode === "image") {
      payload.image_type = elements.imageType ? elements.imageType.value : "realistic";
      payload.ratio = elements.imageRatio ? elements.imageRatio.value : "1:1";
    }

    if (mode === "tts") {
      payload.text = message;
      payload.language = elements.ttsLanguage ? elements.ttsLanguage.value : "en";
      payload.voice = elements.ttsVoice ? elements.ttsVoice.value : "female";
      payload.emotion = elements.ttsEmotion ? elements.ttsEmotion.value : "natural";
    }

    if (mode === "code") {
      const file = elements.codeFile && elements.codeFile.files ? elements.codeFile.files[0] : null;
      if (file) {
        if (file.size > MAX_CODE_UPLOAD_BYTES) {
          throw new Error("Please use a code file smaller than 1.5MB.");
        }
        payload.code_file_name = file.name || "uploaded_code.txt";
        payload.code_file_base64 = await fileToBase64(file);
      }
      if (isDebugIntent(message) && !payload.code_file_base64) {
        throw new Error("For debug/fix requests, upload the code file first.");
      }
    }

    if (mode === "kimi") {
      const file = elements.kimiImage && elements.kimiImage.files ? elements.kimiImage.files[0] : null;
      if (!file) {
        throw new Error("Please upload an image first.");
      }
      if (!file.type.startsWith("image/")) {
        throw new Error("Please upload a valid image file.");
      }
      if (file.size > MAX_UPLOAD_BYTES) {
        throw new Error("Please use an image smaller than 8MB.");
      }
      payload.message = message || "Describe this image.";
      payload.image_base64 = await fileToBase64(file);
    }

    return { ...payload, ...buildTrackingPayloadFields() };
  }

  function buildUserEntry(payload) {
    const mode = getToolId();
    let note = "";
    if (mode === "prompt" && payload.prompt_type) {
      note = `Prompt type: ${payload.prompt_type}`;
    }
    if (mode === "image" && payload.image_type) {
      note = `Style: ${payload.image_type}`;
      if (payload.ratio) {
        note = `${note} | Ratio: ${payload.ratio}`;
      }
    }
    if (mode === "code" && payload.code_file_name) {
      note = `File: ${payload.code_file_name}`;
    }
    if (mode === "tts") {
      const lang = payload.language || "en";
      const voice = payload.voice || "female";
      const emotion = payload.emotion || "natural";
      note = `Language: ${lang} | Voice: ${voice} | Style: ${emotion}`;
    }
    if (mode === "kimi" && elements.kimiImage && elements.kimiImage.files && elements.kimiImage.files[0]) {
      note = `File: ${elements.kimiImage.files[0].name}`;
    }

    return {
      id: createId(),
      role: "user",
      text: payload.message,
      note,
      timestamp: Date.now(),
    };
  }

  function containsSensitiveRequest(payload) {
    const text = [
      payload && typeof payload.message === "string" ? payload.message : "",
      payload && typeof payload.prompt_type === "string" ? payload.prompt_type : "",
    ]
      .join("\n")
      .trim();

    if (!text) {
      return false;
    }

    if (instructionBypassPattern.test(text)) {
      return true;
    }
    if (extractionVerbsPattern.test(text) && sensitiveTargetsPattern.test(text)) {
      return true;
    }
    if (selfContextPattern.test(text) && (sensitiveTargetsPattern.test(text) || providerNamesPattern.test(text))) {
      return true;
    }
    return false;
  }

  async function submitTool(event) {
    if (event) {
      event.preventDefault();
    }
    if (state.isBusy) {
      return;
    }

    let payload;
    try {
      payload = await buildRequestPayload();
    } catch (error) {
      const message = error instanceof Error ? error.message : "Please complete the required fields.";
      if (/upload the code file first/i.test(message)) {
        pushHistory({
          id: createId(),
          role: "assistant",
          text: "For debug/fix requests, upload the code file first in Code Generator, then send your request.",
          timestamp: Date.now(),
        });
      }
      setApiState("needs input", "error");
      showToast(message, "error");
      return;
    }

    console.info("[JO AI Mini App] submit.start", {
      mode: getToolId(),
      payload: summarizePayloadForLog(payload),
    });

    pushHistory(buildUserEntry(payload));
    if (elements.aiInput) {
      elements.aiInput.value = "";
      resizeComposerInput(true);
      if (shouldDismissKeyboardAfterSubmit()) {
        elements.aiInput.blur();
        window.setTimeout(syncViewportState, 40);
      } else {
        elements.aiInput.focus();
      }
    }
    updateSendButtonState();
    if (containsSensitiveRequest(payload)) {
      const refusal = {
        id: createId(),
        role: "assistant",
        text: SAFE_INTERNAL_DETAILS_REFUSAL,
        timestamp: Date.now(),
      };
      state.lastOutputText = refusal.text;
      state.lastImageDataUrl = "";
      state.lastAudioDataUrl = "";
      state.lastAudioFileName = "";
      state.lastCodeFileDataUrl = "";
      state.lastCodeFileName = "";
      pushHistory(refusal);
      setApiState("ready", "success");
      showToast("Internal details are not shared.");
      return;
    }
    insertPendingMessage();
    setBusy(true);
    scrollHistoryToBottom(true);

    try {
      const data = await requestWithFallback(getToolId(), payload);
      if (data && typeof data.error === "string" && data.error.trim()) {
        throw new Error(data.error.trim());
      }

      const imageDataUrl = data && data.image_base64
        ? normalizeImageUrl(data.image_base64)
        : data && typeof data.image_url === "string" && data.image_url.trim()
          ? normalizeImageUrl(data.image_url)
          : "";
      const audioDataUrl =
        data && data.audio_base64
          ? normalizeAudioUrl(data.audio_base64, data.audio_mime_type || "audio/mpeg")
          : data && typeof data.audio_url === "string" && data.audio_url.trim()
            ? normalizeAudioUrl(data.audio_url, data.audio_mime_type || "audio/mpeg")
            : "";
      const audioFileName =
        data && typeof data.audio_file_name === "string" && data.audio_file_name.trim()
          ? data.audio_file_name.trim()
          : "";
      const codeFileDataUrl = data && data.code_file_base64 ? normalizeCodeFileUrl(data.code_file_base64) : "";
      const codeFileName =
        data && typeof data.code_file_name === "string" && data.code_file_name.trim() ? data.code_file_name.trim() : "";
      let text =
        (data && typeof data.output === "string" && data.output.trim()) ||
        (data && typeof data.warning === "string" && !imageDataUrl && data.warning.trim()) ||
        "";

      if (!text && imageDataUrl) {
        text = "Your image is ready.";
      }
      if (!text && audioDataUrl) {
        text = "Your audio is ready.";
      }
      if (!text) {
        text = "No output returned.";
      }

      state.lastOutputText = text;
      state.lastImageDataUrl = imageDataUrl;
      state.lastAudioDataUrl = audioDataUrl;
      state.lastAudioFileName = audioFileName;
      state.lastCodeFileDataUrl = codeFileDataUrl;
      state.lastCodeFileName = codeFileName;

      replacePendingMessage({
        id: createId(),
        role: "assistant",
        text,
        note:
          data &&
          typeof data.warning === "string" &&
          data.output &&
          data.warning.trim()
            ? data.warning.trim()
            : "",
        imageDataUrl,
        audioDataUrl,
        audioFileName,
        codeFileDataUrl,
        codeFileName,
        timestamp: Date.now(),
      });

      console.info("[JO AI Mini App] submit.success", {
        mode: getToolId(),
        endpoint: data && typeof data._endpoint === "string" ? data._endpoint : "",
        request_id: data && typeof data._request_id === "string" ? data._request_id : "",
        has_image: Boolean(imageDataUrl),
        has_audio: Boolean(audioDataUrl),
        has_code_file: Boolean(codeFileDataUrl),
      });

      setApiState("ready", "success");
      showToast("Response ready.");
    } catch (error) {
      const message = error instanceof Error ? error.message : "The assistant could not complete this request.";
      console.error("[JO AI Mini App] submit.failed", {
        mode: getToolId(),
        message,
        details: error && typeof error === "object" && "details" in error ? error.details : [],
      });
      replacePendingMessage({
        id: createId(),
        role: "assistant",
        text: `Request failed\n\n${message}`,
        timestamp: Date.now(),
      });
      setApiState("issue", "error");
      showToast(message, "error", 3200);
    } finally {
      setBusy(false);
    }
  }

  function saveLatestAsset() {
    const config = currentTool();
    const saveCode = Boolean(config && config.supportsCodeSave && state.lastCodeFileDataUrl);
    const saveImage = Boolean(config && config.supportsImageSave && state.lastImageDataUrl);
    const saveAudio = Boolean(config && config.supportsAudioSave && state.lastAudioDataUrl);
    if (!saveCode && !saveImage && !saveAudio) {
      showToast("No file available to save.", "error");
      return;
    }
    const link = document.createElement("a");
    if (saveCode) {
      link.href = state.lastCodeFileDataUrl;
      link.download = state.lastCodeFileName || `jo-ai-code-${Date.now()}.txt`;
    } else if (saveAudio) {
      link.href = state.lastAudioDataUrl;
      link.download = state.lastAudioFileName || `jo-ai-audio-${Date.now()}.mp3`;
    } else {
      link.href = state.lastImageDataUrl;
      link.download = `jo-ai-image-${Date.now()}.png`;
    }
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  }

  function bindComposerViewportBehavior() {
    if (!elements.aiInput) {
      return;
    }

    const handleFocus = () => {
      syncViewportState();
      scrollHistoryToBottom(true);
      scrollComposerIntoView();
    };

    const handleBlur = () => {
      window.setTimeout(syncViewportState, 90);
    };

    elements.aiInput.addEventListener("focus", handleFocus);
    elements.aiInput.addEventListener("blur", handleBlur);

    if (window.visualViewport) {
      window.visualViewport.addEventListener(
        "resize",
        () => {
          syncViewportState();
          if (document.activeElement === elements.aiInput) {
            scrollComposerIntoView(true);
          }
        },
        { passive: true }
      );
    }
  }

  function bindToolPage() {
    if (elements.useExampleBtn) {
      elements.useExampleBtn.addEventListener("click", fillExample);
    }
    if (elements.toolForm) {
      elements.toolForm.addEventListener("submit", submitTool);
    }
    if (elements.clearBtn) {
      elements.clearBtn.addEventListener("click", clearToolWorkspace);
    }
    if (elements.copyBtn) {
      elements.copyBtn.addEventListener("click", async () => {
        try {
          await copyText(state.lastOutputText);
          showToast("Last response copied.");
        } catch (error) {
          showToast(error instanceof Error ? error.message : "Copy failed.", "error");
        }
      });
    }
    if (elements.pastChatsBtn) {
      elements.pastChatsBtn.addEventListener("click", (event) => {
        openComingSoonModal(event.currentTarget);
      });
    }
    if (elements.downloadImageBtn) {
      elements.downloadImageBtn.addEventListener("click", saveLatestAsset);
    }
    if (elements.aiInput) {
      elements.aiInput.addEventListener("input", () => {
        resizeComposerInput();
        updateSendButtonState();
      });
      elements.aiInput.addEventListener("keydown", (event) => {
        if (event.key === "Enter" && !event.shiftKey) {
          event.preventDefault();
          submitTool();
        }
      });
    }
    if (elements.promptType) {
      elements.promptType.addEventListener("input", updateSendButtonState);
    }
    if (elements.imageType) {
      elements.imageType.addEventListener("change", updateSendButtonState);
    }
    if (elements.imageRatio) {
      elements.imageRatio.addEventListener("change", updateSendButtonState);
    }
    if (elements.ttsLanguage) {
      elements.ttsLanguage.addEventListener("change", updateSendButtonState);
    }
    if (elements.ttsVoice) {
      elements.ttsVoice.addEventListener("change", updateSendButtonState);
    }
    if (elements.ttsEmotion) {
      elements.ttsEmotion.addEventListener("change", updateSendButtonState);
    }
    if (elements.codeFile) {
      elements.codeFile.addEventListener("change", () => {
        updateCodeFileSelection();
        updateSendButtonState();
      });
    }
    if (elements.kimiImage) {
      elements.kimiImage.addEventListener("change", () => {
        updateKimiSelection();
        updateSendButtonState();
      });
    }

    bindComposerViewportBehavior();
    resizeComposerInput(true);
    updateSendButtonState();
  }
  function initHomePage() {
    setStatus("Choose a tool");
  }

  function initToolPage() {
    applyToolConfig();
    removeComposerExampleRow();
    state.emptyTemplate = elements.historyList ? elements.historyList.innerHTML : "";
    loadHistory();
    renderHistory();
    bindToolPage();
    syncViewportState();
    setApiState("idle", "muted");
    setLoadingHint("Ready when you are.");
    updateSendButtonState();
  }

  function runAfterFirstPaint(task) {
    const runner = () => {
      window.setTimeout(() => {
        Promise.resolve()
          .then(task)
          .catch((error) => {
            reportStartupError("post-paint task", error);
          });
      }, 0);
    };

    if (typeof window.requestAnimationFrame === "function") {
      window.requestAnimationFrame(runner);
      return;
    }

    runner();
  }

  async function boot() {
    normalizeHostedHomeUrl();
    clearStaleClientState();
    polishStaticUi();
    ensureGlobalUi();
    bindGlobalUi();
    collectElements();
    setRootMounted(Boolean(document.querySelector("#appRoot, #app, #root, .page-shell")));
    setVersionBadge();
    initTelegram();
    configureSupportActions();

    if (getPage() === "home") {
      initHomePage();
      markStartupComplete();
      runAfterFirstPaint(async () => {
        const apiBase = await resolveApiBase();
        await loadReferralCard(apiBase);
      });
      return;
    }

    if (getPage() === "help") {
      setStatus("Support page");
      markStartupComplete();
      return;
    }

    if (getPage() === "tool") {
      initToolPage();
      markStartupComplete();
      runAfterFirstPaint(async () => {
        const apiBase = await resolveApiBase();
        await claimReferralIfNeeded(apiBase);
      });
      return;
    }

    markStartupComplete();
  }

  function startBoot() {
    Promise.resolve()
      .then(boot)
      .catch((error) => {
        reportStartupError("boot", error);
      });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", startBoot, { once: true });
  } else {
    startBoot();
  }
})();
