
/* Churchgate Memories — device photo slideshow above social stream */
(function () {
  const KEY = 'cg_memories_v1';
  const MAX = 40;
  const state = {
    on: true,
    landscape: false,
    intervalMs: 4500,
    effect: 'kenburns',
    items: [], // {id, dataUrl, name}
    idx: 0,
    timer: null,
    musicOn: false,
  };

  function load() {
    try {
      const raw = localStorage.getItem(KEY);
      if (raw) Object.assign(state, JSON.parse(raw));
      if (!Array.isArray(state.items)) state.items = [];
    } catch (e) { state.items = []; }
  }
  function save() {
    try {
      const copy = { on: state.on, landscape: state.landscape, intervalMs: state.intervalMs, effect: state.effect, musicOn: state.musicOn, items: state.items.slice(0, MAX) };
      localStorage.setItem(KEY, JSON.stringify(copy));
    } catch (e) { console.warn('Memories save full', e); }
  }

  function el(id) { return document.getElementById(id); }

  function render() {
    const root = el('cg-memories');
    if (!root) return;
    root.classList.toggle('is-off', !state.on);
    root.classList.toggle('is-landscape', state.landscape);
    const stage = el('cg-memories-stage');
    const empty = el('cg-memories-empty');
    if (!state.items.length) {
      if (stage) stage.innerHTML = '';
      if (empty) empty.classList.remove('hidden');
      return;
    }
    if (empty) empty.classList.add('hidden');
    const it = state.items[state.idx % state.items.length];
    if (!stage || !it) return;
    stage.innerHTML = '';
    const img = document.createElement('img');
    img.src = it.dataUrl;
    img.alt = it.name || 'Memory';
    img.className = 'cg-mem-img cg-fx-' + (state.effect || 'kenburns');
    stage.appendChild(img);
  }

  function next() {
    if (!state.items.length) return;
    state.idx = (state.idx + 1) % state.items.length;
    render();
  }
  function prev() {
    if (!state.items.length) return;
    state.idx = (state.idx - 1 + state.items.length) % state.items.length;
    render();
  }
  function startTimer() {
    stopTimer();
    if (!state.on || state.items.length < 2) return;
    state.timer = setInterval(next, state.intervalMs || 4500);
  }
  function stopTimer() {
    if (state.timer) clearInterval(state.timer);
    state.timer = null;
  }

  function readFiles(fileList) {
    const files = Array.from(fileList || []).filter(f => /^image\//.test(f.type)).slice(0, MAX);
    files.forEach(file => {
      const reader = new FileReader();
      reader.onload = () => {
        state.items.push({ id: Date.now() + Math.random(), dataUrl: reader.result, name: file.name });
        if (state.items.length > MAX) state.items = state.items.slice(-MAX);
        save();
        render();
        startTimer();
      };
      reader.readAsDataURL(file);
    });
  }

  function bindMusic() {
    const audio = el('cg-memories-audio');
    if (!audio) return;
    // Prefer Kwealth nature / books BGM if present on page
    const sources = [
      '/static/kwealth_bgm/nature_ambient.mp3',
      '/static/bgm/nature_ambient.mp3',
      document.querySelector('[data-kwealth-bgm]') && document.querySelector('[data-kwealth-bgm]').getAttribute('data-kwealth-bgm'),
    ].filter(Boolean);
    if (sources[0] && !audio.src) audio.src = sources[0];
    if (state.musicOn) {
      audio.volume = 0.35;
      audio.play().catch(() => {});
    } else {
      audio.pause();
    }
  }

  window.CGMemories = {
    init() {
      load();
      const root = el('cg-memories');
      if (!root) return;
      el('cg-memories-toggle')?.addEventListener('click', () => {
        state.on = !state.on;
        save();
        render();
        if (state.on) startTimer(); else stopTimer();
        const b = el('cg-memories-toggle');
        if (b) b.textContent = state.on ? 'Memories on' : 'Memories off';
      });
      el('cg-memories-landscape')?.addEventListener('click', () => {
        state.landscape = !state.landscape;
        save();
        root.classList.toggle('is-landscape', state.landscape);
      });
      el('cg-memories-add')?.addEventListener('change', (e) => readFiles(e.target.files));
      el('cg-memories-clear')?.addEventListener('click', () => {
        if (!confirm('Clear all memories on this device?')) return;
        state.items = [];
        save();
        render();
        stopTimer();
      });
      el('cg-memories-next')?.addEventListener('click', () => { next(); startTimer(); });
      el('cg-memories-prev')?.addEventListener('click', () => { prev(); startTimer(); });
      el('cg-memories-music')?.addEventListener('click', () => {
        state.musicOn = !state.musicOn;
        save();
        bindMusic();
        const b = el('cg-memories-music');
        if (b) b.textContent = state.musicOn ? '♪ Music on' : '♪ Music off';
      });
      render();
      if (state.on) startTimer();
      bindMusic();
      const tb = el('cg-memories-toggle');
      if (tb) tb.textContent = state.on ? 'Memories on' : 'Memories off';
    }
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => window.CGMemories.init());
  } else {
    window.CGMemories.init();
  }
})();
