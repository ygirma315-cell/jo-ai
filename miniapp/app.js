(() => {
  const tg = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;
  const urlParams = new URLSearchParams(window.location.search);
  const API_BASE = (urlParams.get("api_base") || window.__API_BASE__ || "").trim();
  const CHAT_BACKEND_URL = "https://jo-ai.onrender.com/chat";
  const CODE_BACKEND_URL = "https://jo-ai.onrender.com/code";
  const IMAGE_BACKEND_URL = "https://jo-ai.onrender.com/image";

  const statusEl = document.getElementById("status");
  const userInfoEl = document.getElementById("userInfo");
  const tabs = Array.from(document.querySelectorAll(".tab"));
  const panels = Array.from(document.querySelectorAll(".panel"));
  const modes = Array.from(document.querySelectorAll(".mode"));
  const inputLabel = document.getElementById("inputLabel");
  const aiInput = document.getElementById("aiInput");
  const promptTypeWrap = document.getElementById("promptTypeWrap");
  const promptType = document.getElementById("promptType");
  const imageTypeWrap = document.getElementById("imageTypeWrap");
  const imageType = document.getElementById("imageType");
  const modelProfile = document.getElementById("modelProfile");
  const kimiImageWrap = document.getElementById("kimiImageWrap");
  const kimiImage = document.getElementById("kimiImage");
  const sendBtn = document.getElementById("sendBtn");
  const clearBtn = document.getElementById("clearBtn");
  const apiState = document.getElementById("apiState");
  const aiOutput = document.getElementById("aiOutput");
  const imagePreview = document.getElementById("imagePreview");

  let activeMode = "chat";

  function apiUrl(path) {
    if (!API_BASE) return path;
    return `${API_BASE}${path}`;
  }

  function setStatus(text) {
    if (statusEl) statusEl.textContent = text;
  }

  function setUserInfo(text) {
    if (userInfoEl) userInfoEl.textContent = text;
  }

  function showPanel(id) {
    panels.forEach((panel) => panel.classList.toggle("active", panel.id === id));
    tabs.forEach((tab) => tab.classList.toggle("active", tab.dataset.target === id));
  }

  function setMode(mode) {
    activeMode = mode;
    modes.forEach((btn) => btn.classList.toggle("active", btn.dataset.mode === mode));

    if (mode === "prompt") {
      inputLabel.textContent = "Prompt details";
      aiInput.placeholder =
        "Describe your goal, audience, tone, constraints, and output format.";
      promptTypeWrap.hidden = false;
      imageTypeWrap.hidden = true;
      kimiImageWrap.hidden = true;
      imagePreview.hidden = true;
      imagePreview.removeAttribute("src");
    } else if (mode === "image") {
      inputLabel.textContent = "Image description";
      aiInput.placeholder =
        "Describe subject, scene, mood, composition, and any details you want.";
      promptTypeWrap.hidden = true;
      imageTypeWrap.hidden = false;
      kimiImageWrap.hidden = true;
    } else if (mode === "kimi") {
      inputLabel.textContent = "Describe task";
      aiInput.placeholder = "Optional instruction, e.g. Describe what is in this image.";
      promptTypeWrap.hidden = true;
      imageTypeWrap.hidden = true;
      kimiImageWrap.hidden = false;
    } else {
      promptTypeWrap.hidden = true;
      imageTypeWrap.hidden = true;
      kimiImageWrap.hidden = true;
      promptType.value = "";
      if (mode === "code") {
        inputLabel.textContent = "Code request";
        aiInput.placeholder = "Describe what code you need and include language/framework.";
      } else if (mode === "research") {
        inputLabel.textContent = "Research question";
        aiInput.placeholder = "Ask for detailed analysis and what depth you need.";
      } else {
        inputLabel.textContent = "Message";
        aiInput.placeholder = "Type your request here...";
      }
    }
  }

  async function callAI() {
    const text = (aiInput.value || "").trim();
    if (!text) {
      aiOutput.textContent = "Please enter a request.";
      return;
    }

    const payload = { message: text };
    let requestUrl = CHAT_BACKEND_URL;

    if (activeMode !== "chat") {
      payload.model_profile = modelProfile ? modelProfile.value : "default";
      if (activeMode === "code") {
        requestUrl = CODE_BACKEND_URL;
      }
      if (activeMode === "research") requestUrl = apiUrl("/api/research");
      if (activeMode === "prompt") {
        requestUrl = apiUrl("/api/prompt");
        payload.prompt_type = (promptType.value || "").trim();
        if (!payload.prompt_type) {
          aiOutput.textContent = "Please enter a prompt type first.";
          return;
        }
      } else if (activeMode === "image") {
        requestUrl = IMAGE_BACKEND_URL;
        payload.image_type = (imageType.value || "").trim();
        if (!payload.image_type) {
          aiOutput.textContent = "Please choose an image style.";
          return;
        }
      } else if (activeMode === "kimi") {
        requestUrl = apiUrl("/api/kimi_image_describer");
        const file = kimiImage && kimiImage.files ? kimiImage.files[0] : null;
        if (!file) {
          aiOutput.textContent = "Please upload an image first.";
          return;
        }
        payload.image_base64 = await fileToBase64(file);
      }
    }

    apiState.textContent = "loading...";
    sendBtn.disabled = true;

    try {
      const { response, data } = await fetchJson(requestUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!response.ok) {
        aiOutput.textContent = data.error || "Request failed.";
        imagePreview.hidden = true;
        imagePreview.removeAttribute("src");
      } else {
        aiOutput.textContent = data.output || "No output returned.";
        if (data.image_base64) {
          imagePreview.src = `data:image/png;base64,${data.image_base64}`;
          imagePreview.hidden = false;
        } else {
          imagePreview.hidden = true;
          imagePreview.removeAttribute("src");
        }
      }
    } catch (error) {
      aiOutput.textContent = `Network error: ${error && error.message ? error.message : "unknown error"}`;
      imagePreview.hidden = true;
      imagePreview.removeAttribute("src");
    } finally {
      apiState.textContent = "idle";
      sendBtn.disabled = false;
    }
  }

  function initTelegram() {
    if (!tg) {
      setStatus("Browser mode");
      return;
    }
    tg.ready();
    if (typeof tg.expand === "function") tg.expand();
    const name =
      (tg.initDataUnsafe && tg.initDataUnsafe.user && tg.initDataUnsafe.user.first_name) ||
      "there";
    setStatus("Connected");
    setUserInfo(`Hi, ${name}`);
  }

  async function checkApiHealth() {
    try {
      const { response, data } = await fetchJson(apiUrl("/api/health"), { method: "GET" });
      if (!response.ok) {
        setStatus("API offline");
        return;
      }
      if (data && data.ok) {
        setStatus(tg ? "Connected + API ready" : "API ready");
      } else {
        setStatus("API offline");
      }
    } catch (_error) {
      setStatus("API offline");
    }
  }

  async function fetchJson(url, options) {
    const response = await fetch(url, options);
    const raw = await response.text();
    let data = null;
    try {
      data = raw ? JSON.parse(raw) : {};
    } catch (_error) {
      const preview = raw.slice(0, 120).replace(/\s+/g, " ");
      throw new Error(`Backend returned non-JSON response. Preview: ${preview}`);
    }
    return { response, data };
  }

  async function fileToBase64(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => {
        const result = reader.result || "";
        const text = String(result);
        const comma = text.indexOf(",");
        resolve(comma >= 0 ? text.slice(comma + 1) : text);
      };
      reader.onerror = () => reject(new Error("Failed to read file."));
      reader.readAsDataURL(file);
    });
  }

  function wireTabs() {
    tabs.forEach((tab) => {
      tab.addEventListener("click", () => showPanel(tab.dataset.target));
    });
  }

  function wireModes() {
    modes.forEach((modeBtn) => {
      modeBtn.addEventListener("click", () => setMode(modeBtn.dataset.mode));
    });
  }

  function wireActions() {
    sendBtn.addEventListener("click", callAI);
    clearBtn.addEventListener("click", () => {
      aiInput.value = "";
      aiOutput.textContent = "Your AI response will appear here.";
      apiState.textContent = "idle";
      imagePreview.hidden = true;
      imagePreview.removeAttribute("src");
    });
  }

  function initTicTacToe() {
    const boardEl = document.getElementById("tttBoard");
    const status = document.getElementById("tttStatus");
    const resetBtn = document.getElementById("tttReset");
    if (!boardEl || !status || !resetBtn) return;

    let board = Array(9).fill("");
    let finished = false;

    const winLines = [
      [0, 1, 2],
      [3, 4, 5],
      [6, 7, 8],
      [0, 3, 6],
      [1, 4, 7],
      [2, 5, 8],
      [0, 4, 8],
      [2, 4, 6],
    ];

    const getWinner = (cells) => {
      for (const line of winLines) {
        const [a, b, c] = line;
        if (cells[a] && cells[a] === cells[b] && cells[b] === cells[c]) {
          return { winner: cells[a], line };
        }
      }
      return null;
    };

    const botMove = () => {
      const empty = board.map((v, i) => (v ? null : i)).filter((v) => v !== null);
      if (!empty.length || finished) return;
      const index = empty[Math.floor(Math.random() * empty.length)];
      board[index] = "O";
    };

    const render = (line = []) => {
      boardEl.innerHTML = "";
      board.forEach((value, index) => {
        const button = document.createElement("button");
        button.className = "ttt-cell";
        if (line.includes(index)) button.classList.add("win");
        button.textContent = value || "";
        button.addEventListener("click", () => {
          if (finished || board[index]) return;
          board[index] = "X";
          let result = getWinner(board);
          if (result) {
            finished = true;
            status.textContent = result.winner === "X" ? "You win." : "Bot wins.";
            render(result.line);
            return;
          }
          if (board.every(Boolean)) {
            finished = true;
            status.textContent = "Draw.";
            render();
            return;
          }

          botMove();
          result = getWinner(board);
          if (result) {
            finished = true;
            status.textContent = result.winner === "X" ? "You win." : "Bot wins.";
            render(result.line);
            return;
          }
          if (board.every(Boolean)) {
            finished = true;
            status.textContent = "Draw.";
            render();
            return;
          }
          status.textContent = "Your turn (X).";
          render();
        });
        boardEl.appendChild(button);
      });
    };

    resetBtn.addEventListener("click", () => {
      board = Array(9).fill("");
      finished = false;
      status.textContent = "Your turn (X).";
      render();
    });

    render();
  }

  function initGuessNumber() {
    const input = document.getElementById("guessInput");
    const button = document.getElementById("guessBtn");
    const reset = document.getElementById("guessReset");
    const status = document.getElementById("guessStatus");
    if (!input || !button || !reset || !status) return;

    let target = Math.floor(Math.random() * 100) + 1;
    let attempts = 0;

    button.addEventListener("click", () => {
      const guess = Number(input.value);
      if (!Number.isInteger(guess) || guess < 1 || guess > 100) {
        status.textContent = "Enter a whole number from 1 to 100.";
        return;
      }
      attempts += 1;
      if (guess < target) {
        status.textContent = `Too low. Attempts: ${attempts}`;
      } else if (guess > target) {
        status.textContent = `Too high. Attempts: ${attempts}`;
      } else {
        status.textContent = `Correct in ${attempts} attempt(s).`;
      }
    });

    reset.addEventListener("click", () => {
      target = Math.floor(Math.random() * 100) + 1;
      attempts = 0;
      input.value = "";
      status.textContent = "New game started.";
    });
  }

  initTelegram();
  checkApiHealth();
  wireTabs();
  wireModes();
  wireActions();
  initTicTacToe();
  initGuessNumber();
  setMode("chat");
  showPanel("ai");
})();
