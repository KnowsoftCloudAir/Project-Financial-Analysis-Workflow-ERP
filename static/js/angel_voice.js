
/* Angel voice commands — include near end of portal.html before </body>
   Requires HTTPS (Render) and mic permission. */
(function () {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  function status(msg) {
    const el = document.getElementById("angel-voice-status") || document.getElementById("angelStatus");
    if (el) el.textContent = msg;
    console.log("[Angel voice]", msg);
  }
  if (!SR) {
    status("Voice not supported in this browser — use Chrome/Edge on HTTPS.");
    return;
  }
  const rec = new SR();
  rec.lang = "en-US";
  rec.continuous = false;
  rec.interimResults = false;
  rec.maxAlternatives = 1;

  let listening = false;
  function start() {
    try {
      rec.start();
      listening = true;
      status("Listening… speak now");
    } catch (e) {
      status("Mic error: " + e.message);
    }
  }
  function stop() {
    try { rec.stop(); } catch (e) {}
    listening = false;
  }

  rec.onresult = function (ev) {
    const text = (ev.results[0][0].transcript || "").trim();
    status("Heard: " + text);
    // Prefer existing Angel handlers on the page
    if (typeof window.angelHandleVoice === "function") {
      window.angelHandleVoice(text);
      return;
    }
    if (typeof window.angelAsk === "function") {
      window.angelAsk(text);
      return;
    }
    // Fill chat input and submit if present
    const input = document.querySelector("#angel-input, #angelInput, [name=angel], textarea[x-model*='angel'], input[placeholder*='Angel' i]");
    if (input) {
      input.value = text;
      input.dispatchEvent(new Event("input", { bubbles: true }));
      const form = input.closest("form");
      if (form) form.requestSubmit();
      else {
        const btn = document.querySelector("#angel-send, [data-angel-send]");
        if (btn) btn.click();
      }
    }
  };
  rec.onerror = function (ev) {
    status("Voice error: " + (ev.error || "unknown") + " — allow microphone for this site.");
    listening = false;
  };
  rec.onend = function () {
    listening = false;
    status("Voice idle — tap mic to speak again");
  };

  function bindMic() {
    const btns = document.querySelectorAll(
      "#angel-mic, [data-angel-mic], button[aria-label*='voice' i], button[title*='voice' i], .angel-mic"
    );
    btns.forEach(function (btn) {
      if (btn.dataset.angelBound) return;
      btn.dataset.angelBound = "1";
      btn.addEventListener("click", function (e) {
        e.preventDefault();
        if (listening) stop();
        else start();
      });
    });
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bindMic);
  } else bindMic();
  window.angelStartVoice = start;
  window.angelStopVoice = stop;
})();
