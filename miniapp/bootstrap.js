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
  state.maxLayoutHeight = readNumber(state.maxLayoutHeight);

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

  function clampChannel(value) {
    return Math.max(0, Math.min(255, Math.round(Number(value) || 0)));
  }

  function parseColor(value, fallback = null) {
    if (typeof value !== "string") {
      return fallback;
    }
    const raw = value.trim().toLowerCase();
    if (!raw) {
      return fallback;
    }

    const hexMatch = raw.match(/^#([0-9a-f]{3}|[0-9a-f]{6})$/i);
    if (hexMatch) {
      const token = hexMatch[1];
      if (token.length === 3) {
        return {
          r: parseInt(token[0] + token[0], 16),
          g: parseInt(token[1] + token[1], 16),
          b: parseInt(token[2] + token[2], 16),
        };
      }
      return {
        r: parseInt(token.slice(0, 2), 16),
        g: parseInt(token.slice(2, 4), 16),
        b: parseInt(token.slice(4, 6), 16),
      };
    }

    const rgbMatch = raw.match(/^rgba?\(([^)]+)\)$/i);
    if (!rgbMatch) {
      return fallback;
    }
    const parts = rgbMatch[1].split(",").map((part) => part.trim());
    if (parts.length < 3) {
      return fallback;
    }
    const numbers = parts.slice(0, 3).map((part) => Number.parseFloat(part));
    if (numbers.some((part) => !Number.isFinite(part))) {
      return fallback;
    }
    return {
      r: clampChannel(numbers[0]),
      g: clampChannel(numbers[1]),
      b: clampChannel(numbers[2]),
    };
  }

  function toHexColor(rgb, fallback = "#000000") {
    if (!rgb) {
      return fallback;
    }
    const toHex = (value) => clampChannel(value).toString(16).padStart(2, "0");
    return `#${toHex(rgb.r)}${toHex(rgb.g)}${toHex(rgb.b)}`;
  }

  function toRgba(rgb, alpha = 1) {
    if (!rgb) {
      return `rgba(0, 0, 0, ${alpha})`;
    }
    const clampedAlpha = Math.max(0, Math.min(1, Number(alpha) || 0));
    return `rgba(${clampChannel(rgb.r)}, ${clampChannel(rgb.g)}, ${clampChannel(rgb.b)}, ${clampedAlpha})`;
  }

  function mixColor(base, target, weight = 0.5) {
    const ratio = Math.max(0, Math.min(1, Number(weight) || 0));
    const fallback = { r: 255, g: 255, b: 255 };
    const left = base || fallback;
    const right = target || fallback;
    return {
      r: clampChannel(left.r * (1 - ratio) + right.r * ratio),
      g: clampChannel(left.g * (1 - ratio) + right.g * ratio),
      b: clampChannel(left.b * (1 - ratio) + right.b * ratio),
    };
  }

  function channelToLinear(value) {
    const normalized = clampChannel(value) / 255;
    return normalized <= 0.03928 ? normalized / 12.92 : ((normalized + 0.055) / 1.055) ** 2.4;
  }

  function luminance(rgb) {
    if (!rgb) {
      return 0;
    }
    return (
      0.2126 * channelToLinear(rgb.r) +
      0.7152 * channelToLinear(rgb.g) +
      0.0722 * channelToLinear(rgb.b)
    );
  }

  function contrastRatio(foreground, background) {
    const l1 = luminance(foreground);
    const l2 = luminance(background);
    const lighter = Math.max(l1, l2);
    const darker = Math.min(l1, l2);
    return (lighter + 0.05) / (darker + 0.05);
  }

  function ensureReadable(candidate, background, fallback, minContrast = 4.5) {
    const selected = candidate || fallback;
    if (!selected) {
      return null;
    }
    if (!background) {
      return selected;
    }
    if (contrastRatio(selected, background) >= minContrast) {
      return selected;
    }
    return fallback || selected;
  }

  function applyReadableUiPalette(backgroundRgb, textRgb) {
    const darkBackground = luminance(backgroundRgb) < 0.35;
    const themeMode = darkBackground ? "dark" : "light";

    const pageBg = darkBackground ? mixColor(backgroundRgb, { r: 11, g: 18, b: 32 }, 0.35) : mixColor(backgroundRgb, { r: 247, g: 248, b: 251 }, 0.45);
    const surface = darkBackground ? { r: 17, g: 24, b: 39 } : { r: 255, g: 255, b: 255 };
    const surfaceRaised = darkBackground ? { r: 23, g: 35, b: 52 } : { r: 248, g: 250, b: 252 };
    const bubbleUser = darkBackground ? { r: 21, g: 49, b: 68 } : { r: 229, g: 243, b: 238 };
    const bubbleAssistant = darkBackground ? { r: 17, g: 27, b: 42 } : { r: 255, g: 255, b: 255 };
    const inputBg = darkBackground ? { r: 15, g: 23, b: 42 } : { r: 255, g: 255, b: 255 };
    const textPrimaryFallback = darkBackground ? { r: 248, g: 250, b: 252 } : { r: 17, g: 24, b: 39 };
    const textSecondary = darkBackground ? { r: 203, g: 213, b: 225 } : { r: 71, g: 85, b: 105 };
    const textMuted = darkBackground ? { r: 148, g: 163, b: 184 } : { r: 100, g: 116, b: 139 };
    const border = darkBackground ? { r: 130, g: 149, b: 173 } : { r: 100, g: 116, b: 139 };
    const primaryText = ensureReadable(textRgb, pageBg, textPrimaryFallback, 4.8);

    document.documentElement.style.setProperty("--ui-page-bg", toHexColor(pageBg, darkBackground ? "#0b1220" : "#f7f8fb"));
    document.documentElement.style.setProperty("--ui-surface-bg", toHexColor(surface, darkBackground ? "#111827" : "#ffffff"));
    document.documentElement.style.setProperty("--ui-surface-raised", toHexColor(surfaceRaised, darkBackground ? "#172334" : "#f8fafc"));
    document.documentElement.style.setProperty("--ui-user-bubble-bg", toHexColor(bubbleUser, darkBackground ? "#153144" : "#e5f3ee"));
    document.documentElement.style.setProperty("--ui-assistant-bubble-bg", toHexColor(bubbleAssistant, darkBackground ? "#111b2a" : "#ffffff"));
    document.documentElement.style.setProperty("--ui-input-bg", toHexColor(inputBg, darkBackground ? "#0f172a" : "#ffffff"));
    document.documentElement.style.setProperty("--ui-text-primary", toHexColor(primaryText, darkBackground ? "#f8fafc" : "#111827"));
    document.documentElement.style.setProperty("--ui-text-secondary", toHexColor(textSecondary, darkBackground ? "#cbd5e1" : "#475569"));
    document.documentElement.style.setProperty("--ui-text-muted", toHexColor(textMuted, darkBackground ? "#94a3b8" : "#64748b"));
    document.documentElement.style.setProperty("--ui-border-strong", toRgba(border, darkBackground ? 0.38 : 0.28));

    document.documentElement.setAttribute("data-theme-mode", themeMode);
    if (document.body) {
      document.body.setAttribute("data-theme-mode", themeMode);
    }
  }

  function applyTheme() {
    const tg = getTelegramWebApp();
    const theme = tg && tg.themeParams ? tg.themeParams : null;
    const backgroundRgb = parseColor((theme && (theme.bg_color || theme.secondary_bg_color)) || "#fffaf2", {
      r: 255,
      g: 250,
      b: 242,
    });
    const rawTextRgb = parseColor((theme && theme.text_color) || "#1b1f24", {
      r: 27,
      g: 31,
      b: 36,
    });
    const cardRgb = parseColor((theme && (theme.secondary_bg_color || theme.bg_color)) || "#ffffff", {
      r: 255,
      g: 255,
      b: 255,
    });
    const hintRgb = parseColor((theme && theme.hint_color) || "#68727b", {
      r: 104,
      g: 114,
      b: 123,
    });

    const lightFallback = { r: 17, g: 24, b: 39 };
    const darkFallback = { r: 248, g: 250, b: 252 };
    const darkTheme = luminance(backgroundRgb) < 0.35;
    const textFallback = darkTheme ? darkFallback : lightFallback;
    const safeText = ensureReadable(rawTextRgb, backgroundRgb, textFallback, 4.8);
    const safeHint = ensureReadable(hintRgb, backgroundRgb, darkTheme ? { r: 203, g: 213, b: 225 } : { r: 71, g: 85, b: 105 }, 3.2);
    const safeCard = ensureReadable(cardRgb, safeText, darkTheme ? { r: 17, g: 24, b: 39 } : { r: 255, g: 255, b: 255 }, 3.8);

    const backgroundHex = toHexColor(backgroundRgb, "#fffaf2");
    const textHex = toHexColor(safeText, "#1b1f24");
    const cardHex = toHexColor(safeCard, "#ffffff");
    const hintHex = toHexColor(safeHint, "#68727b");

    document.documentElement.style.setProperty("--tg-bg", backgroundHex);
    document.documentElement.style.setProperty("--tg-text", textHex);
    document.documentElement.style.setProperty("--tg-card", cardHex);
    document.documentElement.style.setProperty("--tg-hint", hintHex);
    document.documentElement.style.backgroundColor = backgroundHex;

    applyReadableUiPalette(backgroundRgb, safeText);

    if (document.body) {
      document.body.style.backgroundColor = getComputedStyle(document.documentElement).getPropertyValue("--ui-page-bg").trim() || backgroundHex;
      document.body.style.color = getComputedStyle(document.documentElement).getPropertyValue("--ui-text-primary").trim() || textHex;
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
    const telegramStableHeight = tg ? readNumber(tg.viewportStableHeight) : 0;

    const stableCandidate =
      maxPositive([telegramStableHeight, state.maxLayoutHeight, innerHeight, telegramHeight, viewportBottom]) || innerHeight;
    state.maxLayoutHeight = Math.max(state.maxLayoutHeight || 0, stableCandidate || 0);

    const stableHeight = state.maxLayoutHeight || stableCandidate || innerHeight || 0;
    const visibleHeight =
      minPositive([viewportBottom, viewportHeight, telegramHeight, innerHeight]) ||
      maxPositive([viewportBottom, viewportHeight, telegramHeight, innerHeight]) ||
      stableHeight;
    const offsetBottom = Math.max(0, stableHeight - visibleHeight);
    const keyboardOpen = offsetBottom > 92;

    return {
      // Keep layout height stable; only inset the bottom region when keyboard appears.
      height: stableHeight,
      stableHeight,
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
      try {
        tg.onEvent("themeChanged", () => {
          applyTheme();
          handler();
        });
      } catch (error) {
        reportError("telegram.onEvent(themeChanged)", error);
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
