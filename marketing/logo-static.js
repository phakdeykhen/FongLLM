(() => {
const stage = document.getElementById('stage');
const wrap = document.getElementById('wrap');
const reduce = true;
if (THREE.ColorManagement) THREE.ColorManagement.legacyMode = false;

const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true });
renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 2));
renderer.outputEncoding = THREE.sRGBEncoding;
stage.appendChild(renderer.domElement);
const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(28, 1, 0.1, 50);
camera.position.set(0, 0, 8.2);

// ---------- ribbon geometry: rounded-rect tube swept along a path, indexed in path order ----------
function ribbon(curve, { w = 0.15, d = 0.13, steps = 300, ring = 28, n = 4 } = {}) {
  const pos = [], nor = [], vU = [], idx = [];
  const Z = new THREE.Vector3(0, 0, 1);
  const sec = [];
  for (let k = 0; k < ring; k++) {
    const a = k / ring * Math.PI * 2, c = Math.cos(a), s = Math.sin(a);
    const px = Math.sign(c) * Math.pow(Math.abs(c), 2 / n), py = Math.sign(s) * Math.pow(Math.abs(s), 2 / n);
    const nx = Math.sign(c) * Math.pow(Math.abs(c), 2 - 2 / n) / w, ny = Math.sign(s) * Math.pow(Math.abs(s), 2 - 2 / n) / d;
    sec.push([px * w, py * d, nx, ny]);
  }
  const P = new THREE.Vector3(), D = new THREE.Vector3(), T = new THREE.Vector3(), v = new THREE.Vector3(), nn = new THREE.Vector3();
  for (let i = 0; i <= steps; i++) {
    const u = i / steps;
    const c = curve.getPointAt(u); T.copy(curve.getTangentAt(u)).normalize();
    P.crossVectors(Z, T); if (P.lengthSq() < 1e-6) P.set(1, 0, 0); P.normalize();
    D.crossVectors(T, P).normalize();
    for (const [x, y, nx, ny] of sec) {
      v.copy(c).addScaledVector(P, x).addScaledVector(D, y);
      nn.set(0, 0, 0).addScaledVector(P, nx).addScaledVector(D, ny).normalize();
      pos.push(v.x, v.y, v.z); nor.push(nn.x, nn.y, nn.z); vU.push(u);
    }
  }
  for (let i = 0; i < steps; i++) for (let k = 0; k < ring; k++) {
    const a = i * ring + k, b = i * ring + (k + 1) % ring, c2 = a + ring, d2 = b + ring;
    idx.push(a, c2, b, b, c2, d2);
  }
  const capAt = (i, flip) => {
    const u = i / steps, c = curve.getPointAt(u), t = curve.getTangentAt(u).normalize().multiplyScalar(flip ? 1 : -1);
    const center = pos.length / 3; pos.push(c.x, c.y, c.z); nor.push(t.x, t.y, t.z); vU.push(u);
    const base = pos.length / 3;
    for (let k = 0; k < ring; k++) { const j = (i * ring + k) * 3; pos.push(pos[j], pos[j+1], pos[j+2]); nor.push(t.x, t.y, t.z); vU.push(u); }
    for (let k = 0; k < ring; k++) flip ? idx.push(center, base + k, base + (k + 1) % ring) : idx.push(center, base + (k + 1) % ring, base + k);
  };
  capAt(steps, true); capAt(0, false);
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
  g.setAttribute('normal', new THREE.Float32BufferAttribute(nor, 3));
  g.setAttribute('pu', new THREE.Float32BufferAttribute(vU, 1));
  g.setIndex(idx);
  return g;
}

// ---------- glass shader: vertical blue to violet gradient, fresnel rim, two speculars, travelling shine ----------
const uniforms = { uTime: { value: 0 }, uShine: { value: -4 }, uDraw: { value: 1 }, uDraw2: { value: 1 } };
function glass(drawKey) {
  return new THREE.ShaderMaterial({
    uniforms: { uShine: uniforms.uShine, uMyDraw: uniforms[drawKey] },
    transparent: true,
    side: THREE.DoubleSide,
    vertexShader: `
      attribute float pu; varying float vU;
      varying vec3 vN; varying vec3 vW; varying vec3 vV; varying vec3 vL;
      void main(){
        vU = pu; vL = position;
        vec4 w = modelMatrix * vec4(position,1.0); vW = w.xyz;
        vN = normalize(mat3(modelMatrix) * normal);
        vV = normalize(cameraPosition - w.xyz);
        gl_Position = projectionMatrix * viewMatrix * w;
      }`,
    fragmentShader: `
      uniform float uShine, uMyDraw; varying float vU;
      varying vec3 vN; varying vec3 vW; varying vec3 vV; varying vec3 vL;
      void main(){
        if (vU > uMyDraw) discard;
        vec3 n = normalize(vN); if (!gl_FrontFacing) n = -n;
        float t = clamp((1.1 - vL.y) / 2.2, 0.0, 1.0);
        vec3 cTop = vec3(0.18, 0.72, 1.0), cMid = vec3(0.10, 0.30, 1.0), cBot = vec3(0.62, 0.20, 1.0);
        vec3 base = t < 0.5 ? mix(cTop, cMid, t*2.0) : mix(cMid, cBot, (t-0.5)*2.0);
        float ndv = max(dot(n, vV), 0.0);
        float fres = pow(1.0 - ndv, 2.2);
        vec3 L1 = normalize(vec3(-0.4, 0.8, 0.6)), L2 = normalize(vec3(0.7, -0.2, 0.7));
        float diff = 0.6 + 0.4 * max(dot(n, L1), 0.0);
        float s1 = pow(max(dot(reflect(-L1, n), vV), 0.0), 60.0);
        float s2 = pow(max(dot(reflect(-L2, n), vV), 0.0), 20.0);
        vec3 col = base * diff * (0.7 + 0.3 * (1.0 - pow(ndv, 3.0)));
        col += fres * mix(vec3(0.75,0.92,1.0), vec3(0.92,0.78,1.0), t) * 0.85;
        col += s1 * 1.4 + s2 * vec3(0.7,0.8,1.0) * 0.45;
        float band = exp(-pow((vW.x + vW.y*0.6 - uShine) * 3.0, 2.0));
        col += band * vec3(0.9, 0.95, 1.0) * (0.35 + fres);
        float alpha = clamp(0.8 + fres * 0.3 + s1, 0.0, 1.0);
        gl_FragColor = vec4(col, alpha);
        #include <encodings_fragment>
      }`,
  });
}

// ---------- paths ----------
const V = (x, y, z = 0) => new THREE.Vector3(x, y, z);
const aPath = new THREE.CurvePath();
aPath.add(new THREE.LineCurve3(V(0.42, -1.0), V(0.08, 0.92)));
aPath.add(new THREE.QuadraticBezierCurve3(V(0.08, 0.92), V(0.04, 1.12), V(-0.12, 1.0)));
aPath.add(new THREE.LineCurve3(V(-0.12, 1.0), V(-0.62, -0.35)));
aPath.add(new THREE.CatmullRomCurve3([
  V(-0.62, -0.35), V(-0.76, -0.68, 0.02), V(-1.02, -0.96, 0.06), V(-1.45, -0.98, 0.1),
  V(-1.66, -0.64, 0.14), V(-1.38, -0.34, 0.2), V(-0.82, -0.32, 0.3), V(-0.28, -0.46, 0.34),
  V(0.22, -0.62, 0.26), V(0.52, -0.66, 0.1)
], false, 'centripetal'));
const iPath = new THREE.LineCurve3(V(1.0, -1.0), V(1.0, 1.02));

const mark = new THREE.Group(); scene.add(mark);
const aMesh = new THREE.Mesh(ribbon(aPath, { w: 0.19, d: 0.15, steps: 420 }), glass('uDraw'));
const iMesh = new THREE.Mesh(ribbon(iPath, { w: 0.19, d: 0.15, steps: 60 }), glass('uDraw2'));
aMesh.renderOrder = 1; iMesh.renderOrder = 2;
mark.add(aMesh, iMesh);

const sparkGeo = new THREE.BufferGeometry();
const SP = 70, sp = new Float32Array(SP * 3), seeds = [];
for (let i = 0; i < SP; i++) seeds.push([Math.random()*Math.PI*2, 1.5 + Math.random()*1.1, (Math.random()-0.5)*2.4, 0.2 + Math.random()*0.5]);
sparkGeo.setAttribute('position', new THREE.BufferAttribute(sp, 3));
const sparkMat = new THREE.PointsMaterial({ color: 0x9fc4ff, size: 0.035, transparent: true, opacity: 0.0, depthWrite: false });
scene.add(new THREE.Points(sparkGeo, sparkMat));

const pointer = new THREE.Vector2(), smooth = new THREE.Vector2();
let lastMove = -10;
function onMove(e) {
  const r = stage.getBoundingClientRect(), p = e.touches ? e.touches[0] : e;
  pointer.set(((p.clientX - r.left) / r.width) * 2 - 1, -(((p.clientY - r.top) / r.height) * 2 - 1));
  lastMove = clock.getElapsedTime();
}
addEventListener('pointermove', onMove, { passive: true });
addEventListener('touchmove', onMove, { passive: true });
function resize() { const w = stage.clientWidth, h = stage.clientHeight; renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix(); }
new ResizeObserver(resize).observe(stage); resize();

const clock = new THREE.Clock();
let introStart = reduce ? -100 : 0;
const clamp01 = t => Math.min(1, Math.max(0, t));
const easeInOut = t => t < .5 ? 4*t*t*t : 1 - Math.pow(-2*t + 2, 3) / 2;
const easeOutBack = t => { const c1 = 1.4, c3 = c1 + 1; return 1 + c3 * Math.pow(t - 1, 3) + c1 * Math.pow(t - 1, 2); };

function replay() { introStart = clock.getElapsedTime(); wrap.classList.remove('play'); void wrap.offsetWidth; wrap.classList.add('play'); }
document.getElementById('replay').onclick = replay;
function setSolo(on) {
  wrap.classList.toggle('solo', on);
  document.getElementById('solo').setAttribute('aria-pressed', String(on));
  document.getElementById('lockup').setAttribute('aria-pressed', String(!on));
}
document.getElementById('solo').onclick = () => setSolo(true);
document.getElementById('lockup').onclick = () => setSolo(false);
if (location.hash === '#solo') setSolo(true);
if (!reduce) wrap.classList.add('play');

function frame() {
  const t = clock.getElapsedTime();
  const dt = Math.min(t - (frame.last ?? t), 0.05); frame.last = t;
  const it = t - introStart;
  uniforms.uDraw.value = reduce ? 1 : easeInOut(clamp01(it / 1.3));
  uniforms.uDraw2.value = reduce ? 1 : easeInOut(clamp01((it - 0.75) / 0.55));
  const settle = easeOutBack(clamp01(it / 1.6));
  mark.scale.setScalar(0.75 + 0.25 * settle);
  const spin = (1 - settle) * -1.1;
  const idle = t - lastMove > 2.5;
  const target = idle ? new THREE.Vector2(Math.sin(t * 0.6) * 0.5, Math.sin(t * 0.45) * 0.25) : pointer;
  smooth.lerp(target, 1 - Math.pow(0.004, dt));
  mark.rotation.y = spin + smooth.x * 0.45;
  mark.rotation.x = -smooth.y * 0.3;
  mark.position.set(0.12, Math.sin(t * 1.3) * 0.06, 0);
  const cyc = ((it - 1.4) % 3.2 + 3.2) % 3.2;
  uniforms.uShine.value = it < 1.4 ? -4 : -2.6 + cyc * 2.4;
  sparkMat.opacity = 0.75 * clamp01((it - 1.0) / 0.8);
  for (let i = 0; i < SP; i++) {
    const [a0, r, y0, spd] = seeds[i], a = a0 + t * spd * 0.4;
    sp[i*3] = Math.cos(a) * r; sp[i*3+1] = y0 + Math.sin(t * spd + a0) * 0.15; sp[i*3+2] = Math.sin(a) * r * 0.5 - 0.4;
  }
  sparkGeo.attributes.position.needsUpdate = true;
  renderer.render(scene, camera);
  requestAnimationFrame(frame);
}
requestAnimationFrame(frame);
window.__fong = { replay, setSolo };
})();
