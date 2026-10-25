/* Churchgate 3D ambient + fallback 2D — portal & books */
(function (global) {
  const MODES = [
    { id: 'none', name: 'None' },
    { id: 'sunset', name: 'Golden sunset' },
    { id: 'planets', name: 'Planets around the sun' },
    { id: 'starfield', name: 'Deep starfield' },
    { id: 'aurora', name: 'Northern lights' },
    { id: 'ocean_waves', name: 'Ocean waves' },
    { id: 'ocean_fish', name: 'Ocean depths' },
    { id: 'sky_run', name: 'Journey into the heavens' },
    { id: 'jupiter', name: 'Jupiter flyby' },
    { id: 'galaxy', name: 'Spiral galaxy' },
    { id: 'floating_orbs', name: 'Floating orbs of light' },
    { id: 'word_forms', name: 'Living words' },
    { id: 'great_men', name: 'Portraits from the sky' },
    { id: 'sunrise_ant', name: 'Sunrise meadow' },
  ];

  let renderer, scene, camera, animId, mode = 'none', paused = false;
  let clock, starPoints, extra = {}, threeReady = null;
  let canvasHost = null, use3d = true, ctx2d = null, canvas2d = null;

  function loadThree() {
    if (global.THREE) return Promise.resolve(global.THREE);
    if (threeReady) return threeReady;
    threeReady = new Promise(function (resolve, reject) {
      var s = document.createElement('script');
      s.src = 'https://cdnjs.cloudflare.com/ajax/libs/three.js/r134/three.min.js';
      s.onload = function () { resolve(global.THREE); };
      s.onerror = function () { reject(new Error('three load fail')); };
      document.head.appendChild(s);
      setTimeout(function () { if (!global.THREE) reject(new Error('three timeout')); }, 12000);
    });
    return threeReady;
  }

  function hostParent() {
    return document.getElementById('imStage') || document.getElementById('stage') || document.body;
  }

  function ensureHost() {
    if (canvasHost && document.body.contains(canvasHost)) return;
    canvasHost = document.getElementById('cgBgAnim3d');
    if (!canvasHost) {
      canvasHost = document.createElement('div');
      canvasHost.id = 'cgBgAnim3d';
    }
    canvasHost.style.cssText = 'position:fixed;inset:0;z-index:70;pointer-events:none;opacity:1;';
    var parent = hostParent();
    if (parent === document.body) {
      document.body.prepend(canvasHost);
    } else {
      canvasHost.style.position = 'absolute';
      parent.style.position = parent.style.position || 'relative';
      if (!parent.contains(canvasHost)) parent.insertBefore(canvasHost, parent.firstChild);
    }
  }

  function onResize() {
    var w = window.innerWidth, h = window.innerHeight;
    if (renderer && camera) {
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      renderer.setSize(w, h);
    }
    if (canvas2d) {
      canvas2d.width = w;
      canvas2d.height = h;
    }
  }

  function clear3d() {
    if (!scene) return;
    while (scene.children.length) {
      var o = scene.children[0];
      scene.remove(o);
      if (o.geometry) o.geometry.dispose();
      if (o.material) {
        if (Array.isArray(o.material)) o.material.forEach(function (m) { m.dispose(); });
        else o.material.dispose();
      }
    }
    starPoints = null;
    extra = {};
  }

  function softLight() {
    var THREE = global.THREE;
    scene.add(new THREE.AmbientLight(0x404060, 0.65));
    var key = new THREE.DirectionalLight(0xffe4c4, 1.1);
    key.position.set(5, 8, 5);
    scene.add(key);
  }

  function addStars(count, spread) {
    var THREE = global.THREE;
    var geo = new THREE.BufferGeometry();
    var pos = new Float32Array(count * 3);
    for (var i = 0; i < count; i++) {
      pos[i * 3] = (Math.random() - 0.5) * spread;
      pos[i * 3 + 1] = (Math.random() - 0.5) * spread;
      pos[i * 3 + 2] = (Math.random() - 0.5) * spread;
    }
    geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    starPoints = new THREE.Points(geo, new THREE.PointsMaterial({ color: 0xffffff, size: 0.06, transparent: true, opacity: 0.9 }));
    scene.add(starPoints);
  }

  function buildMode(id) {
    var THREE = global.THREE;
    clear3d();
    softLight();
    camera.position.set(0, 2, 12);
    camera.lookAt(0, 0, 0);
    if (id === 'sunset') {
      renderer.setClearColor(0x0b1026, 1);
      scene.add(new THREE.Mesh(new THREE.SphereGeometry(40, 32, 32), new THREE.MeshBasicMaterial({ color: 0x1a1035, side: THREE.BackSide })));
      var sun = new THREE.Mesh(new THREE.SphereGeometry(2.2, 48, 48), new THREE.MeshBasicMaterial({ color: 0xffb347 }));
      sun.position.set(0, -1.2, -14); scene.add(sun);
      var sunCore = new THREE.Mesh(new THREE.SphereGeometry(1.1, 32, 32), new THREE.MeshBasicMaterial({ color: 0xfff1c1 }));
      sunCore.position.copy(sun.position); scene.add(sunCore);
      var glow = new THREE.PointLight(0xff8c42, 3.2, 90); glow.position.copy(sun.position); scene.add(glow);
      scene.add(new THREE.HemisphereLight(0xff9966, 0x1e1b4b, 0.7));
      var ground = new THREE.Mesh(new THREE.PlaneGeometry(90, 50, 32, 16), new THREE.MeshStandardMaterial({ color: 0x1a1140, roughness: 0.35, metalness: 0.45 }));
      ground.rotation.x = -Math.PI / 2; ground.position.y = -3.2; scene.add(ground);
      extra.sun = sun; extra.sunCore = sunCore; extra.water = ground; extra.clouds = [];
      for (var i = 0; i < 10; i++) {
        var c = new THREE.Mesh(new THREE.SphereGeometry(1.4 + Math.random(), 12, 12), new THREE.MeshStandardMaterial({ color: 0xffc9a3, transparent: true, opacity: 0.28 }));
        c.position.set((Math.random() - 0.5) * 24, 0.5 + Math.random() * 4, -8 - Math.random() * 10);
        c.scale.set(2.8, 0.55, 1.3); scene.add(c); extra.clouds.push(c);
      }
      camera.position.set(0, 1.5, 10);
    } else if (id === 'planets') {
      renderer.setClearColor(0x020617, 1); addStars(1000, 80);
      scene.add(new THREE.Mesh(new THREE.SphereGeometry(1.4, 32, 32), new THREE.MeshBasicMaterial({ color: 0xffd166 })));
      scene.add(new THREE.PointLight(0xffcc66, 2, 50));
      extra.planets = [];
      [0x94a3b8, 0xf59e0b, 0x3b82f6, 0xef4444, 0xa78bfa].forEach(function (col, i) {
        var p = new THREE.Mesh(new THREE.SphereGeometry(0.25 + i * 0.08, 20, 20), new THREE.MeshStandardMaterial({ color: col, roughness: 0.4 }));
        var pivot = new THREE.Object3D();
        pivot.userData = { speed: 0.35 - i * 0.04 };
        p.position.x = 2.5 + i * 1.1; pivot.add(p); scene.add(pivot); extra.planets.push(pivot);
      });
    } else if (id === 'starfield' || id === 'sky_run') {
      renderer.setClearColor(0x000010, 1); addStars(id === 'sky_run' ? 2200 : 1600, 100);
      camera.position.set(0, 0, 8); extra.drift = id === 'sky_run' ? 0.12 : 0.04;
    } else if (id === 'aurora') {
      renderer.setClearColor(0x020617, 1); addStars(500, 60);
      extra.bands = [];
      for (var i = 0; i < 5; i++) {
        var band = new THREE.Mesh(new THREE.PlaneGeometry(40, 6, 32, 4), new THREE.MeshBasicMaterial({ color: new THREE.Color().setHSL(0.35 + i * 0.06, 0.7, 0.45), transparent: true, opacity: 0.22, side: THREE.DoubleSide }));
        band.position.set(0, 2 + i * 1.2, -10); scene.add(band); extra.bands.push(band);
      }
    } else if (id === 'ocean_waves' || id === 'ocean_fish') {
      renderer.setClearColor(0x0c4a6e, 1);
      var water = new THREE.Mesh(new THREE.PlaneGeometry(60, 60, 48, 48), new THREE.MeshStandardMaterial({ color: 0x0ea5e9, roughness: 0.25, metalness: 0.25, flatShading: true }));
      water.rotation.x = -Math.PI / 2; water.position.y = -1; scene.add(water); extra.water = water;
      camera.position.set(0, 4, 14);
      if (id === 'ocean_fish') {
        extra.fish = [];
        for (var f = 0; f < 10; f++) {
          var body = new THREE.Mesh(new THREE.SphereGeometry(0.25, 10, 10), new THREE.MeshStandardMaterial({ color: 0x38bdf8 }));
          body.scale.set(2, 0.7, 1); body.position.set((Math.random() - 0.5) * 14, Math.random() * 2, (Math.random() - 0.5) * 8);
          scene.add(body); extra.fish.push(body);
        }
      }
    } else if (id === 'jupiter') {
      renderer.setClearColor(0x020617, 1); addStars(800, 70);
      extra.jup = new THREE.Mesh(new THREE.SphereGeometry(2.2, 40, 40), new THREE.MeshStandardMaterial({ color: 0xd97706, roughness: 0.55 }));
      scene.add(extra.jup); extra.phase = 0;
      scene.add(new THREE.PointLight(0xffcc66, 1.5, 40));
    } else if (id === 'galaxy') {
      renderer.setClearColor(0x000008, 1);
      var geo = new THREE.BufferGeometry(); var n = 3500;
      var pos = new Float32Array(n * 3); var col = new Float32Array(n * 3);
      for (var i = 0; i < n; i++) {
        var arm = i % 3, a = i * 0.05 + arm * 2.1, r = (i * 0.004) % 12;
        pos[i * 3] = Math.cos(a) * r; pos[i * 3 + 1] = (Math.random() - 0.5) * 0.8; pos[i * 3 + 2] = Math.sin(a) * r;
        var c = new THREE.Color().setHSL(0.55 + arm * 0.1, 0.8, 0.6);
        col[i * 3] = c.r; col[i * 3 + 1] = c.g; col[i * 3 + 2] = c.b;
      }
      geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
      geo.setAttribute('color', new THREE.BufferAttribute(col, 3));
      extra.galaxy = new THREE.Points(geo, new THREE.PointsMaterial({ size: 0.05, vertexColors: true }));
      scene.add(extra.galaxy); camera.position.set(0, 8, 14); camera.lookAt(0, 0, 0);
    } else if (id === 'floating_orbs') {
      renderer.setClearColor(0x0f172a, 1); extra.orbs = [];
      for (var i = 0; i < 14; i++) {
        var mesh = new THREE.Mesh(new THREE.SphereGeometry(0.35 + Math.random() * 0.35, 16, 16), new THREE.MeshStandardMaterial({ color: new THREE.Color().setHSL(Math.random(), 0.7, 0.55), emissive: new THREE.Color().setHSL(Math.random(), 0.5, 0.15), transparent: true, opacity: 0.85 }));
        mesh.position.set((Math.random() - 0.5) * 12, (Math.random() - 0.5) * 7, (Math.random() - 0.5) * 8);
        mesh.userData = { sp: 0.3 + Math.random() * 0.5, ph: Math.random() * 6 };
        scene.add(mesh); extra.orbs.push(mesh);
      }
    } else if (id === 'word_forms') {
      renderer.setClearColor(0x050510, 1); addStars(700, 70); extra.blocks = [];
      for (var i = 0; i < 12; i++) {
        var beam = new THREE.Mesh(new THREE.CylinderGeometry(0.08, 0.35, 10, 12), new THREE.MeshStandardMaterial({ color: new THREE.Color().setHSL(0.55 + (i % 5) * 0.08, 0.85, 0.55), emissive: new THREE.Color().setHSL(0.55 + (i % 5) * 0.08, 0.7, 0.25), transparent: true, opacity: 0.55 }));
        beam.position.set((i - 5.5) * 1.3, 0, -6 - (i % 3)); beam.userData = { ph: i };
        scene.add(beam); extra.blocks.push(beam);
      }
      scene.add(new THREE.PointLight(0xa5b4fc, 1.2, 40)); camera.position.set(0, 2, 12);
    } else if (id === 'great_men') {
      renderer.setClearColor(0x020617, 1); addStars(900, 80); extra.figures = [];
      for (var i = 0; i < 7; i++) {
        var pillar = new THREE.Mesh(new THREE.CylinderGeometry(0.25, 0.4, 8 + i * 0.3, 16), new THREE.MeshStandardMaterial({ color: 0xfef3c7, emissive: 0xfbbf24, emissiveIntensity: 0.4, transparent: true, opacity: 0.75 }));
        pillar.position.set((i - 3) * 2.4, 1, -8); pillar.userData = { speed: 0.2 + i * 0.03 };
        scene.add(pillar); extra.figures.push(pillar);
      }
      scene.add(new THREE.PointLight(0xfbbf24, 1.4, 50)); camera.position.set(0, 3, 14);
    } else if (id === 'sunrise_ant') {
      renderer.setClearColor(0x0c1a2e, 1);
      var sun2 = new THREE.Mesh(new THREE.SphereGeometry(1.8, 40, 40), new THREE.MeshBasicMaterial({ color: 0xfcd34d }));
      sun2.position.set(0, 0.5, -16); scene.add(sun2); extra.sun = sun2;
      scene.add(new THREE.PointLight(0xfbbf24, 2.5, 80));
      scene.add(new THREE.HemisphereLight(0xfdba74, 0x0c4a6e, 0.8));
      var water2 = new THREE.Mesh(new THREE.PlaneGeometry(80, 50, 40, 20), new THREE.MeshStandardMaterial({ color: 0x0e7490, roughness: 0.2, metalness: 0.55 }));
      water2.rotation.x = -Math.PI / 2; water2.position.y = -2; scene.add(water2); extra.water = water2;
      camera.position.set(0, 2.5, 11);
    }
  }

  function tick3d() {
    animId = requestAnimationFrame(tick3d);
    if (paused || mode === 'none' || !renderer) return;
    var t = clock.getElapsedTime();
    if (starPoints) { starPoints.rotation.y += (extra.drift || 0.02) * 0.12; }
    if (extra.planets) extra.planets.forEach(function (p) { p.rotation.y += p.userData.speed * 0.01; });
    if (extra.sun) extra.sun.position.y = (extra.sunCore ? -1.2 : -0.5) + Math.sin(t * 0.15) * 0.2;
    if (extra.sunCore) extra.sunCore.position.copy(extra.sun.position);
    if (extra.clouds) extra.clouds.forEach(function(c,i){ c.position.x += 0.01*(1+i*0.03); if(c.position.x>16)c.position.x=-16; });
    if (extra.water) {
      var pos = extra.water.geometry.attributes.position;
      for (var i = 0; i < pos.count; i++) pos.setZ(i, Math.sin(pos.getX(i) * 0.3 + t) * 0.25 + Math.cos(pos.getY(i) * 0.25 + t * 0.8) * 0.2);
      pos.needsUpdate = true; extra.water.geometry.computeVertexNormals();
    }
    if (extra.fish) extra.fish.forEach(function (f, i) { f.position.y = Math.sin(t * 0.8 + i) * 1.2; f.position.x += Math.sin(t + i) * 0.015; });
    if (extra.jup) {
      extra.phase = (extra.phase || 0) + 0.004; var p = extra.phase % 2;
      if (p < 1) { extra.jup.position.x = -6 + p * 12; extra.jup.scale.setScalar(0.6 + p * 1.8); }
      else { extra.jup.position.x = 6 + (p - 1) * 8; extra.jup.scale.setScalar(2.4 - (p - 1) * 1.2); }
      extra.jup.rotation.y += 0.01;
    }
    if (extra.galaxy) extra.galaxy.rotation.y += 0.002;
    if (extra.orbs) extra.orbs.forEach(function (o) { o.position.y += Math.sin(t * o.userData.sp + o.userData.ph) * 0.01; });
    if (extra.bands) extra.bands.forEach(function (b, i) { b.position.y = 2 + i * 1.2 + Math.sin(t + i) * 0.3; });
    if (extra.figures) extra.figures.forEach(function (g) { g.rotation.y += (g.userData.speed || 0.2) * 0.01; g.position.y = 1 + Math.sin(t * (g.userData.speed || 0.3)) * 0.15; });
    if (extra.ant) { extra.ant.position.x = Math.sin(t * 0.4) * 6; }
    if (extra.blocks) extra.blocks.forEach(function (b,i) { b.position.y = Math.sin(t * 0.6 + ((b.userData && b.userData.ph) || i)) * 0.4; if (b.material) b.material.opacity = 0.4 + 0.25 * Math.sin(t + i); });
    camera.position.x = Math.sin(t * 0.15) * 0.35;
    renderer.render(scene, camera);
  }

  /* 2D fallback if Three.js fails */
  function ensure2d() {
    ensureHost();
    if (canvas2d) return;
    canvas2d = document.createElement('canvas');
    canvas2d.style.cssText = 'width:100%;height:100%;display:block;';
    canvasHost.appendChild(canvas2d);
    ctx2d = canvas2d.getContext('2d');
    onResize();
  }
  function tick2d() {
    animId = requestAnimationFrame(tick2d);
    if (paused || mode === 'none' || !ctx2d) return;
    var w = canvas2d.width, h = canvas2d.height, t = performance.now() / 1000;
    var g = ctx2d.createLinearGradient(0, 0, 0, h);
    if (mode === 'sunset' || mode === 'sunrise_ant') {
      g.addColorStop(0, '#0f172a'); g.addColorStop(0.5, '#c2410c'); g.addColorStop(1, '#fbbf24');
    } else if (mode.indexOf('ocean') >= 0) {
      g.addColorStop(0, '#0c4a6e'); g.addColorStop(1, '#22d3ee');
    } else {
      g.addColorStop(0, '#020617'); g.addColorStop(1, '#1e1b4b');
    }
    ctx2d.fillStyle = g; ctx2d.fillRect(0, 0, w, h);
    ctx2d.fillStyle = 'rgba(255,255,255,0.8)';
    for (var i = 0; i < 80; i++) {
      var x = (i * 97 + t * 20) % w, y = (i * 53) % h;
      ctx2d.fillRect(x, y, 2, 2);
    }
    if (mode === 'planets' || mode === 'jupiter') {
      ctx2d.beginPath(); ctx2d.arc(w / 2, h / 2, 40 + Math.sin(t) * 8, 0, Math.PI * 2);
      ctx2d.fillStyle = '#f59e0b'; ctx2d.fill();
    }
  }

  async function setMode(id) {
    mode = id || 'none';
    try { localStorage.setItem('cg_bg_anim', mode); } catch (e) {}
    if (mode === 'none') {
      stop();
      if (canvasHost) canvasHost.style.display = 'none';
      return;
    }
    ensureHost();
    canvasHost.style.display = 'block';
    if (use3d) {
      try {
        await loadThree();
        var THREE = global.THREE;
        if (!renderer) {
          renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
          renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
          renderer.setSize(window.innerWidth, window.innerHeight);
          canvasHost.innerHTML = '';
          canvasHost.appendChild(renderer.domElement);
          scene = new THREE.Scene();
          camera = new THREE.PerspectiveCamera(55, window.innerWidth / window.innerHeight, 0.1, 2000);
          clock = new THREE.Clock();
          window.addEventListener('resize', onResize);
        }
        buildMode(mode);
        if (!animId) tick3d();
        return;
      } catch (e) {
        console.warn('3D unavailable, using 2D fallback', e);
        use3d = false;
      }
    }
    ensure2d();
    if (!animId) tick2d();
  }

  function setPaused(p) { paused = !!p; }
  function stop() { if (animId) cancelAnimationFrame(animId); animId = null; }
  function toggleFullscreen() {
    var el = document.documentElement;
    if (!document.fullscreenElement) (el.requestFullscreen || el.webkitRequestFullscreen || function () {}).call(el);
    else (document.exitFullscreen || document.webkitExitFullscreen || function () {}).call(document);
  }
  function attachTo(el) {
    if (!el) return;
    ensureHost();
    canvasHost.style.position = 'absolute';
    canvasHost.style.zIndex = '1';
    if (!el.contains(canvasHost)) el.insertBefore(canvasHost, el.firstChild);
    onResize();
  }

  global.CGBgAnim = {
    MODES: MODES,
    setMode: setMode,
    setPaused: setPaused,
    toggleFullscreen: toggleFullscreen,
    attachTo: attachTo,
    pushSpokenWord: function () {},
    getMode: function () { return mode; },
    isPaused: function () { return paused; },
    init: function () {
      var saved = 'none';
      try { saved = localStorage.getItem('cg_bg_anim') || 'none'; } catch (e) {}
      if (saved && saved !== 'none') setMode(saved);
    },
  };
})(window);
