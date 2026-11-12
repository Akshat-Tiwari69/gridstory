/** Load a licensed glTF car and give it the same runtime API as Codex's f1car.js:
 *  +X forward, +Y up, -Z left, metres, origin on the ground at the wheelbase midpoint;
 *  userData.update(dt, {speedKmh, steer, brake}) spins the wheels and steers the fronts.
 *  The wheels in these models are merged into the body meshes, so we cut each wheel's
 *  triangles out (everything inside the tyre radius, outboard of the suspension) at load time.
 */
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';

export async function loadRealCar(THREE, url, spec) {
  const gltf = await new GLTFLoader().loadAsync(url);
  const V = a => new THREE.Vector3(...a);
  const fwd = V(spec.forward), up = V(spec.up), side = new THREE.Vector3().crossVectors(fwd, up);
  const s = spec.length / spec.lengthRaw;
  const origin = V([0, (spec.axleY[0] + spec.axleY[1]) / 2, spec.groundZ]);   // raw coords
  const toCar = new THREE.Matrix4().set(fwd.x, fwd.y, fwd.z, 0, up.x, up.y, up.z, 0, side.x, side.y, side.z, 0, 0, 0, 0, 1)
    .premultiply(new THREE.Matrix4().makeScale(s, s, s)).multiply(new THREE.Matrix4().makeTranslation(-origin.x, -origin.y, -origin.z));

  // wheel hubs in raw coords: FL, FR, RL, RR (left = +Z_car side, decided below from the basis)
  const hubs = [];
  for (const ay of spec.axleY.slice().sort((a, b) => fwd.y * (b - a))) for (const sx of [1, -1]) hubs.push({ ay, sx });
  const car = new THREE.Group(), wheels = hubs.map(h => {
    const centre = V([h.sx * spec.hubX, h.ay, spec.axleZ]).applyMatrix4(toCar);
    const pivot = new THREE.Group(), spinner = new THREE.Group(); pivot.position.copy(centre); pivot.add(spinner); car.add(pivot);
    return { ...h, centre, pivot, spinner, front: h.ay === spec.axleY.slice().sort((a, b) => fwd.y * (b - a))[0] };
  });

  const c = new THREE.Vector3(), tmp = new THREE.Vector3();
  gltf.scene.updateMatrixWorld(true);
  gltf.scene.traverse(mesh => {
    if (!mesh.isMesh) return;
    let g = mesh.geometry.index ? mesh.geometry.toNonIndexed() : mesh.geometry.clone();
    const minX = spec.wheelMeshes?.[mesh.name] ?? spec.outboardX;
    const pos = g.attributes.position, buckets = new Map();
    for (let t = 0; t < pos.count / 3; t++) {   // classify each triangle by its centroid in raw coords
      c.set(0, 0, 0); for (let k = 0; k < 3; k++) c.add(tmp.fromBufferAttribute(pos, t * 3 + k)); c.multiplyScalar(1 / 3);
      let b = -1;
      if (Math.abs(c.x) > minX) for (let w = 0; w < 4; w++) { const h = wheels[w];
        if (Math.sign(c.x) === h.sx && Math.hypot(c.y - h.ay, c.z - spec.axleZ) < spec.wheelR) { b = w; break; } }
      if (!buckets.has(b)) buckets.set(b, []); buckets.get(b).push(t);
    }
    for (const [b, tris] of buckets) {
      const part = new THREE.BufferGeometry();
      for (const [name, attr] of Object.entries(g.attributes)) {
        const n = attr.itemSize, arr = new attr.array.constructor(tris.length * 3 * n);
        tris.forEach((t, i) => arr.set(attr.array.subarray(t * 3 * n, (t + 1) * 3 * n), i * 3 * n));
        part.setAttribute(name, new THREE.BufferAttribute(arr, n, attr.normalized));
      }
      part.applyMatrix4(toCar);
      const m = new THREE.Mesh(part, mesh.material);
      if (b < 0) car.add(m); else { part.translate(-wheels[b].centre.x, -wheels[b].centre.y, -wheels[b].centre.z); wheels[b].spinner.add(m); }
    }
    g.dispose();
  });
  // these textures are DirectX-style normal maps; glTF expects OpenGL (green up)
  car.traverse(o => { if (o.isMesh && o.material.normalMap && spec.directXNormals) { o.material = o.material.clone(); o.material.normalScale.y *= -1; } });

  const r = spec.wheelR * s * 0.95;
  car.userData.update = (dt, { speedKmh = 0, steer = 0 } = {}) => {
    const roll = (speedKmh / 3.6) / r * dt;
    for (const w of wheels) { w.spinner.rotation.z -= roll; if (w.front) w.pivot.rotation.y = steer; }
  };
  // FL, FR, RL, RR from car coordinates (front = +X, left = -Z), not from the model's raw axes
  const order = wheels.slice().sort((a, b) => (b.centre.x > 0) - (a.centre.x > 0) || a.centre.z - b.centre.z);
  car.userData.wheelGroups = order.map(w => w.spinner);
  let removed = [false, false, false, false];   // persists across update(), so spinning never brings a wheel back
  car.userData.setWheelsRemoved = mask => { removed = mask.slice(0, 4); order.forEach((w, i) => { w.spinner.visible = !removed[i]; }); };
  car.userData.setCompound = () => {};
  car.userData.real = true;
  return car;
}
