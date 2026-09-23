"use client";

import { MapboxOverlay } from "@deck.gl/mapbox";
import { ArcLayer, ScatterplotLayer } from "@deck.gl/layers";
import maplibregl from "maplibre-gl";
import { useEffect, useRef, useState } from "react";

import type { Corridor } from "@/lib/types";

import "maplibre-gl/dist/maplibre-gl.css";

/**
 * The India map, as a deck.gl ArcLayer over a MapLibre basemap.
 *
 * The Streamlit version drew 1,130 Folium polylines through an iframe: slow, no
 * hover detail, no smooth zoom. This renders the same corridors as GPU arcs, so
 * the map is finally the thing the demo can lead with.
 *
 * The basemap style needs no API key -- CARTO serves these publicly. That is
 * deliberate: a key would have to live in the build, and a public build holds
 * no secrets (D-062). If the tiles ever fail the arcs still draw, because they
 * are a deck.gl overlay and not part of the style.
 */

const STYLE_DARK =
  "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json";
const STYLE_LIGHT =
  "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json";

function hexToRgb(hex: string): [number, number, number] {
  const h = hex.replace("#", "");
  return [
    parseInt(h.slice(0, 2), 16),
    parseInt(h.slice(2, 4), 16),
    parseInt(h.slice(4, 6), 16),
  ];
}

export interface MapCorridor extends Corridor {}

export function CorridorMap({
  corridors,
  height = 560,
  interactive = true,
  onSelect,
  selectedId,
  autoRotate = false,
}: {
  corridors: MapCorridor[];
  height?: number | string;
  interactive?: boolean;
  onSelect?: (c: MapCorridor | null) => void;
  selectedId?: string | null;
  autoRotate?: boolean;
}) {
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const overlayRef = useRef<MapboxOverlay | null>(null);
  const [hovered, setHovered] = useState<{
    c: MapCorridor;
    x: number;
    y: number;
  } | null>(null);
  const [ready, setReady] = useState(false);

  // Only corridors with both ends located can be drawn at all.
  const drawable = corridors.filter(
    (c) => c.src.lat && c.src.lon && c.dst.lat && c.dst.lon
  );

  // ── the map itself, created once ──────────────────────────────────────────
  useEffect(() => {
    if (!container.current || mapRef.current) return;

    const isLight =
      document.documentElement.getAttribute("data-theme") === "light";

    const map = new maplibregl.Map({
      container: container.current,
      style: isLight ? STYLE_LIGHT : STYLE_DARK,
      center: [80.9, 22.6],
      zoom: 3.85,
      minZoom: 3,
      maxZoom: 12,
      attributionControl: { compact: true },
      interactive,
    });
    mapRef.current = map;

    if (interactive) {
      map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    }

    const overlay = new MapboxOverlay({ interleaved: false, layers: [] });
    overlayRef.current = overlay;
    map.addControl(overlay as unknown as maplibregl.IControl);

    map.on("load", () => setReady(true));

    return () => {
      overlayRef.current = null;
      map.remove();
      mapRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── follow the theme ──────────────────────────────────────────────────────
  useEffect(() => {
    const observer = new MutationObserver(() => {
      const isLight =
        document.documentElement.getAttribute("data-theme") === "light";
      mapRef.current?.setStyle(isLight ? STYLE_LIGHT : STYLE_DARK);
    });
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["data-theme"],
    });
    return () => observer.disconnect();
  }, []);

  // ── layers ────────────────────────────────────────────────────────────────
  useEffect(() => {
    if (!overlayRef.current || !ready) return;

    const arcs = new ArcLayer<MapCorridor>({
      id: "corridors",
      data: drawable,
      getSourcePosition: (d) => [d.src.lon!, d.src.lat!],
      getTargetPosition: (d) => [d.dst.lon!, d.dst.lat!],
      getSourceColor: (d) => {
        const [r, g, b] = hexToRgb(d.severity.color);
        return [r, g, b, selectedId && d.id !== selectedId ? 55 : 210];
      },
      getTargetColor: (d) => {
        const [r, g, b] = hexToRgb(d.severity.color);
        return [r, g, b, selectedId && d.id !== selectedId ? 55 : 210];
      },
      getWidth: (d) => (d.id === selectedId ? d.severity.weight + 2 : d.severity.weight),
      getHeight: 0.35,
      greatCircle: false,
      pickable: interactive,
      autoHighlight: interactive,
      highlightColor: [255, 255, 255, 120],
      widthUnits: "pixels",
      widthMinPixels: 1.2,
      onHover: (info) => {
        if (!interactive) return;
        setHovered(
          info.object
            ? { c: info.object as MapCorridor, x: info.x, y: info.y }
            : null
        );
      },
      onClick: (info) => {
        if (!interactive) return;
        onSelect?.((info.object as MapCorridor) ?? null);
      },
      updateTriggers: {
        getSourceColor: [selectedId],
        getTargetColor: [selectedId],
        getWidth: [selectedId],
      },
      transitions: { getSourceColor: 250, getTargetColor: 250 },
    });

    // Intra-city corridors collapse to a point at national zoom, so an arc with
    // identical endpoints would be invisible. A dot keeps the 70 intra-city
    // bottlenecks on the map instead of silently dropping them.
    const dots = new ScatterplotLayer<MapCorridor>({
      id: "intra-city",
      data: drawable.filter((d) => d.intra_city),
      getPosition: (d) => [d.src.lon!, d.src.lat!],
      getFillColor: (d) => {
        const [r, g, b] = hexToRgb(d.severity.color);
        return [r, g, b, 230];
      },
      getRadius: (d) => 2000 + d.severity.weight * 900,
      radiusUnits: "meters",
      radiusMinPixels: 3,
      radiusMaxPixels: 12,
      stroked: true,
      getLineColor: [255, 255, 255, 90],
      lineWidthMinPixels: 0.8,
      pickable: interactive,
      onHover: (info) => {
        if (!interactive) return;
        setHovered(
          info.object
            ? { c: info.object as MapCorridor, x: info.x, y: info.y }
            : null
        );
      },
      onClick: (info) => {
        if (!interactive) return;
        onSelect?.((info.object as MapCorridor) ?? null);
      },
    });

    overlayRef.current.setProps({ layers: [arcs, dots] });
  }, [drawable, ready, selectedId, interactive, onSelect]);

  // ── slow drift on the landing hero ────────────────────────────────────────
  useEffect(() => {
    if (!autoRotate || !ready || !mapRef.current) return;
    const map = mapRef.current;
    let raf = 0;
    let bearing = 0;
    const tick = () => {
      bearing += 0.02;
      map.setBearing(bearing);
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [autoRotate, ready]);

  return (
    <div
      className="relative overflow-hidden rounded-xl border border-[var(--line)]"
      style={{ height }}
    >
      <div ref={container} className="h-full w-full" />

      {!ready && (
        <div className="absolute inset-0 grid place-items-center bg-[var(--surface-raised)]">
          <p className="font-mono text-xs text-[var(--ink-faint)]">
            loading map…
          </p>
        </div>
      )}

      {hovered && (
        <div
          className="pointer-events-none absolute z-20 max-w-[16rem] rounded-lg border border-[var(--line)] bg-[var(--surface-raised)]/95 px-3 py-2 text-xs shadow-xl backdrop-blur"
          style={{
            left: Math.min(hovered.x + 12, 400),
            top: hovered.y + 12,
          }}
        >
          <p className="font-medium">
            {hovered.c.src.city ?? hovered.c.src.code} →{" "}
            {hovered.c.dst.city ?? hovered.c.dst.code}
          </p>
          <p className="tabular mt-1 font-mono text-[11px] text-[var(--ink-muted)]">
            {hovered.c.excess_ratio.toFixed(2)}× · {hovered.c.n_legs} legs ·{" "}
            {hovered.c.severity.label}
          </p>
        </div>
      )}

      <div className="pointer-events-none absolute bottom-2 left-2 z-10 rounded-lg bg-[var(--surface)]/80 px-2.5 py-1.5 font-mono text-[10px] text-[var(--ink-faint)] backdrop-blur">
        {drawable.length.toLocaleString()} corridors drawn
      </div>
    </div>
  );
}
