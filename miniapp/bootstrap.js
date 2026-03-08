(() => {
  "use strict";

  const state = (window.__joMiniAppBoot = window.__joMiniAppBoot || {});
  state.errors = Array.isArray(state.errors) ? state.errors : [];
  state.startupComplete = false;
  state.telegramDetected = false;
  state.viewportBound = false;
  state.rootMounted = false;
  state.shellInitialized = false;
  state.startupTimer = state.startupTimer || 0;

  function byId(id) {
    return document.getElementById(id);
  }

  function getTelegramWebApp() {
    return window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;
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

  function readNumber(value) {
    const next = Number(value);
    return Number.isFinite(next) && next > 0 ? next : 0;
  }

  function maxPositive(values) {
    const numbers = values.filter((value) => value > 0);
    return numbers.length ? Math.max(...numbers) : 0;
  }

  function minPositive(values) {
    const numbers = values.filter((value) => value > 0);
    return numbers.length ? Math.min(...numbers) : 0;
  }

  function errorToMessage(error) {
    if (!error) {
      return "Unknown startup error.";
    }
    if (error instanceof Error) {
      return error.message || error.name || "Unknown startup error.";
    }
    if (typeof error === "string") {
      return error;
    }
    if (typeof error.reason === "string") {
      return error.reason;
    }
    if (typeof error.message === "string") {
      return error.message;
    }
    try {
      return JSON.stringify(error);
    } catch (_jsonError) {
      return String(error);
    }
  }

  function updateBanner() {
    // Production keeps startup state in memory and console logs only.
  }

  function setRootMounted(value) {
    state.rootMounted = !!value;
    updateBanner();
  }

  function clearStartupWatchdog() {
    if (state.startupTimer) {
      clearTimeout(state.startupTimer);
      state.startupTimer = 0;
    }
  }

  function setBodyFlag(name, value) {
    if (!document.body) {
      return;
    }
    document.body.dataset[name] = value;
  }

  function showFallback(message) {
    clearStartupWatchdog();
    const panel = byId("appFallback");
    const copy = byId("appFallbackMessage");
    if (copy) {
      copy.textContent = message || "Unknown startup error.";
    }
    if (panel) {
      panel.hidden = false;
    }
    setBodyFlag("bootFailed", "true");
  }

  function hideFallback() {
    clearStartupWatchdog();
    const panel = byId("appFallback");
    if (panel) {
      panel.hidden = true;
    }
    setBodyFlag("bootFailed", "false");
  }

  function reportError(label, error) {
    const message = errorToMessage(error);
    state.errors.push({ label, message, time: Date.now() });
    console.error(`[JO AI Mini App] ${label}`, error);
    if (!state.startupComplete) {
      showFallback(message);
    }
    updateBanner();
  }

  function applyTheme() {
    const tg = getTelegramWebApp();
    const theme = tg && tg.themeParams ? tg.themeParams : null;
    const background = (theme && (theme.bg_color || theme.secondary_bg_color)) || "#fffaf2";
    const foreground = (theme && theme.text_color) || "#1b1f24";
    const card = (theme && (theme.secondary_bg_color || theme.bg_color)) || "#ffffff";
    const hint = (theme && theme.hint_color) || "#68727b";

    document.documentElement.style.setProperty("--tg-bg", background);
    document.documentElement.style.setProperty("--tg-text", foreground);
    document.documentElement.style.setProperty("--tg-card", card);
    document.documentElement.style.setProperty("--tg-hint", hint);
    document.documentElement.style.backgroundColor = background;

    if (document.body) {
      document.body.style.backgroundColor = background;
      document.body.style.color = foreground;
    }
  }

  function detectTelegramMobile() {
    const tg = getTelegramWebApp();
    const platform = tg && typeof tg.platform === "string" ? tg.platform.toLowerCase() : "";
    const ua = navigator.userAgent || "";
    const isMobileUa = /android|iphone|ipad|ipod|mobile/i.test(ua);
    return (
      isMobileUa &&
      (
        platform === "android" ||
        platform === "ios" ||
        /telegram|plus\s*messenger|plusmessenger|nekogram|nicegram/i.test(ua) ||
        hasTelegramWebAppContext(tg)
      )
    );
  }

  function readViewportMetrics() {
    const tg = hasTelegramWebAppContext(getTelegramWebApp()) ? getTelegramWebApp() : null;
    const viewport = window.visualViewport || null;
    const innerHeight = readNumber(window.innerHeight);
    const viewportHeight = viewport ? readNumber(viewport.height) : 0;
    const viewportTop = viewport ? readNumber(viewport.offsetTop) : 0;
    const viewportBottom = viewportHeight > 0 ? viewportHeight + viewportTop : 0;
    const telegramHeight = tg ? readNumber(tg.viewportHeight) : 0;
    const stableHeight = tg ? readNumber(tg.viewportStableHeight) : 0;
    const stable = maxPositive([stableHeight, innerHeight, telegramHeight, viewportBottom, viewportHeight]);
    const keyboardDeltaInner = innerHeight > 0 && viewportHeight > 0 ? innerHeight - viewportHeight : 0;
    const keyboardDeltaStable = stable > 0 && viewportHeight > 0 ? stable - viewportHeight : 0;
    const keyboardOpen = keyboardDeltaInner > 120 || keyboardDeltaStable > 120;
    const height = keyboardOpen
      ? minPositive([viewportBottom, viewportHeight, telegramHeight, innerHeight]) || maxPositive([telegramHeight, innerHeight, viewportBottom, viewportHeight])
      : maxPositive([telegramHeight, viewportBottom, innerHeight, viewportHeight]);
    const offsetBottom =
      keyboardOpen && stable > height
        ? Math.max(0, stable - height)
        : viewport
          ? Math.max(0, innerHeight - viewportHeight - viewportTop)
          : 0;

    return {
      height: height || innerHeight || stable || 0,
      stableHeight: stable || height || innerHeight || 0,
      offsetTop: viewportTop,
      offsetBottom,
      keyboardOpen,
    };
  }

  function syncViewportMetrics() {
    const metrics = readViewportMetrics();
    if (!metrics.height) {
      return;
    }

    document.documentElement.style.setProperty("--app-height", `${metrics.height}px`);
    document.documentElement.style.setProperty("--viewport-height", `${metrics.height}px`);
    document.documentElement.style.setProperty("--viewport-stable-height", `${metrics.stableHeight}px`);
    document.documentElement.style.setProperty("--viewport-offset-top", `${metrics.offsetTop}px`);
    document.documentElement.style.setProperty("--viewport-offset-bottom", `${metrics.offsetBottom}px`);
    document.documentElement.style.setProperty("--keyboard-inset", metrics.keyboardOpen ? `${metrics.offsetBottom}px` : "0px");

    setBodyFlag("telegramDetected", state.telegramDetected ? "true" : "false");
    setBodyFlag("telegramMobile", detectTelegramMobile() ? "true" : "false");
    setBodyFlag("keyboardOpen", metrics.keyboardOpen ? "true" : "false");
  }

  function bindViewportSync() {
    if (state.viewportBound) {
      syncViewportMetrics();
      return;
    }

    const handler = () => {
      try {
        syncViewportMetrics();
      } catch (error) {
        reportError("viewport.sync", error);
      }
    };

    state.viewportBound = true;
    window.addEventListener("resize", handler, { passive: true });
    window.addEventListener("orientationchange", handler);

    if (window.visualViewport) {
      window.visualViewport.addEventListener("resize", handler, { passive: true });
      window.visualViewport.addEventListener("scroll", handler, { passive: true });
    }

    const tg = state.telegramDetected ? window.Telegram.WebApp : null;
    if (tg && typeof tg.onEvent === "function") {
      try {
        tg.onEvent("viewportChanged", handler);
      } catch (error) {
        reportError("telegram.onEvent(viewportChanged)", error);
      }
    }

    handler();
  }

  function safeTelegramInit() {
    const tg = getTelegramWebApp();
    state.telegramDetected = hasTelegramWebAppContext(tg) || detectTelegramMobile();
    updateBanner();
    setBodyFlag("telegramDetected", state.telegramDetected ? "true" : "false");
    setBodyFlag("telegramMobile", detectTelegramMobile() ? "true" : "false");

    const shell = state.telegramDetected ? tg : null;
    if (!shell) {
      return;
    }

    try {
      if (typeof shell.ready === "function") {
        shell.ready();
      }
    } catch (error) {
      reportError("telegram.ready", error);
    }

    try {
      if (typeof shell.expand === "function") {
        shell.expand();
      }
    } catch (error) {
      reportError("telegram.expand", error);
    }

    window.setTimeout(syncViewportMetrics, 16);
    window.setTimeout(syncViewportMetrics, 220);
  }

  function initMiniAppShell() {
    if (state.shellInitialized) {
      return;
    }
    state.shellInitialized = true;
    applyTheme();
    safeTelegramInit();
    bindViewportSync();
    const hasRoot = Boolean(document.querySelector("#appRoot, #app, #root, .page-shell"));
    setRootMounted(hasRoot);
    setBodyFlag("shellReady", "true");
    if (!hasRoot) {
      showFallback("Mini App container is missing.");
    }
  }

  state.updateBanner = updateBanner;
  state.setRootMounted = setRootMounted;
  state.showFallback = showFallback;
  state.hideFallback = hideFallback;
  state.reportError = reportError;
  state.applyTheme = applyTheme;
  state.syncViewportMetrics = syncViewportMetrics;
  state.safeTelegramInit = safeTelegramInit;

  state.telegramDetected = hasTelegramWebAppContext(getTelegramWebApp()) || detectTelegramMobile();

  state.startupTimer = window.setTimeout(() => {
    if (!state.startupComplete && !state.rootMounted) {
      showFallback("Mini App startup is taking longer than expected. Please reopen it.");
    }
  }, 6500);

  window.addEventListener("error", (event) => {
    reportError("window.onerror", event.error || event.message || "Unknown startup error.");
  });

  window.addEventListener("unhandledrejection", (event) => {
    reportError("window.onunhandledrejection", event.reason || "Unhandled promise rejection.");
  });

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initMiniAppShell, { once: true });
  } else {
    initMiniAppShell();
  }
})();
