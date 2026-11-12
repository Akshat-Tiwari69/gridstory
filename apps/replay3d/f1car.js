/** Generic 2022–2025 open-wheel car. Metres; +X forward, +Y up, -Z left.
 * No external assets, logos, textures, or dependencies. Geometry is baked once.
 */
export function buildF1Car(THREE, opts = {}) {
  const car = new THREE.Group();
  car.name = 'Ground-effect single-seater';
  const primary = new THREE.Color(opts.primary ?? '#171c20');
  const secondary = new THREE.Color(opts.secondary ?? '#abb5bc');
  const accent = new THREE.Color(opts.accent ?? '#26dfc0');
  const black = new THREE.Color('#11151a');
  const silver = new THREE.Color('#879099');
  const white = new THREE.Color('#eef0eb');
  const buckets = { paint: [], carbon: [], tyre: [], trim: [], disc: [] };
  const bandVertices = [];
  const v = (x, y, z) => new THREE.Vector3(x, y, z);
  const transform = new THREE.Matrix4();

  function add(bucket, geometry, color = white, position = [0, 0, 0], rotation = [0, 0, 0], scale = [1, 1, 1], band = false) {
    transform.compose(v(...position), new THREE.Quaternion().setFromEuler(new THREE.Euler(...rotation)), v(...scale));
    geometry.applyMatrix4(transform);
    if (!geometry.attributes.normal) geometry.computeVertexNormals();
    const flat = geometry.index ? geometry.toNonIndexed() : geometry;
    if (flat !== geometry) geometry.dispose();
    const colors = new Float32Array(flat.attributes.position.count * 3);
    for (let i = 0; i < colors.length; i += 3) {
      colors[i] = color.r; colors[i + 1] = color.g; colors[i + 2] = color.b;
    }
    flat.setAttribute('color', new THREE.BufferAttribute(colors, 3));
    if (band) flat.userData.compoundBand = true;
    buckets[bucket].push(flat);
  }

  // Rings have identical topology; caps use their own vertices to retain crisp edges.
  function loft(rings, caps = true) {
    const positions = rings.flat(2), indices = [], n = rings[0].length;
    for (let j = 0; j < rings.length - 1; j++) for (let i = 0; i < n; i++) {
      const a = j * n + i, b = j * n + (i + 1) % n;
      indices.push(a, b, a + n, b, b + n, a + n);
    }
    if (caps) for (const [j, reverse] of [[0, true], [rings.length - 1, false]]) {
      const ring = rings[j], centre = ring.reduce((p, q) => p.map((x, k) => x + q[k] / n), [0, 0, 0]);
      const start = positions.length / 3;
      positions.push(...centre, ...ring.flat());
      for (let i = 0; i < n; i++) {
        const a = start + 1 + i, b = start + 1 + (i + 1) % n;
        indices.push(start, ...(reverse ? [b, a] : [a, b]));
      }
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
    geo.setIndex(indices); geo.computeVertexNormals();
    return geo;
  }

  // Section [x, centre Y, half-height, half-width, centre Z].
  function shell(sections, samples = 20) {
    return loft(sections.map(([x, y, h, w, z = 0]) => Array.from({ length: samples }, (_, i) => {
      const a = i / samples * Math.PI * 2;
      return [x, y + h * Math.cos(a), z + w * Math.sin(a)];
    })));
  }

  function rod(bucket, a, b, radius, color = black, radiusEnd = radius) {
    const from = v(...a), to = v(...b), delta = to.clone().sub(from);
    const geo = new THREE.CylinderGeometry(radiusEnd, radius, delta.length(), 7, 1);
    geo.applyQuaternion(new THREE.Quaternion().setFromUnitVectors(v(0, 1, 0), delta.normalize()));
    add(bucket, geo, color, from.add(to).multiplyScalar(.5).toArray());
  }

  function tube(points, radius, color = black, bucket = 'carbon', closed = false) {
    const curve = new THREE.CatmullRomCurve3(points.map(p => v(...p)), closed, 'centripetal');
    add(bucket, new THREE.TubeGeometry(curve, points.length * 5, radius, 7, closed), color);
  }

  function plate(bucket, points, thickness, color, axis = 'y') {
    const rings = [-thickness / 2, thickness / 2].map(offset => points.map(p => {
      const q = [...p]; q[axis === 'y' ? 1 : 2] += offset; return q;
    }));
    add(bucket, loft(rings), color);
  }

  // A closed cambered aerofoil, swept and twisted along its span.
  function wing(sections, bucket = 'carbon', color = black) {
    const rings = sections.map(([z, leading, chord, y, camber = .035]) => {
      const ring = [], count = 12;
      for (let side = 0; side < 2; side++) for (let j = 0; j <= count; j++) {
        const u = side ? 1 - j / count : j / count;
        const t = .12 * chord * (0.2969 * Math.sqrt(u) - .126 * u - .3516 * u ** 2 + .2843 * u ** 3 - .1036 * u ** 4) / .2;
        ring.push([leading - chord * u, y + camber * u + (side ? -t : t), z]);
      }
      return ring;
    });
    add(bucket, loft(rings), color);
  }

  // Floor: broad venturi deck, tapered coke-bottle tail and raised outer fences.
  plate('carbon', [
    [-2.37, .115, -.35], [-1.95, .10, -.66], [-1.35, .10, -.79], [.55, .10, -.80],
    [1.16, .10, -.65], [1.28, .10, -.36], [1.04, .10, .36], [.55, .10, .80],
    [-1.35, .10, .79], [-1.95, .10, .66], [-2.37, .115, .35],
  ], .025, black);
  for (const side of [-1, 1]) {
    tube([[-1.76, .14, side * .75], [-.70, .135, side * .81], [.50, .15, side * .81], [1.08, .18, side * .65]], .013);
    tube([[-1.63, .15, side * .758], [-.6, .15, side * .795], [.4, .17, side * .795]], .006, accent, 'paint');
    // Inlet fences and small floor-edge strakes.
    for (let i = 0; i < 3; i++) plate('carbon', [[.66, .13, side * (.37 + i * .115)], [1.16, .13, side * (.33 + i * .10)],
      [1.04, .28, side * (.36 + i * .105)], [.70, .23, side * (.39 + i * .115)]], .008, black, 'z');
  }

  // Nose, front bulkhead and cockpit shoulders are individually profiled, never boxes.
  add('paint', shell([[.36, .41, .20, .28], [.75, .405, .18, .25], [1.12, .36, .135, .20],
    [1.60, .30, .095, .145], [2.16, .245, .068, .105], [2.48, .215, .05, .085], [2.62, .207, .027, .05]]), primary);
  for (const side of [-1, 1]) {
    add('paint', shell([[-.62, .43, .14, .13, side * .24], [-.30, .48, .13, .105, side * .285],
      [.12, .49, .11, .09, side * .28], [.43, .46, .12, .10, side * .23]]), secondary);
    tube([[2.47, .262, side * .055], [1.66, .396, side * .095], [1.02, .49, side * .13], [.67, .57, side * .17]], .009, accent, 'paint');
  }
  add('carbon', shell([[-.62, .36, .12, .20], [.05, .36, .13, .235], [.40, .37, .12, .18]]), black);
  // Deep cockpit well, seat back and padded rim.
  add('carbon', new THREE.SphereGeometry(1, 18, 10), black, [-.15, .49, 0], [0, 0, 0], [.42, .10, .235]);
  add('carbon', shell([[-.50, .60, .11, .20], [-.38, .58, .12, .19]]), black);

  // Sculpted sidepods: high intake lip, deep undercut, sloping downwash shoulder.
  const podSections = [
    [.56, .66, .28, .57, .36], [.38, .73, .29, .62, .24], [.02, .81, .27, .60, .20],
    [-.48, .78, .25, .55, .18], [-.98, .67, .23, .45, .17], [-1.48, .46, .19, .32, .16], [-1.74, .30, .16, .235, .15],
  ];
  for (const side of [-1, 1]) {
    const rings = podSections.map(([x, outer, inner, top, bottom]) => {
      const profile = [[inner, top - .04], [outer * .80, top], [outer, top - .055], [outer, top - .15],
        [outer * .86, bottom + .06], [inner + .045, bottom], [inner, bottom + .07], [inner, top - .13]];
      const curve = new THREE.CatmullRomCurve3(profile.map(([z, y]) => v(x, y, side * z)), true, 'centripetal');
      // Reverse mirrored winding so both sides face outwards.
      const ring = Array.from({ length: 24 }, (_, i) => curve.getPoint(i / 24).toArray());
      return side === 1 ? ring.reverse() : ring;
    });
    add('paint', loft(rings), primary);
    // Dark intake aperture, inset beneath a bright upper lip.
    add('carbon', shell([[.575, .50, .047, .150, side * .49], [.548, .50, .047, .150, side * .49]], 16), black);
    tube([[.56, .56, side * .35], [.40, .607, side * .52], [.03, .592, side * .68],
      [-.50, .534, side * .67], [-1.06, .43, side * .54], [-1.5, .30, side * .37]], .014, accent, 'paint');
    add('paint', shell([[.15, .36, .035, .035, side * .75], [-.45, .315, .04, .035, side * .72],
      [-1.04, .25, .025, .025, side * .58]]), secondary);
    // Downwash shoulder panel and six restrained cooling louvres.
    plate('paint', [[.10, .604, side * .37], [-.30, .575, side * .37], [-1.1, .405, side * .37],
      [-.89, .455, side * .49], [-.32, .56, side * .65]], .005, secondary);
    for (let i = 0; i < 6; i++) {
      const x = -.40 - i * .07, y = .55 - i * .014;
      rod('carbon', [x, y + .008, side * .38], [x - .045, y - .009, side * .53], .006);
    }
  }

  // Tapered engine cover, shark fin, roll hoop and open oval airbox.
  add('paint', shell([[-2.10, .26, .10, .14], [-1.72, .35, .15, .20], [-1.25, .45, .20, .23],
    [-.85, .56, .245, .245], [-.53, .68, .22, .19], [-.35, .74, .15, .145]]), primary);
  plate('paint', [[-1.95, .36, 0], [-1.45, .62, 0], [-.65, .94, 0], [-.48, .94, 0],
    [-.56, .71, 0], [-1.23, .49, 0]], .012, secondary, 'z');
  add('paint', shell([[-.61, .87, .095, .12], [-.40, .885, .082, .11], [-.325, .88, .070, .102]], 20), primary);
  add('carbon', shell([[-.320, .88, .051, .079], [-.311, .88, .051, .079]], 20), black);
  tube([[-.45, .93, -.095], [-.34, .95, 0], [-.45, .93, .095]], .012, accent, 'paint');

  // Halo: continuous horseshoe, rear mounts and central forward pillar.
  tube([[-.46, .72, -.27], [-.24, .82, -.295], [.19, .815, -.25], [.43, .785, -.12],
    [.46, .775, 0], [.43, .785, .12], [.19, .815, .25], [-.24, .82, .295], [-.46, .72, .27]], .022);
  rod('carbon', [.46, .775, 0], [.55, .51, 0], .019);
  for (const side of [-1, 1]) rod('carbon', [-.46, .72, side * .27], [-.55, .54, side * .25], .025);
  // Generic helmet and dark visor; deliberately free of helmet livery marks.
  add('paint', new THREE.SphereGeometry(1, 22, 14), accent, [-.12, .718, 0], [0, 0, 0], [.125, .139, .117]);
  add('carbon', shell([[-.018, .74, .036, .100], [.008, .739, .028, .087]], 18), black);
  rod('carbon', [.21, .57, -.12], [.21, .57, .12], .018); // steering wheel

  // Four-element front wing: spoon centre, raised tips, independent flap slots.
  for (let element = 0; element < 4; element++) {
    const lead = 2.79 - element * .15, y = .115 + element * .037;
    wing([[-.96, lead - .10, .19, y + .075, .045], [-.76, lead - .035, .22, y + .025, .04],
      [-.34, lead, .225, y, .035], [0, lead + .025, .22, y + .005, .035],
      [.34, lead, .225, y, .035], [.76, lead - .035, .22, y + .025, .04], [.96, lead - .10, .19, y + .075, .045]],
    element === 3 ? 'paint' : 'carbon', element === 3 ? secondary : black);
  }
  for (const side of [-1, 1]) {
    plate('paint', [[2.13, .15, side * .975], [2.62, .13, side * .975], [2.72, .24, side * .975],
      [2.55, .39, side * .975], [2.20, .33, side * .975]], .018, primary, 'z');
    tube([[2.17, .32, side * .985], [2.38, .365, side * .985], [2.54, .38, side * .985]], .007, accent, 'paint');
    rod('carbon', [2.30, .20, side * .065], [2.24, .13, side * .18], .014);
    // Rear wing endplates have a curved, forward-raked outline.
    plate('paint', [[-2.59, .48, side * .565], [-2.61, .87, side * .565], [-2.47, .98, side * .565],
      [-2.02, .96, side * .565], [-2.04, .83, side * .565], [-2.25, .68, side * .565],
      [-2.29, .47, side * .565]], .016, primary, 'z');
    tube([[-2.57, .88, side * .58], [-2.46, .975, side * .58], [-2.08, .965, side * .58]], .008, accent, 'paint');
    rod('carbon', [-1.96, .26, side * .15], [-2.26, .88, side * .15], .018);
  }
  // Mainplane, distinct DRS flap and twin beam wings.
  wing([[-.55, -2.02, .56, .81, .08], [-.36, -2.03, .55, .79, .09], [0, -2.04, .53, .78, .10],
    [.36, -2.03, .55, .79, .09], [.55, -2.02, .56, .81, .08]]);
  wing([[-.53, -2.17, .34, .932, .025], [0, -2.18, .34, .925, .025], [.53, -2.17, .34, .932, .025]], 'paint', secondary);
  wing([[-.45, -1.98, .34, .40, .05], [0, -2.01, .36, .35, .06], [.45, -1.98, .34, .40, .05]]);
  wing([[-.44, -2.05, .25, .48, .03], [0, -2.07, .27, .44, .04], [.44, -2.05, .25, .48, .03]]);
  rod('carbon', [-2.30, .87, 0], [-2.30, .95, 0], .013); // generic flap actuator

  // Diffuser ramp and longitudinal vanes.
  plate('carbon', [[-1.72, .09, -.48], [-2.46, .25, -.51], [-2.46, .25, .51], [-1.72, .09, .48]], .015, black);
  for (const z of [-.45, -.225, 0, .225, .45]) plate('carbon', [[-1.75, .095, z], [-2.46, .25, z],
    [-2.46, .34, z], [-1.75, .15, z]], .010, black, 'z');
  add('carbon', new THREE.CylinderGeometry(.037, .041, .14, 12), silver, [-2.14, .42, 0], [0, 0, Math.PI / 2]);

  // Double wishbones, pull/push rods and steering links.
  for (const side of [-1, 1]) for (const front of [true, false]) {
    const x = front ? 1.8 : -1.8, hubZ = side * (front ? .79 : .77);
    const anchor = front ? 1.0 : -1.08;
    for (const y of [.22, .40]) {
      rod('carbon', [anchor, y + .015, side * .22], [x, y, hubZ], .013);
      rod('carbon', [front ? 1.46 : -1.45, y, side * .20], [x + (front ? .08 : -.08), y, hubZ], .012);
    }
    rod('carbon', [anchor, .51, side * .22], [x, .25, hubZ], .014);
    rod('carbon', [anchor + .12, .33, side * .20], [x + .08, .32, hubZ], .009);
  }
  for (const side of [-1, 1]) {
    rod('carbon', [.29, .53, side * .28], [.37, .66, side * .63], .010);
    add('paint', shell([[.27, .67, .036, .045, side * .65], [.40, .67, .038, .065, side * .65],
      [.48, .67, .025, .05, side * .65]], 14), secondary);
    add('carbon', shell([[.269, .67, .025, .033, side * .65], [.263, .67, .025, .033, side * .65]], 12), silver);
  }

  // Small vector numerals, merged with paint: readable without a texture or draw call.
  const digits = ['abcdef', 'bc', 'abdeg', 'abcdg', 'bcfg', 'acdfg', 'acdefg', 'abc', 'abcdefg', 'abcdfg'];
  const segments = { a: [0, 1, 1, 1], b: [1, 1, 1, .5], c: [1, .5, 1, 0], d: [0, 0, 1, 0],
    e: [0, .5, 0, 0], f: [0, 1, 0, .5], g: [0, .5, 1, .5] };
  const number = String(opts.number ?? '44').replace(/\D/g, '').slice(0, 3) || '44';
  function raceNumber(position, quaternion, height) {
    const width = height * .53, gap = width * .28, offset = (number.length * (width + gap) - gap) / 2;
    for (let d = 0; d < number.length; d++) for (const segment of digits[Number(number[d])]) {
      const [ax, ay, bx, by] = segments[segment];
      const a = v(d * (width + gap) + ax * width - offset, ay * height, 0);
      const b = v(d * (width + gap) + bx * width - offset, by * height, 0);
      const direction = b.clone().sub(a), perpendicular = v(-direction.y, direction.x, 0).normalize().multiplyScalar(height * .048);
      const corners = [a.clone().add(perpendicular), b.clone().add(perpendicular), b.clone().sub(perpendicular), a.clone().sub(perpendicular)]
        .map(p => p.applyQuaternion(quaternion).add(v(...position)).toArray());
      plate('paint', corners, .001, white, 'z');
    }
  }
  raceNumber([1.40, .422, 0], new THREE.Quaternion().setFromEuler(new THREE.Euler(-Math.PI / 2, 0, Math.PI / 2)), .24);
  for (const side of [-1, 1]) raceNumber([-.85, .555, side * .252],
    new THREE.Quaternion().setFromEuler(new THREE.Euler(0, side === 1 ? 0 : Math.PI, 0)), .18);

  // Wheel geometry uses a unit axial width; instance Z scale supplies front/rear widths.
  const tyreProfile = [[.235, -.49], [.275, -.505], [.323, -.485], [.350, -.425], [.361, -.33],
    [.363, -.20], [.363, .20], [.361, .33], [.350, .425], [.323, .485], [.275, .505], [.235, .49]];
  add('tyre', new THREE.LatheGeometry(tyreProfile.map(([r, z]) => new THREE.Vector2(r, z)), 56), white, [0, 0, 0], [Math.PI / 2, 0, 0]);
  for (const side of [-1, 1]) {
    add('trim', new THREE.TorusGeometry(.230, .010, 6, 48), silver, [0, 0, side * .483]);
    add('trim', new THREE.TorusGeometry(.205, .009, 5, 48), black, [0, 0, side * .484]);
    // Vented aero cover leaves the brake disc visible through the radial openings.
    for (let i = 0; i < 10; i++) add('trim', new THREE.RingGeometry(.070, .201, 4, 1, i / 10 * Math.PI * 2, Math.PI * 2 / 10 * .68),
      black, [0, 0, side * .445], [0, side === -1 ? Math.PI : 0, 0]);
    add('trim', new THREE.TorusGeometry(.315, .005, 5, 56), white, [0, 0, side * .487], [0, 0, 0], [1, 1, 1], true);
    add('trim', new THREE.TorusGeometry(.333, .0018, 4, 48), new THREE.Color('#24282b'), [0, 0, side * .46]);
    for (let i = 0; i < 10; i++) {
      const a = i / 10 * Math.PI * 2;
      rod('trim', [.067 * Math.cos(a), .067 * Math.sin(a), side * .486],
        [.198 * Math.cos(a + .13), .198 * Math.sin(a + .13), side * .486], .009, silver);
    }
    add('trim', new THREE.CylinderGeometry(.052, .052, .028, 10), silver, [0, 0, side * .49], [Math.PI / 2, 0, 0]);
    add('trim', new THREE.CylinderGeometry(.024, .024, .04, 6), accent, [0, 0, side * .505], [Math.PI / 2, 0, 0]);
    add('disc', new THREE.RingGeometry(.065, .184, 40), white, [0, 0, side * .395], [0, side === -1 ? Math.PI : 0, 0]);
  }

  function merge(bucket) {
    const parts = buckets[bucket], count = parts.reduce((n, geo) => n + geo.attributes.position.count, 0);
    const geo = new THREE.BufferGeometry();
    for (const attribute of ['position', 'normal', 'color']) {
      const data = new Float32Array(count * 3);
      let offset = 0;
      for (const part of parts) {
        data.set(part.attributes[attribute].array, offset);
        if (attribute === 'color' && part.userData.compoundBand) {
          for (let i = 0; i < part.attributes.color.count; i++) bandVertices.push(offset / 3 + i);
        }
        offset += part.attributes[attribute].array.length;
      }
      geo.setAttribute(attribute, new THREE.BufferAttribute(data, 3));
    }
    parts.forEach(part => part.dispose());
    geo.computeBoundingSphere(); geo.computeBoundingBox();
    return geo;
  }

  const paintMaterial = new THREE.MeshPhysicalMaterial({ vertexColors: true, metalness: .30, roughness: .34, clearcoat: .85, clearcoatRoughness: .22, envMapIntensity: 1.05, side: THREE.DoubleSide });
  const carbonMaterial = new THREE.MeshStandardMaterial({ vertexColors: true, metalness: .18, roughness: .62, envMapIntensity: .85, side: THREE.DoubleSide });
  const tyreMaterial = new THREE.MeshStandardMaterial({ color: '#101215', roughness: .93, metalness: .02, side: THREE.DoubleSide });
  const trimMaterial = new THREE.MeshStandardMaterial({ vertexColors: true, metalness: .72, roughness: .36, side: THREE.DoubleSide });
  const discMaterial = new THREE.MeshStandardMaterial({ color: '#423e39', roughness: .65, metalness: .6, emissive: '#ff3708', emissiveIntensity: 0, side: THREE.DoubleSide });
  for (const [bucket, material] of [['paint', paintMaterial], ['carbon', carbonMaterial]]) {
    const mesh = new THREE.Mesh(merge(bucket), material);
    mesh.name = bucket === 'paint' ? 'Clearcoat bodywork and markings' : 'Carbon aero and suspension';
    mesh.castShadow = mesh.receiveShadow = true; car.add(mesh);
  }
  const tyreMesh = new THREE.InstancedMesh(merge('tyre'), tyreMaterial, 4);
  const trimMesh = new THREE.InstancedMesh(merge('trim'), trimMaterial, 4);
  const discMesh = new THREE.InstancedMesh(merge('disc'), discMaterial, 4);
  tyreMesh.name = 'Four slick tyres'; trimMesh.name = 'Rims and compound bands'; discMesh.name = 'Brake discs';
  for (const mesh of [tyreMesh, trimMesh, discMesh]) {
    mesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
    // Bounds cover the full steering sweep and are calculated once, not every frame.
    mesh.boundingSphere = new THREE.Sphere(v(0, .36, 0), 2.8);
    mesh.castShadow = true; mesh.receiveShadow = true; car.add(mesh);
  }
  const wheelPositions = [[1.8, .363, -.825, .31], [1.8, .363, .825, .31], [-1.8, .363, -.78, .405], [-1.8, .363, .78, .405]];
  const matrix = new THREE.Matrix4(), rotation = new THREE.Quaternion(), roll = new THREE.Quaternion();
  const position = new THREE.Vector3(), scale = new THREE.Vector3();
  const axle = v(0, 0, 1), up = v(0, 1, 0);
  let angle = 0, heat = 0, lastSteer = NaN, lastAngle = NaN;

  function update(dt, state = {}) {
    dt = Number.isFinite(dt) && dt > 0 ? dt : 0;
    const speed = Number.isFinite(state.speedKmh) ? state.speedKmh : 0;
    const steer = THREE.MathUtils.clamp(Number.isFinite(state.steer) ? state.steer : 0, -.6, .6);
    const brake = THREE.MathUtils.clamp(Number.isFinite(state.brake) ? state.brake : 0, 0, 1);
    angle = (angle - speed / 3.6 / .363 * dt) % (Math.PI * 2);
    heat += (brake - heat) * (1 - Math.exp(-dt * (brake > heat ? 12 : 2)));
    discMaterial.emissiveIntensity = heat * 2.4;
    if (angle === lastAngle && steer === lastSteer) return;
    lastAngle = angle; lastSteer = steer;
    roll.setFromAxisAngle(axle, angle);
    for (let i = 0; i < 4; i++) {
      const [x, y, z, width] = wheelPositions[i];
      position.set(x, y, z); scale.set(1, 1, width);
      rotation.setFromAxisAngle(up, i < 2 ? steer : 0).multiply(roll);
      matrix.compose(position, rotation, scale);
      tyreMesh.setMatrixAt(i, matrix); trimMesh.setMatrixAt(i, matrix); discMesh.setMatrixAt(i, matrix);
    }
    for (const mesh of [tyreMesh, trimMesh, discMesh]) mesh.instanceMatrix.needsUpdate = true;
  }

  function setCompound(name) {
    const colors = { hard: '#ecebe4', medium: '#ffcf19', soft: '#ed243d' };
    if (!Object.hasOwn(colors, name)) throw new RangeError(`Unsupported tyre compound: ${name}`);
    if (car.userData.compound === name) return;
    const color = new THREE.Color(colors[name]), attribute = trimMesh.geometry.attributes.color;
    for (const i of bandVertices) attribute.setXYZ(i, color.r, color.g, color.b);
    attribute.needsUpdate = true; car.userData.compound = name;
  }

  car.userData.update = update;
  car.userData.setCompound = setCompound;
  car.userData.wheelbase = 3.6;
  car.userData.wheelRadius = .363;
  car.userData.wheels = { tyres: tyreMesh, rims: trimMesh, discs: discMesh };
  car.userData.dispose = () => car.traverse(object => {
    if (object.isMesh) { object.geometry.dispose(); object.material.dispose(); }
  });
  update(0);
  setCompound(opts.compound ?? 'hard');
  let triangles = 0, drawCalls = 0;
  car.traverse(object => {
    if (!object.isMesh) return;
    drawCalls++;
    triangles += (object.geometry.index?.count ?? object.geometry.attributes.position.count) / 3 * (object.isInstancedMesh ? object.count : 1);
  });
  car.userData.stats = { drawCalls, triangles };
  return car;
}
