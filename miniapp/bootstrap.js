(() => {
  "use strict";

  const state = (window.__joMiniAppBoot = window.__joMiniAppBoot || {});
  state.errors = Array.isArray(state.errors) ? state.errors : [];
  state.startupComplete = false;
  state.telegramDetected = !!(window.Telegram && window.Telegram.WebApp);
  state.rootMounted = false;

  function byId(id) {
    return document.getElementById(id);
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

  function showFallback(message) {
    const panel = byId("appFallback");
    const copy = byId("appFallbackMessage");
    if (copy) {
      copy.textContent = message || "Unknown startup error.";
    }
    if (panel) {
      panel.hidden = false;
    }
  }

  function hideFallback() {
    const panel = byId("appFallback");
    if (panel) {
      panel.hidden = true;
    }
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
    const tg = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;
    const theme = tg && tg.themeParams ? tg.themeParams : null;
    const background = (theme && (theme.bg_color || theme.secondary_bg_color)) || "#fffaf2";
    const foreground = (theme && theme.text_color) || "#1b1f24";
    const card = (theme && (theme.secondary_bg_color || theme.bg_color)) || "#ffffff";
    const hint = (theme && theme.hint_color) || "#68727b";

    document.documentElement.style.setProperty("--tg-bg", background);
    document.documentElement.style.setProperty("--tg-text", foreground);
    document.documentElement.style.setProperty("--tg-card", card);
    document.documentElement.style.setProperty("--tg-hint", hint);

    if (document.body && theme) {
      document.body.style.background = background;
      document.body.style.color = foreground;
    }
  }

  function safeTelegramInit() {
    state.telegramDetected = !!(window.Telegram && window.Telegram.WebApp);
    updateBanner();

    const tg = state.telegramDetected ? window.Telegram.WebApp : null;
    if (!tg) {
      return;
    }

    try {
      if (typeof tg.ready === "function") {
        tg.ready();
      }
    } catch (error) {
      reportError("telegram.ready", error);
    }

    try {
      if (typeof tg.expand === "function") {
        tg.expand();
      }
    } catch (error) {
      reportError("telegram.expand", error);
    }
  }

  function initMiniAppShell() {
    applyTheme();
    safeTelegramInit();
    const hasRoot = Boolean(document.querySelector("#appRoot, #app, #root, .page-shell"));
    setRootMounted(hasRoot);
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
  state.safeTelegramInit = safeTelegramInit;

  window.addEventListener("error", (event) => {
    reportError("window.onerror", event.error || event.message || "Unknown startup error.");
  });

  window.addEventListener("unhandledrejection", (event) => {
    reportError("window.onunhandledrejection", event.reason || "Unhandled promise rejection.");
  });

  document.addEventListener("DOMContentLoaded", initMiniAppShell);
})();
