import type { Corridor } from "@/lib/types";

/**
 * Corridors drawn as a static SVG on a plain outline-free map of India: no JavaScript, paints at once.
 * Used where the interactive deck.gl map would otherwise block the main thread on load.
 */
const LON: [number, number] = [67.5, 98.5];
const LAT: [number, number] = [6, 36.5];
const WIDTH = 760;
const HEIGHT = 420;
// An equirectangular projection corrected by the cosine of the mid latitude, so distances look right.
const K = Math.cos((21 * Math.PI) / 180);

function project(lon: number, lat: number): [number, number] {
  const spanX = (LON[1] - LON[0]) * K;
  const spanY = LAT[1] - LAT[0];
  const scale = Math.min(WIDTH / spanX, HEIGHT / spanY);
  const offsetX = (WIDTH - spanX * scale) / 2;
  const offsetY = (HEIGHT - spanY * scale) / 2;
  return [offsetX + (lon - LON[0]) * K * scale, HEIGHT - offsetY - (lat - LAT[0]) * scale];
}

export function CorridorSketch({ corridors, label }: { corridors: Corridor[]; label: string }) {
  const drawn = corridors.filter(
    (c) => c.src.lat != null && c.src.lon != null && c.dst.lat != null && c.dst.lon != null
  );
  return (
    <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} role="img" aria-label={label} className="block h-auto w-full">
      {drawn.map((c) => {
        const [x1, y1] = project(c.src.lon as number, c.src.lat as number);
        const [x2, y2] = project(c.dst.lon as number, c.dst.lat as number);
        const same = Math.hypot(x2 - x1, y2 - y1) < 3;
        const color = c.direction === "better" ? "#3b82f6" : c.severity.color;
        return (
          <g key={c.id}>
            {same ? (
              <circle cx={x1} cy={y1} r={6 + c.severity.weight} fill="none" stroke={color} strokeWidth={2} />
            ) : (
              <line x1={x1} y1={y1} x2={x2} y2={y2} stroke={color}
                strokeWidth={Math.max(1.2, c.severity.weight)} strokeLinecap="round" opacity={0.8} />
            )}
            <circle cx={x1} cy={y1} r={2.5} fill={color} />
            <circle cx={x2} cy={y2} r={2.5} fill={color} />
          </g>
        );
      })}
    </svg>
  );
}
