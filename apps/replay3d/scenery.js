/** Generic night-race architecture. Metres, +Y up. No assets, logos or dependencies. */
function kit(THREE) {
  const group = new THREE.Group(), bins = new Map(), materials = new Map();
  const v = p => new THREE.Vector3(...p);
  const white = new THREE.Color('#ffffff');
  const definitions = {
    concrete: { color: '#686b6b', roughness: .87 },
    steel: { color: '#87909b', roughness: .43, metalness: .76 },
    roof: { color: '#89939a', roughness: .65, metalness: .20 },
    dark: { color: '#17212a', roughness: .73, metalness: .22 },
    glass: { color: '#23424f', roughness: .23, metalness: .60, envMapIntensity: .14 },
    warm: { color: '#ac8b60', roughness: .50, emissive: '#ffb66b', emissiveIntensity: .48 },
    foliage: { color: '#ffffff', roughness: .91 },
  };
  function material(key) {
    if (!materials.has(key)) {
      const common = { vertexColors: true, side: THREE.DoubleSide };
      const m = key === 'light' ? new THREE.MeshBasicMaterial({ ...common, toneMapped: false })
        : new THREE.MeshStandardMaterial({ ...common, envMapIntensity: .04, ...definitions[key] });
      m.name = `Scenery ${key}`; materials.set(key, m);
    }
    return materials.get(key);
  }
  function add(key, geo, color = white, position = [0, 0, 0], rotation = [0, 0, 0]) {
    const c = color?.isColor ? color : new THREE.Color(color);
    geo.rotateX(rotation[0]); geo.rotateY(rotation[1]); geo.rotateZ(rotation[2]); geo.translate(...position);
    if (!geo.attributes.normal) geo.computeVertexNormals();
    const flat = geo.index ? geo.toNonIndexed() : geo;
    if (flat !== geo) geo.dispose();
    const data = new Float32Array(flat.attributes.position.count * 3);
    for (let i = 0; i < data.length; i += 3) { data[i] = c.r; data[i + 1] = c.g; data[i + 2] = c.b; }
    flat.setAttribute('color', new THREE.BufferAttribute(data, 3));
    if (!bins.has(key)) bins.set(key, []); bins.get(key).push(flat);
  }
  function box(key, p, size, color = white, rotation = [0, 0, 0]) { add(key, new THREE.BoxGeometry(...size), color, p, rotation); }
  function beam(key, a, b, r = .055, color = white) {
    const start = v(a), end = v(b), delta = end.clone().sub(start);
    if (delta.lengthSq() < 1e-10) return;
    const geo = new THREE.CylinderGeometry(r, r, delta.length(), 6);
    geo.applyQuaternion(new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0, 1, 0), delta.normalize()));
    add(key, geo, color, start.add(end).multiplyScalar(.5).toArray());
  }
  function quad(key, a, b, c, d, color = white) {
    const geo = new THREE.BufferGeometry();
    const triangle = c.every((value, i) => value === d[i]);
    geo.setAttribute('position', new THREE.Float32BufferAttribute(triangle ? [...a, ...b, ...c] : [...a, ...b, ...c, ...d], 3));
    geo.setIndex(triangle ? [0, 1, 2] : [0, 1, 2, 0, 2, 3]); geo.computeVertexNormals(); add(key, geo, color);
  }
  function cylinder(key, radius, height, y, color = white, segments = 40, radiusTop = radius) {
    add(key, new THREE.CylinderGeometry(radiusTop, radius, height, segments), color, [0, y, 0]);
  }
  function ring(key, radius, y, thickness = .035, color = white) {
    add(key, new THREE.TorusGeometry(radius, thickness, 4, 48), color, [0, y, 0], [Math.PI / 2, 0, 0]);
  }
  function steps(x, width, count, tread, rise, y = 0, z = 0, base = 0) {
    const shape = new THREE.Shape(); shape.moveTo(0, base); shape.lineTo(0, y + rise);
    for (let i = 0; i < count; i++) {
      shape.lineTo((i + 1) * tread, y + (i + 1) * rise);
      if (i < count - 1) shape.lineTo((i + 1) * tread, y + (i + 2) * rise);
    }
    shape.lineTo(count * tread, base); shape.closePath();
    const geo = new THREE.ExtrudeGeometry(shape, { depth: width, bevelEnabled: false, steps: 1, curveSegments: 1 });
    geo.rotateY(Math.PI / 2); add('concrete', geo, white, [x, 0, z]);
  }
  function finish(name) {
    group.name = name;
    for (const [key, parts] of bins) {
      const count = parts.reduce((n, g) => n + g.attributes.position.count, 0), geo = new THREE.BufferGeometry();
      for (const attribute of ['position', 'normal', 'color']) {
        const array = new Float32Array(count * 3); let offset = 0;
        for (const part of parts) { array.set(part.attributes[attribute].array, offset); offset += part.attributes[attribute].array.length; }
        geo.setAttribute(attribute, new THREE.BufferAttribute(array, 3));
      }
      parts.forEach(g => g.dispose()); geo.computeBoundingBox(); geo.computeBoundingSphere();
      const mesh = new THREE.Mesh(geo, material(key)); mesh.name = `${name}: ${key}`;
      mesh.castShadow = key !== 'light' && key !== 'warm'; mesh.receiveShadow = key !== 'light'; group.add(mesh);
    }
    let triangles = 0, drawCalls = 0;
    group.traverse(o => { if (o.isMesh) { drawCalls++; triangles += (o.geometry.index?.count ?? o.geometry.attributes.position.count) / 3 * (o.isInstancedMesh ? o.count : 1); } });
    group.userData.stats = { drawCalls, triangles };
    group.userData.dispose = () => {
      const geometries = new Set(), mats = new Set();
      group.traverse(o => { if (o.isMesh) { geometries.add(o.geometry); mats.add(o.material); } });
      geometries.forEach(g => g.dispose()); mats.forEach(m => m.dispose());
    };
    return group;
  }
  return { group, add, box, beam, quad, cylinder, ring, steps, finish, material };
}

function random(seed) {
  return () => { seed = (Math.imul(1664525, seed) + 1013904223) >>> 0; return seed / 4294967296; };
}
function dimension(value, fallback, min, max, name) {
  value ??= fallback;
  if (!Number.isFinite(value) || value < min || value > max) throw new RangeError(`${name} must be ${min}..${max}`);
  return value;
}

/** Ground-centred, 52.5 m generic hospitality / race-control landmark. */
export function buildTower(THREE) {
  const k = kit(THREE), rng = random(71), bright = new THREE.Color(3.5, 2.7, 1.8);
  k.cylinder('concrete', 8.2, .45, .225, '#b8b2a4', 48);
  k.cylinder('dark', 3.1, 47, 23.7, '#b9c1c6', 40);
  k.cylinder('concrete', 4.8, .35, 6.8, '#ded6c1');
  for (let i = 0; i < 6; i++) {
    const a = i / 6 * Math.PI * 2;
    k.beam('concrete', [Math.cos(a) * 4, .45, Math.sin(a) * 4], [Math.cos(a) * 2.4, 7.2, Math.sin(a) * 2.4], .40);
  }
  // Faceted-curved glazing and separated floor slabs create real depth at silhouette.
  for (let floor = 0; floor < 10; floor++) {
    const y = 7.2 + floor * 3.95, radius = floor >= 8 ? 6.8 + (floor - 8) * .45 : 4.9 + .14 * Math.sin(floor * .7);
    k.cylinder('concrete', radius + .48, .20, y, '#dad4c8', 48);
    k.cylinder('steel', radius + .30, .075, y + .21, '#82949f', 48);
    k.ring('light', radius + .33, y + .11, .028, bright);
    for (let panel = 0; panel < 32; panel++) {
      const a = panel / 32 * Math.PI * 2, b = (panel + 1) / 32 * Math.PI * 2;
      const point = (angle, height, r = radius) => [Math.cos(angle) * r, height, Math.sin(angle) * r];
      k.quad(rng() < .53 ? 'warm' : 'glass', point(a + .009, y + .34), point(b - .009, y + .34), point(b - .009, y + 3.58), point(a + .009, y + 3.58));
      k.beam('steel', point(a, y + .23, radius + .025), point(a, y + 3.78, radius + .025), .035, '#b2bfc5');
      if (panel % 4 === 0) k.beam('concrete', point(a, y + .25, radius + .15), point(a, y + 3.75, radius + .15), .07, '#ded6c4');
    }
    k.ring('steel', radius + .23, y + 1.08, .022, '#c1c9c8');
    k.ring('steel', radius + .22, y + 3.63, .026);
  }
  k.cylinder('roof', 7.95, .24, 47.35, '#d0c8b6', 64, 7.65);
  k.cylinder('roof', 7.65, .55, 47.72, '#dfd8c6', 64, 5.9);
  k.ring('light', 7.8, 47.3, .045, bright);
  k.cylinder('steel', .09, 4.2, 50.1, '#d5d7d7', 10, .055);
  k.cylinder('dark', .42, .35, 48.2, '#677b87', 16);
  k.add('light', new THREE.SphereGeometry(.13, 12, 8), new THREE.Color(5, .08, .025), [0, 52.31, 0]);
  for (let i = 0; i < 3; i++) k.beam('steel', [0, 49.8, 0], [Math.cos(i * 2.094) * 1.1, 48.2, Math.sin(i * 2.094) * 1.1], .018);
  // Ground entrance, curved canopy and radial approach stair.
  for (let j = 0; j < 3; j++) k.box('concrete', [0, .12 + j * .12, 6.1 - j * .5], [4.2, .24, 2.2 - j * .35], '#bbb4a4');
  k.quad('warm', [-1.35, .4, 3.14], [1.35, .4, 3.14], [1.35, 4.5, 3.14], [-1.35, 4.5, 3.14]);
  k.box('roof', [0, 4.8, 4.5], [5.3, .14, 4.0], '#c6c7c3', [-.10, 0, 0]);
  return k.finish('Illuminated hospitality tower');
}

/** Front-left origin (0,0,0); front edge along +X, tiers rise toward -Z. */
export function buildGrandstand(THREE, { length = 72, rows = 12 } = {}) {
  length = dimension(length, 72, 12, 300, 'length');
  rows = dimension(rows, 12, 3, 40, 'rows');
  if (!Number.isInteger(rows)) throw new RangeError('rows must be an integer');
  const k = kit(THREE), rng = random(1021), tread = .88, rise = .43, depth = rows * tread;
  const high = rows * rise + 3.7, frameCount = Math.max(2, Math.ceil(length / 12));
  const aisleCount = Math.max(1, Math.floor(length / 24));
  const aisles = Array.from({ length: aisleCount }, (_, i) => length * (i + 1) / (aisleCount + 1));
  const aisleWidth = 1.75, cuts = [0, ...aisles.flatMap(x => [x - aisleWidth / 2, x + aisleWidth / 2]), length];
  for (let i = 0; i < cuts.length - 1; i += 2) k.steps(cuts[i], cuts[i + 1] - cuts[i], rows, tread, rise);
  for (const x of aisles) {
    // Half-height aisle steps and a true unfilled opening beneath the upper landing.
    k.steps(x - aisleWidth / 2, aisleWidth, 6, tread / 2, rise / 2);
    if (rows > 4) k.steps(x - aisleWidth / 2, aisleWidth, (rows - 3) * 2, tread / 2, rise / 2, rise * 3, -tread * 3, rise * 2.25);
    k.box('dark', [x, .7, -tread * 3 - .03], [aisleWidth - .2, 1.25, .025]);
    k.box('concrete', [x - aisleWidth / 2 + .07, .8, -tread * 3], [.14, 1.6, .7]);
    k.box('concrete', [x + aisleWidth / 2 - .07, .8, -tread * 3], [.14, 1.6, .7]);
    k.box('light', [x, 1.5, -tread * 3 + .04], [.45, .09, .04], new THREE.Color(.1, 2.5, .7));
    for (const side of [-1, 1]) {
      const railX = x + side * (aisleWidth / 2 - .08);
      k.beam('steel', [railX, 1.25, -.15], [railX, rows * rise + .95, -depth + .15], .025);
      for (let j = 0; j < rows; j += 3) k.beam('steel', [railX, (j + 1) * rise, -(j + .5) * tread], [railX, (j + 1) * rise + .90, -(j + .5) * tread], .024);
    }
  }
  // Rear columns carry a cantilever: no posts along the spectator sightline.
  for (let i = 0; i <= frameCount; i++) {
    const x = length * i / frameCount;
    k.beam('steel', [x, 0, -depth - .8], [x, high + .3, -depth - .8], .16);
    k.beam('steel', [x, high - 2.1, -depth - .8], [x, high - .6, 1.6], .075);
    k.beam('steel', [x, high + .3, -depth - 1.2], [x, high - .05, 1.6], .075);
    for (let j = 0; j < 6; j++) {
      const z = -depth - 1.2 + (depth + 2.8) * j / 6, z2 = z + (depth + 2.8) / 6;
      const top = high + .3 - .35 * j / 6, lower = high - 2.1 + 1.5 * j / 6;
      k.beam('steel', [x, j % 2 ? top : lower, z], [x, j % 2 ? lower + .25 : top - .05, z2], .040);
    }
    k.beam('steel', [x, 1, -depth - .8], [x, high - 2.1, -depth + 1.7], .06);
    if (i) {
      const previous = length * (i - 1) / frameCount;
      k.beam('steel', [previous, .4, -depth - .85], [x, high - 1.0, -depth - .85], .035);
      k.beam('steel', [x, .4, -depth - .85], [previous, high - 1.0, -depth - .85], .035);
    }
  }
  // Curved metal canopy, seams and individual underside luminaires.
  for (let i = 0; i < frameCount * 2; i++) for (let j = 0; j < 8; j++) {
    const x = length * i / (frameCount * 2) - .5, x2 = length * (i + 1) / (frameCount * 2) + .5;
    const z = 1.8 - (depth + 3.1) * j / 8, z2 = 1.8 - (depth + 3.1) * (j + 1) / 8;
    const roofY = z => high + .20 - .30 * ((z + depth + 1.3) / (depth + 3.1)) ** 2;
    k.quad('roof', [x, roofY(z), z], [x2, roofY(z), z], [x2, roofY(z2), z2], [x, roofY(z2), z2]);
  }
  k.beam('steel', [-.5, high - .10, 1.8], [length + .5, high - .10, 1.8], .065);
  k.box('roof', [length / 2, high - .1, 1.82], [length + 1, .34, .10], '#cfd4d6');
  for (let x = 3; x < length; x += 6) {
    k.box('light', [x, high - .44, -.7], [1.45, .055, .15], new THREE.Color(3.6, 3.4, 2.8));
    k.box('light', [x, high - .25, -depth + 1], [1.0, .055, .15], new THREE.Color(3.2, 3.1, 2.8));
  }
  k.box('dark', [length / 2, rows * rise / 2, -depth - .75], [length, rows * rise, .18]);
  for (let y = rows * rise + .5; y < high - .7; y += .3) k.box('steel', [length / 2, y, -depth - .8], [length, .055, .12], '#586570');
  for (const x of [0, length]) {
    k.beam('steel', [x, 1.2, .1], [x, rows * rise + 1, -depth], .03);
    for (let r = 0; r < rows; r += 2) k.beam('steel', [x, (r + 1) * rise, -(r + .4) * tread], [x, (r + 1) * rise + .9, -(r + .4) * tread], .025);
  }
  // Physical moulded seats, plus two instanced meshes for varied 3D spectators.
  const seatPositions = [], people = [];
  const coats = ['#ad6b50', '#d4c7aa', '#476383', '#59604c', '#8b3d3e', '#b6b9b9', '#303e54', '#a79c7a'];
  const heads = ['#b47f5b', '#d3a379', '#8d5b3f', '#60432f', '#d7bc9b', '#323035'];
  for (let row = 0; row < rows; row++) for (let x = .65; x < length - .4; x += .64) {
    if (aisles.some(a => Math.abs(x - a) < aisleWidth / 2 + .25)) continue;
    const y = (row + 1) * rise, z = -(row + .51) * tread;
    seatPositions.push([x, y, z]);
    if (rng() > .17) people.push({ x: x + (rng() - .5) * .07, y, z, coat: coats[Math.floor(rng() * coats.length)], skin: heads[Math.floor(rng() * heads.length)], lean: (rng() - .5) * .16 });
  }
  const seatGeometry = new THREE.BufferGeometry();
  const cross = [[.24, .13], [-.16, .13], [-.24, .26], [-.20, .61]], seatVertices = [], seatIndices = [];
  cross.forEach(([z, y]) => seatVertices.push(-.22, y, z, .22, y, z));
  for (let i = 0; i < cross.length - 1; i++) { const a = i * 2; seatIndices.push(a, a + 1, a + 2, a + 1, a + 3, a + 2); }
  seatGeometry.setAttribute('position', new THREE.Float32BufferAttribute(seatVertices, 3)); seatGeometry.setIndex(seatIndices); seatGeometry.computeVertexNormals();
  const seatMaterial = new THREE.MeshStandardMaterial({ color: '#3d535e', roughness: .78, side: THREE.DoubleSide, envMapIntensity: .04 });
  const seats = new THREE.InstancedMesh(seatGeometry, seatMaterial, seatPositions.length); seats.name = 'Individual moulded seats';
  const jacketMaterial = new THREE.MeshStandardMaterial({ color: '#8b8f95', roughness: .95, emissive: '#0d1118', emissiveIntensity: .5, envMapIntensity: .04 });
  const skinMaterial = new THREE.MeshStandardMaterial({ color: '#a59b91', roughness: .9, envMapIntensity: .04 });
  const bodies = new THREE.InstancedMesh(new THREE.CylinderGeometry(.15, .20, .36, 6), jacketMaterial, people.length); bodies.name = 'Varied spectator coats';
  const faces = new THREE.InstancedMesh(new THREE.IcosahedronGeometry(.105, 0), skinMaterial, people.length); faces.name = 'Spectator heads';
  const dummy = new THREE.Object3D(), color = new THREE.Color();
  seatPositions.forEach((p, i) => { dummy.position.set(...p); dummy.updateMatrix(); seats.setMatrixAt(i, dummy.matrix); });
  people.forEach((p, i) => {
    dummy.position.set(p.x, p.y + .48, p.z - .06); dummy.rotation.x = p.lean; dummy.updateMatrix(); bodies.setMatrixAt(i, dummy.matrix); bodies.setColorAt(i, color.set(p.coat));
    dummy.position.set(p.x, p.y + .80, p.z - .06 + p.lean * .15); dummy.rotation.set(0, i * .37, 0); dummy.updateMatrix(); faces.setMatrixAt(i, dummy.matrix); faces.setColorAt(i, color.set(p.skin));
  });
  for (const mesh of [seats, bodies, faces]) { mesh.instanceMatrix.needsUpdate = true; if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true; mesh.receiveShadow = true; k.group.add(mesh); }
  const group = k.finish('Cantilever grandstand'); group.userData.seats = seatPositions.length; group.userData.spectators = people.length;
  group.userData.front = '+Z'; group.userData.length = length; group.userData.rows = rows;
  return group;
}

/** Single vertex-coloured mesh suitable for a whole avenue in one InstancedMesh. */
export function buildPalm(THREE) {
  const k = kit(THREE), rng = random(53), trunk = new THREE.CatmullRomCurve3([
    new THREE.Vector3(0, 0, 0), new THREE.Vector3(.15, 3.4, .12), new THREE.Vector3(.62, 6.9, .04), new THREE.Vector3(.95, 9.65, -.13),
  ]);
  const positions = [], indices = [], rings = 50, sides = 8;
  for (let j = 0; j <= rings; j++) {
    const t = j / rings, p = trunk.getPoint(t), tangent = trunk.getTangent(t), normal = new THREE.Vector3(1, 0, 0).cross(tangent).normalize(), binormal = tangent.clone().cross(normal).normalize();
    const radius = (.245 - t * .12) * (j % 2 ? 1.09 : .97);
    for (let i = 0; i < sides; i++) {
      const a = i / sides * Math.PI * 2, q = p.clone().addScaledVector(normal, Math.cos(a) * radius).addScaledVector(binormal, Math.sin(a) * radius);
      positions.push(q.x, q.y, q.z);
      if (j < rings) { const n = j * sides + i, next = j * sides + (i + 1) % sides; indices.push(n, next, n + sides, next, next + sides, n + sides); }
    }
  }
  const geo = new THREE.BufferGeometry(); geo.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3)); geo.setIndex(indices); geo.computeVertexNormals();
  k.add('foliage', geo, '#81715a');
  const crown = trunk.getPoint(1);
  k.add('foliage', new THREE.IcosahedronGeometry(.36, 1), '#5b6531', crown.toArray());
  for (let frond = 0; frond < 13; frond++) {
    const a = frond * Math.PI * 2 / 13 + rng() * .12, length = 3.7 + rng() * .9, droop = 1.5 + rng() * 1.2;
    const point = t => [crown.x + Math.cos(a) * length * t, crown.y + Math.sin(Math.PI * t) * (1 + (frond % 3) * .15) - droop * t * t, crown.z + Math.sin(a) * length * t];
    const rachis = new THREE.CatmullRomCurve3(Array.from({ length: 13 }, (_, s) => new THREE.Vector3(...point(s / 12))));
    k.add('foliage', new THREE.TubeGeometry(rachis, 12, .013, 3, false), '#6b7a3d');
    for (let s = 1; s < 19; s++) {
      const t = s / 20, p = point(t), width = Math.sin(t * Math.PI) ** .7 * .76;
      for (const side of [-1, 1]) {
        const crossX = -Math.sin(a) * side, crossZ = Math.cos(a) * side;
        const tip = [p[0] + crossX * width + Math.cos(a) * .25, p[1] - .15 - width * .35, p[2] + crossZ * width + Math.sin(a) * .25];
        const mid = [(p[0] + tip[0]) / 2, (p[1] + tip[1]) / 2 + .06, (p[2] + tip[2]) / 2];
        k.quad('foliage', p, [mid[0] - Math.cos(a) * .055, mid[1], mid[2] - Math.sin(a) * .055], tip,
          [mid[0] + Math.cos(a) * .055, mid[1] + .025, mid[2] + Math.sin(a) * .055], frond % 3 ? '#3b603b' : '#597843');
      }
    }
  }
  const group = k.finish('Date palm'), mesh = group.children[0];
  mesh.geometry.userData.stats = group.userData.stats;
  return { geometry: mesh.geometry, material: mesh.material };
}

/** Ground-centred post, observer/front side +Z. */
export function buildMarshalPost(THREE) {
  const k = kit(THREE), white = '#d1d0c5';
  k.box('concrete', [0, .17, 0], [3.8, .34, 3.0]);
  for (let i = 0; i < 2; i++) k.box('concrete', [0, .08 + .08 * i, 1.6 + (1 - i) * .28], [1.5, .16 + .16 * i, .6]);
  for (const x of [-1.55, 1.55]) for (const z of [-1.15, 1.15]) k.beam('steel', [x, .34, z], [x, 3.12, z], .055);
  k.box('concrete', [0, .75, -1.15], [3.2, .82, .12], white);
  for (const x of [-1.55, 1.55]) {
    k.box('roof', [x, .75, 0], [.10, .82, 2.3], white);
    k.quad('glass', [x, 1.16, -1.15], [x, 1.16, 1.15], [x, 2.5, 1.15], [x, 2.5, -1.15]);
  }
  k.quad('glass', [-1.55, 1.15, -1.15], [1.55, 1.15, -1.15], [1.55, 2.6, -1.15], [-1.55, 2.6, -1.15]);
  for (let i = 0; i < 6; i++) {
    const x = -1.95 + i * .65, x2 = x + .65, y = 3.0 + .25 * Math.sin(i / 6 * Math.PI), y2 = 3.0 + .25 * Math.sin((i + 1) / 6 * Math.PI);
    k.quad('roof', [x, y, 1.7], [x2, y2, 1.7], [x2, y2, -1.7], [x, y, -1.7], white);
  }
  k.beam('steel', [-1.9, 2.94, 1.7], [1.9, 2.94, 1.7], .035);
  k.box('light', [0, 2.95, .25], [1.8, .05, .18], new THREE.Color(3.4, 3.3, 2.9));
  k.box('dark', [.76, 1.75, 1.25], [1.15, .72, .14]);
  for (let y = 0; y < 3; y++) for (let x = 0; x < 5; x++) k.add('light', new THREE.CircleGeometry(.052, 8), new THREE.Color(4.2, 2.5, .025), [.36 + x * .20, 1.54 + y * .20, 1.326]);
  k.beam('steel', [-1.26, 1.3, 1.35], [-1.26, 2.65, 1.35], .022);
  k.quad('roof', [-1.24, 2.61, 1.35], [-.50, 2.46, 1.43], [-.56, 2.02, 1.54], [-1.24, 2.18, 1.35], '#edbd24');
  return k.finish('Covered marshal post');
}

/** Front face z=0 looks toward +Z; length along +X, building depth toward -Z. */
export function buildPaddockBuilding(THREE, { length = 72 } = {}) {
  length = dimension(length, 72, 12, 300, 'length');
  const k = kit(THREE), rng = random(912), depth = 16;
  k.box('concrete', [length / 2, .20, -depth / 2], [length, .4, depth], '#ada999');
  k.box('dark', [length / 2, 1.8, -depth + .25], [length, 3.2, .5]);
  k.box('concrete', [length / 2, 1.8, -depth / 2], [length, 3.2, depth - 1.6], '#969c9b');
  for (let x = 1.0; x + 3.1 <= length - .25; x += 5.8) {
    k.box('dark', [x + 1.6, 1.65, -.75], [2.9, 2.6, .04]);
    k.box('steel', [x + 1.6, 2.98, -.69], [3.0, .10, .10]);
    k.box('light', [x + 1.6, 3.18, -.80], [1.6, .055, .13], new THREE.Color(2.6, 2.7, 2.6));
  }
  for (let floor = 0; floor < 3; floor++) {
    const y = 3.7 + floor * 3.55;
    k.box('concrete', [length / 2, y, -depth / 2], [length, .22, depth], '#d1cbc0');
    k.box('roof', [length / 2, y + .20, -.22], [length, .12, .42], '#d1d4ce');
    k.box('light', [length / 2, y + .08, -.045], [length - .5, .035, .035], new THREE.Color(2.7, 2.1, 1.45));
    for (let x = .3; x < length - .3; x += 2.15) {
      const end = Math.min(x + 2.02, length - .25), key = rng() < .57 ? 'warm' : 'glass';
      k.quad(key, [x, y + .3, -1.15], [end, y + .3, -1.15], [end, y + 3.23, -1.15], [x, y + 3.23, -1.15]);
      k.beam('steel', [x - .04, y + .25, -1.1], [x - .04, y + 3.30, -1.1], .025, '#b4bfc2');
      // Real balcony barrier, visibly separate from recessed glazing.
      k.quad('glass', [x, y + .30, -.09], [end, y + .30, -.09], [end, y + 1.18, -.09], [x, y + 1.18, -.09], '#b5c4c5');
    }
    k.beam('steel', [.15, y + 1.22, -.06], [length - .15, y + 1.22, -.06], .022);
    for (const x of [.05, length - .05]) k.quad('glass', [x, y + .25, -1.15], [x, y + .25, -depth + .15], [x, y + 3.27, -depth + .15], [x, y + 3.27, -1.15]);
    for (let x = 0; x <= length; x += 6) k.box('roof', [x, y + 1.72, -.55], [.10, 3.1, 1.0], '#d4cfc3', [0, .18, 0]);
  }
  const top = 14.5;
  k.box('concrete', [length / 2, top, -depth / 2], [length, .28, depth], '#d8d2c5');
  k.beam('steel', [.08, top + 1.18, -.05], [length - .08, top + 1.18, -.05], .025);
  for (let x = .1; x < length; x += 2.2) k.beam('steel', [x, top + .15, -.05], [x, top + 1.18, -.05], .019);
  for (let x = 3; x < length - 2; x += 8) {
    // Tensile terrace sails form a recognisable, non-box roof silhouette.
    const sail = [[x - 3.4, top + 2.0, -2], [x + 3.4, top + 2.9, -2], [x + 3.4, top + 2.0, -10], [x - 3.4, top + 2.9, -10]];
    const centre = [x, top + 2.0, -6];
    for (let i = 0; i < 4; i++) { k.quad('roof', sail[i], sail[(i + 1) % 4], centre, centre, '#e4dac8'); k.beam('steel', [sail[i][0], top + .15, sail[i][2]], sail[i], .035); }
    k.box('light', [x, top + 2.05, -5.5], [1.4, .05, .15], new THREE.Color(3.0, 2.45, 1.7));
    k.add('steel', new THREE.CylinderGeometry(.58, .58, .07, 12), '#b3aa9a', [x, top + .92, -4]);
    k.beam('steel', [x, top + .15, -4], [x, top + .91, -4], .04);
  }
  // Rear service spine, louvres and rooftop plant screens, all merged.
  k.box('dark', [length / 2, 8.8, -depth + .1], [length, 11.4, .20]);
  for (let y = 4.0; y < 14.0; y += .43) k.box('steel', [length / 2, y, -depth - .06], [length, .07, .14], '#6d7d86');
  for (let x = 6; x < length; x += 18) k.box('dark', [x, top + .7, -13.5], [5.0, 1.3, 3.0], '#555e62');
  return k.finish('Glazed paddock hospitality building');
}
