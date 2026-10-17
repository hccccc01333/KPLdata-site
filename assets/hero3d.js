/* Hero「数据穹顶」：线框穹顶 + 红蓝粒子阵营 + 橙色核心（Three.js r160，本地依赖） */
import * as THREE from "./vendor/three.module.min.js";

const canvas = document.getElementById("dome");
const wrap = canvas ? canvas.parentElement : null;
if (canvas && wrap) {
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(42, 1, 0.1, 100);
  camera.position.set(0, 2.7, 11.2);

  /* ---- 穹顶线框 ---- */
  const dome = new THREE.Mesh(
    new THREE.SphereGeometry(6.4, 36, 18, 0, Math.PI * 2, 0, Math.PI / 2),
    new THREE.MeshBasicMaterial({ color: 0x3d7ea6, wireframe: true, transparent: true, opacity: 0.14 })
  );
  dome.position.y = -0.7;
  scene.add(dome);

  /* ---- 地平环（橙色，数据中心基底） ---- */
  const ring = new THREE.Mesh(
    new THREE.RingGeometry(6.32, 6.5, 128),
    new THREE.MeshBasicMaterial({ color: 0xC8C8C8, transparent: true, opacity: 0.45, side: THREE.DoubleSide })
  );
  ring.rotation.x = -Math.PI / 2;
  ring.position.y = -0.68;
  scene.add(ring);

  /* ---- 红蓝粒子阵营 ---- */
  function makeField(hex, side, count) {
    const pos = new Float32Array(count * 3);
    const seed = new Float32Array(count * 3); // bx, by, phase
    for (let i = 0; i < count; i++) {
      const bx = side * (1.1 + Math.random() * 4.6 + (Math.random() - 0.5) * 1.1);
      const by = 0.1 + Math.pow(Math.random(), 0.85) * 4.8;
      const bz = (Math.random() - 0.5) * 4.8;
      pos[i * 3] = bx; pos[i * 3 + 1] = by; pos[i * 3 + 2] = bz;
      seed[i * 3] = bx; seed[i * 3 + 1] = by; seed[i * 3 + 2] = Math.random() * Math.PI * 2;
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
    const mat = new THREE.PointsMaterial({
      color: hex, size: 0.055, transparent: true, opacity: 0.85,
      blending: THREE.AdditiveBlending, depthWrite: false, sizeAttenuation: true,
    });
    const pts = new THREE.Points(geo, mat);
    scene.add(pts);
    return { geo, seed, side };
  }
  const fieldL = makeField(0xc0392b, -1, 1500); // 红方
  const fieldR = makeField(0x4a9fd8, 1, 1500);  // 蓝方

  /* ---- 橙色核心 + 光晕 ---- */
  const core = new THREE.Mesh(
    new THREE.IcosahedronGeometry(0.46, 1),
    new THREE.MeshBasicMaterial({ color: 0xC8C8C8, wireframe: true, transparent: true, opacity: 0.95 })
  );
  core.position.y = 1.1;
  scene.add(core);

  const glowCanvas = document.createElement("canvas");
  glowCanvas.width = glowCanvas.height = 128;
  (function paintGlow() {
    const g = glowCanvas.getContext("2d");
    const rg = g.createRadialGradient(64, 64, 4, 64, 64, 62);
    rg.addColorStop(0, "rgba(255,156,40,0.95)");
    rg.addColorStop(0.35, "rgba(255,140,0,0.35)");
    rg.addColorStop(1, "rgba(255,140,0,0)");
    g.fillStyle = rg;
    g.fillRect(0, 0, 128, 128);
  })();
  const glow = new THREE.Sprite(new THREE.SpriteMaterial({
    map: new THREE.CanvasTexture(glowCanvas), transparent: true,
    blending: THREE.AdditiveBlending, depthWrite: false, opacity: 0.9,
  }));
  glow.scale.set(2.6, 2.6, 1);
  glow.position.copy(core.position);
  scene.add(glow);

  /* ---- 交互与循环 ---- */
  const mouse = { x: 0, y: 0 };
  wrap.addEventListener("pointermove", (e) => {
    const r = wrap.getBoundingClientRect();
    mouse.x = ((e.clientX - r.left) / r.width - 0.5) * 2;
    mouse.y = ((e.clientY - r.top) / r.height - 0.5) * 2;
  });

  function resize() {
    const w = wrap.clientWidth || 1, h = wrap.clientHeight || 1;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  }
  new ResizeObserver(resize).observe(wrap);
  resize();

  let running = true;
  document.addEventListener("visibilitychange", () => { running = !document.hidden; });
  new IntersectionObserver((es) => { running = es[0].isIntersecting && !document.hidden; })
    .observe(wrap);

  const clock = new THREE.Clock();
  function step() {
    requestAnimationFrame(step);
    if (!running) return;
    const t = clock.getElapsedTime();

    for (const f of [fieldL, fieldR]) {
      const arr = f.geo.attributes.position.array;
      const s = f.seed;
      const n = arr.length / 3;
      for (let i = 0; i < n; i++) {
        const by = s[i * 3 + 1] + ((t * 0.22 + s[i * 3 + 2]) % 5.4);
        arr[i * 3] = s[i * 3] + Math.sin(t * 0.5 + s[i * 3 + 2]) * 0.14;
        arr[i * 3 + 1] = by > 5.2 ? by - 5.2 : by;
        arr[i * 3 + 2] = s[i * 3 + 2] * 0.6 + Math.cos(t * 0.35 + s[i * 3 + 2]) * 0.18;
      }
      f.geo.attributes.position.needsUpdate = true;
    }

    core.rotation.y = t * 0.5;
    core.rotation.x = Math.sin(t * 0.4) * 0.35;
    glow.material.opacity = 0.75 + Math.sin(t * 1.6) * 0.12;

    const th = t * 0.055;
    camera.position.x += ((Math.sin(th) * 1.9 + mouse.x * 0.9) - camera.position.x) * 0.04;
    camera.position.y += ((2.75 + Math.sin(t * 0.12) * 0.3 - mouse.y * 0.5) - camera.position.y) * 0.05;
    camera.lookAt(0, 1.75, 0);

    renderer.render(scene, camera);
  }

  if (reduced) {
    camera.lookAt(0, 1.75, 0);
    renderer.render(scene, camera);
  } else {
    step();
  }
}
