/** Rotate a point by `rad` (counter-clockwise), the same transform FastF1 uses for its maps. */
export const rotate = (x: number, y: number, rad: number): [number, number] =>
  [x * Math.cos(rad) - y * Math.sin(rad), x * Math.sin(rad) + y * Math.cos(rad)];
