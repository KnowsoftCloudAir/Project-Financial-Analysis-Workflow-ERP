
(function () {
  function status(msg) {
    var el = document.getElementById("angel-mic-status") || document.getElementById("angel-voice-status");
    if (el) el.textContent = msg;
  }
  async function ensureMic() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      status("Mic not supported in this browser (use Chrome/Edge).");
      return false;
    }
    try {
      var stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      stream.getTracks().forEach(function (t) { t.stop(); });
      window.__cgMicAllowed = true;
      status("Microphone ON — Angel can listen.");
      document.dispatchEvent(new CustomEvent("cg-mic-granted"));
      return true;
    } catch (e) {
      window.__cgMicAllowed = false;
      status("Microphone OFF/blocked — allow mic for churchgate.knowsoft.org.uk");
      return false;
    }
  }
  function bind() {
    document.querySelectorAll("[data-angel-mic-request], #angel-mic-request").forEach(function (btn) {
      if (btn.dataset.boundMic) return;
      btn.dataset.boundMic = "1";
      btn.addEventListener("click", async function (e) {
        e.preventDefault();
        var ok = await ensureMic();
        btn.textContent = ok ? "🎤 Mic on" : "🎤 Allow microphone";
      });
    });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", bind);
  else bind();
  window.cgRequestAngelMic = ensureMic;
})();
