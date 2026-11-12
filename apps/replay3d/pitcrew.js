/** Generic, articulated pit crew. Metres; car faces +X, ground at Y=0.
 * Host applies group.userData.carLift and wheelsRemoved to its own car.
 * wheelsRemoved order: front-left (-Z), front-right, rear-left, rear-right.
 */
export function buildPitCrew(THREE, { kit = '#23363a', side = 1 } = {}) {
  if (side !== 1 && side !== -1) throw new RangeError('Garage side must be +1 or -1');
  const group = new THREE.Group(); group.name = 'Generic 18-person pit crew';
  const kitColor = new THREE.Color(kit), trimColor = kitColor.clone().lerp(new THREE.Color('#f3f4ef'), .42);
  const suitMaterial = new THREE.MeshStandardMaterial({ color: kitColor, roughness: .86, metalness: .02, side: THREE.DoubleSide });
  const darkMaterial = new THREE.MeshStandardMaterial({ color: '#10151a', roughness: .65, metalness: .15, side: THREE.DoubleSide });
  const helmetMaterial = new THREE.MeshPhysicalMaterial({ color: kitColor, roughness: .29, clearcoat: .8, metalness: .2 });
  const visorMaterial = new THREE.MeshPhysicalMaterial({ color: '#131e26', roughness: .16, metalness: .8 });
  const stripeMaterial = new THREE.MeshStandardMaterial({ color: trimColor, roughness: .65 });
  const metalMaterial = new THREE.MeshStandardMaterial({ color: '#727b80', roughness: .37, metalness: .83 });
  const rubberMaterial = new THREE.MeshStandardMaterial({ color: '#101114', roughness: .95 });
  const allInstances = [];
  const vector = (x, y, z) => new THREE.Vector3(x, y, z);
  const UP = vector(0, 1, 0), q = new THREE.Quaternion(), matrix = new THREE.Matrix4();
  const pos = new THREE.Vector3(), scale = new THREE.Vector3(), delta = new THREE.Vector3();

  function profile(sections, segments = 12) {
    const positions = [], indices = [];
    sections.forEach(([y, width, depth, offset = 0]) => {
      for (let i = 0; i < segments; i++) {
        const a = i / segments * Math.PI * 2;
        positions.push(Math.cos(a) * width, y, Math.sin(a) * depth + offset);
      }
    });
    for (let j = 0; j < sections.length - 1; j++) for (let i = 0; i < segments; i++) {
      const a = j * segments + i, b = j * segments + (i + 1) % segments;
      indices.push(a, a + segments, b, b, a + segments, b + segments);
    }
    for (let end = 0; end < 2; end++) {
      const j = end ? sections.length - 1 : 0, first = positions.length / 3;
      positions.push(0, sections[j][0], sections[j][3] || 0);
      for (let i = 0; i < segments; i++) {
        const a = j * segments + i, b = j * segments + (i + 1) % segments;
        indices.push(first, ...(end ? [b, a] : [a, b]));
      }
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
    geo.setIndex(indices); geo.computeVertexNormals(); return geo;
  }

  function instances(name, geometry, material, count) {
    const mesh = new THREE.InstancedMesh(geometry, material, count); mesh.name = name;
    mesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
    mesh.frustumCulled = false; mesh.castShadow = mesh.receiveShadow = true;
    group.add(mesh); allInstances.push(mesh); return mesh;
  }

  const torsos = instances('Tailored suit jackets', profile([[0, .14, .095], [.10, .15, .105], [.33, .215, .11], [.41, .17, .095], [.445, .075, .075]]), suitMaterial, 18);
  const hips = instances('Suit trousers', profile([[-.10, .14, .10], [.02, .16, .10], [.13, .14, .095]]), suitMaterial, 18);
  const limbs = instances('Articulated arms and legs', profile([[0, .72, .73], [.10, .96, .94], [.40, 1, .94], [.75, .80, .78], [1, .64, .65]], 10), suitMaterial, 144);
  const joints = instances('Elbows and knee protection', new THREE.SphereGeometry(1, 10, 7), darkMaterial, 72);
  const boots = instances('Shaped work boots', profile([[0, .065, .15, .025], [.055, .075, .17, .03], [.12, .06, .10, -.025], [.19, .052, .07, -.05]], 12), darkMaterial, 36);
  const gloves = instances('Work gloves', new THREE.SphereGeometry(1, 10, 7), darkMaterial, 36);
  const helmets = instances('Full face pit helmets', profile([[0, .10, .12], [.045, .135, .145], [.16, .145, .15], [.245, .12, .13], [.29, .04, .05]], 20), helmetMaterial, 18);
  const visorGeometry = new THREE.SphereGeometry(1, 18, 8, Math.PI * .10, Math.PI * .80, Math.PI * .32, Math.PI * .22);
  visorGeometry.rotateY(Math.PI / 2);
  const visors = instances('Dark curved helmet visors', visorGeometry, visorMaterial, 18);
  const shoulderStripes = instances('Unbranded shoulder inserts', profile([[0, .19, .11], [.025, .19, .11]], 12), stripeMaterial, 18);
  const guns = instances('Four wheel guns', new THREE.CylinderGeometry(.055, .065, .22, 10), metalMaterial, 4);
  const tyreProfile = [[.23, -.16], [.31, -.17], [.35, -.13], [.36, -.09], [.36, .09], [.35, .13], [.31, .17], [.23, .16]];
  const spareGeometry = new THREE.LatheGeometry(tyreProfile.map(([r, z]) => new THREE.Vector2(r, z)), 32);
  spareGeometry.rotateX(Math.PI / 2);
  const spareTyres = instances('Removed and replacement tyres', spareGeometry, rubberMaterial, 8);
  const spareRims = instances('Spare wheel faces', new THREE.TorusGeometry(.23, .012, 6, 28), metalMaterial, 8);

  function merge(parts) {
    const flat = parts.map(geo => { const out = geo.index ? geo.toNonIndexed() : geo; if (out !== geo) geo.dispose(); return out; });
    const result = new THREE.BufferGeometry();
    for (const key of ['position', 'normal']) {
      const attribute = new Float32Array(flat.reduce((n, geo) => n + geo.attributes[key].array.length, 0));
      let offset = 0;
      for (const geo of flat) { attribute.set(geo.attributes[key].array, offset); offset += geo.attributes[key].array.length; }
      result.setAttribute(key, new THREE.BufferAttribute(attribute, 3));
    }
    flat.forEach(geo => geo.dispose()); return result;
  }
  function cylinderBetween(a, b, radius) {
    const first = vector(...a), last = vector(...b), direction = last.clone().sub(first);
    const geo = new THREE.CylinderGeometry(radius, radius, direction.length(), 8);
    geo.applyQuaternion(new THREE.Quaternion().setFromUnitVectors(UP, direction.normalize()));
    geo.translate(...first.add(last).multiplyScalar(.5).toArray()); return geo;
  }
  const jackParts = [
    cylinderBetween([-.5, .09, -.20], [.22, .09, -.20], .032), cylinderBetween([-.5, .09, .20], [.22, .09, .20], .032),
    cylinderBetween([.15, .09, -.20], [.15, .09, .20], .035), cylinderBetween([-.48, .09, 0], [.70, .69, 0], .033),
    cylinderBetween([-.48, .09, -.16], [-.48, .09, .16], .032), cylinderBetween([.70, .69, -.16], [.70, .69, .16], .026),
  ];
  for (const z of [-.22, .22]) {
    const wheel = new THREE.CylinderGeometry(.07, .07, .055, 12); wheel.rotateX(Math.PI / 2); wheel.translate(.17, .07, z); jackParts.push(wheel);
  }
  const jackGeometry = merge(jackParts);
  const jackFront = new THREE.Mesh(jackGeometry, metalMaterial), jackRear = new THREE.Mesh(jackGeometry, metalMaterial);
  jackFront.name = 'Front jack'; jackRear.name = 'Rear jack';
  jackFront.castShadow = jackRear.castShadow = true; jackRear.rotation.y = Math.PI;
  group.add(jackFront, jackRear);
  const gantryGeometry = merge([
    cylinderBetween([.50, 0, side * 2.5], [.50, 2.05, side * 2.5], .035),
    cylinderBetween([.50, 2.05, side * 2.5], [.50, 2.05, side * 1.35], .035),
  ]);
  const gantry = new THREE.Mesh(gantryGeometry, darkMaterial); gantry.name = 'Release light gantry'; group.add(gantry);
  const redMaterial = new THREE.MeshStandardMaterial({ color: '#ed2a18', emissive: '#ed2a18', emissiveIntensity: 2 });
  const greenMaterial = new THREE.MeshStandardMaterial({ color: '#15ed74', emissive: '#15ed74', emissiveIntensity: 0 });
  const red = new THREE.Mesh(new THREE.SphereGeometry(.07, 12, 8), redMaterial);
  const green = new THREE.Mesh(red.geometry, greenMaterial);
  red.position.set(.50, 1.98, side * 1.35); green.position.set(.50, 1.81, side * 1.35); group.add(red, green);

  const members = [];
  const corners = [[1.8, -.825], [1.8, .825], [-1.8, -.78], [-1.8, .78]];
  for (let corner = 0; corner < 4; corner++) {
    const [x, originalZ] = corners[corner], z = originalZ * side, sign = Math.sign(z);
    for (let role = 0; role < 3; role++) members.push({ role: ['gun', 'off', 'on'][role], corner: side === 1 ? corner : corner ^ 1,
      x: x + (role === 1 ? -.48 : role === 2 ? .48 : 0), z: z + sign * (role ? 1.02 : .75), targetX: x, targetZ: z, sign });
  }
  members.push({ role: 'front-jack', x: 3.58, z: side * .13, targetX: 2.7, targetZ: 0, sign: side });
  members.push({ role: 'rear-jack', x: -3.43, z: side * .13, targetX: -2.3, targetZ: 0, sign: side });
  for (const [x, z] of [[.70, -1.35], [.70, 1.35], [-.85, -1.35], [-.85, 1.35]]) members.push({ role: 'steady', x, z: z * side, targetX: x, targetZ: Math.sign(z) * side * .55, sign: Math.sign(z) * side });
  group.userData.members = members.map(({ role, corner }) => ({ role, corner }));
  group.userData.carLift = 0; group.userData.wheelsRemoved = [false, false, false, false];
  const smooth = (a, b, t) => { const u = THREE.MathUtils.clamp((t - a) / (b - a), 0, 1); return u * u * (3 - 2 * u); };

  function put(mesh, index, p, s, rotation = null) {
    pos.set(...p); scale.set(...s); q.identity(); if (rotation) q.setFromEuler(new THREE.Euler(...rotation));
    matrix.compose(pos, q, scale); mesh.setMatrixAt(index, matrix);
  }
  function bone(index, a, b, radius) {
    delta.set(b[0] - a[0], b[1] - a[1], b[2] - a[2]); const length = delta.length();
    pos.set(...a); scale.set(radius, length, radius); q.setFromUnitVectors(UP, delta.normalize());
    matrix.compose(pos, q, scale); limbs.setMatrixAt(index, matrix);
  }
  let lastPhase = '', lastU = -1;
  function update(phase, u) {
    if (!['waiting', 'stopped', 'release'].includes(phase)) throw new RangeError(`Unknown pit phase: ${phase}`);
    u = Number.isFinite(u) ? THREE.MathUtils.clamp(u, 0, 1) : 0;
    if (phase === lastPhase && u === lastU) return;
    lastPhase = phase; lastU = u;
    const stopped = phase === 'stopped', release = phase === 'release';
    const work = stopped ? smooth(0, .14, u) * (1 - smooth(.77, .96, u)) : 0;
    const retreat = release ? smooth(0, .75, u) : phase === 'waiting' ? 1 - smooth(0, 1, u) : 0;
    const lift = stopped ? smooth(.03, .13, u) * (1 - smooth(.83, .97, u)) : 0;
    group.userData.carLift = lift * .04;
    group.userData.wheelsRemoved.fill(stopped && u >= .30 && u < .70);
    redMaterial.emissiveIntensity = release ? 0 : 2;
    greenMaterial.emissiveIntensity = release ? 2.5 : 0;
    red.material.color.set(release ? '#36120e' : '#ed2a18'); green.material.color.set(release ? '#15ed74' : '#0b3420');
    jackFront.position.set(2.97 + retreat * .45, .02 + lift * .04, 0);
    jackRear.position.set(-2.72 - retreat * .45, .02 + lift * .04, 0);
    let limbIndex = 0, jointIndex = 0;
    for (let i = 0; i < members.length; i++) {
      const member = members[i], jack = member.role.includes('jack'), steady = member.role === 'steady';
      const dx = member.targetX - member.x, dz = member.targetZ - member.z, length = Math.hypot(dx, dz);
      const fx = dx / length, fz = dz / length, rx = -fz, rz = fx;
      const x = member.x - fx * retreat * .42, z = member.z - fz * retreat * .42;
      const yaw = Math.atan2(-fz, fx);
      const baseY = jack ? .86 : steady ? .77 : .55 + retreat * .20;
      const shoulderY = baseY + (jack ? .38 : .37);
      const lean = jack ? .24 + work * .10 : .12 + work * .10;
      const w = (forward, y, lateral = 0) => [x + fx * forward + rx * lateral, y, z + fz * forward + rz * lateral];
      put(hips, i, w(0, baseY), [1, 1, 1], [0, yaw, 0]);
      put(torsos, i, w(.07, baseY + .05), [1, 1, 1], [0, yaw, -.22]);
      put(shoulderStripes, i, w(lean, shoulderY + .02), [1, 1, 1], [0, yaw, -.22]);
      put(helmets, i, w(lean + .035, shoulderY + .08), [1, 1, 1], [0, yaw, -.12]);
      put(visors, i, w(lean + .065, shoulderY + .21), [.145, .15, .15], [0, yaw, -.12]);
      for (let arm = 0; arm < 2; arm++) {
        const sign = arm ? 1 : -1;
        const shoulder = w(lean, shoulderY, sign * .18);
        const reach = member.role === 'gun' ? .44 + work * .17 : jack ? .50 : steady ? .44 + work * .10 : .33 + work * .24;
        const handY = jack ? .69 - work * .18 : steady ? .61 : .38 + lift * .04;
        const hand = w(reach, handY, sign * (jack ? .13 : .08));
        const elbow = w(.16 + work * .14, shoulderY - .20, sign * .24);
        bone(limbIndex++, shoulder, elbow, .060); bone(limbIndex++, elbow, hand, .047);
        put(joints, jointIndex++, elbow, [.062, .055, .062]);
        put(gloves, i * 2 + arm, hand, [.052, .040, .075], [0, yaw, 0]);
      }
      for (let leg = 0; leg < 2; leg++) {
        const sign = leg ? 1 : -1;
        const hip = w(-.015, baseY, sign * .095);
        const knee = w(jack ? .05 : leg ? .19 : -.17, jack ? .46 : leg ? .16 : .29, sign * .14);
        const ankle = w(jack ? -.10 : leg ? -.12 : -.32, .12, sign * .18);
        bone(limbIndex++, hip, knee, .085); bone(limbIndex++, knee, ankle, .060);
        put(joints, jointIndex++, knee, [.078, .070, .075]);
        put(boots, i * 2 + leg, w(jack ? -.08 : leg ? -.08 : -.28, .015, sign * .18), [1, 1, 1], [0, yaw + Math.PI / 2, 0]);
      }
    }
    for (let corner = 0; corner < 4; corner++) {
      const [x, rawZ] = corners[corner], z = rawZ * side, sign = Math.sign(z);
      const reach = stopped ? smooth(.05, .18, u) * (1 - smooth(.73, .90, u)) : 0;
      put(guns, corner, [x, .365 + lift * .04, z + sign * (.34 + (1 - reach) * .38)], [1, 1, 1], [Math.PI / 2, 0, 0]);
      const off = stopped ? smooth(.30, .50, u) : release ? 1 : 0;
      const on = stopped ? smooth(.50, .70, u) : release ? 1 : 0;
      const oldPos = [x - off * .45, .363 + lift * .04 + Math.sin(off * Math.PI) * .12, z + sign * off * .83];
      const newPos = [x + (1 - on) * .46, .363 + lift * .04 + Math.sin(on * Math.PI) * .12, z + sign * (1 - on) * .83];
      const oldVisible = stopped && u >= .30 || release;
      const newVisible = !release && (!stopped || u < .70);
      put(spareTyres, corner * 2, oldPos, oldVisible ? [1, 1, 1] : [0, 0, 0]);
      put(spareRims, corner * 2, [oldPos[0], oldPos[1], oldPos[2] + sign * .165], oldVisible ? [1, 1, 1] : [0, 0, 0]);
      put(spareTyres, corner * 2 + 1, newPos, newVisible ? [1, 1, 1] : [0, 0, 0]);
      put(spareRims, corner * 2 + 1, [newPos[0], newPos[1], newPos[2] + sign * .165], newVisible ? [1, 1, 1] : [0, 0, 0]);
    }
    for (const mesh of allInstances) mesh.instanceMatrix.needsUpdate = true;
  }
  update('waiting', 0);
  group.userData.update = update;
  let triangles = 0, drawCalls = 0;
  group.traverse(object => { if (object.isMesh) { drawCalls++; triangles += (object.geometry.index?.count ?? object.geometry.attributes.position.count) / 3 * (object.isInstancedMesh ? object.count : 1); } });
  group.userData.stats = { figures: members.length, drawCalls, triangles };
  group.userData.dispose = () => {
    const geometries = new Set(), materials = new Set();
    group.traverse(object => { if (object.isMesh) { geometries.add(object.geometry); materials.add(object.material); } });
    geometries.forEach(geometry => geometry.dispose()); materials.forEach(material => material.dispose());
  };
  return { group, update };
}
