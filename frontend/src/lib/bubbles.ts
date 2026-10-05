// Geometry for editable bubbles. Bubbles are stored as fractions of their panel's inner
// rectangle (so they stick to the artwork in both reading directions); the canvas works in
// page pixels (the backend's 1240x1754 page).

import type { Box, Bubble, BubbleKind } from "./api";

export const KIND_LABEL: Record<BubbleKind, string> = {
  speech: "Speech",
  thought: "Thought",
  shout: "Shout",
  narration: "Narration box",
  sfx: "Sound effect",
};

export function toPx(b: Pick<Bubble, "x" | "y" | "w" | "h">, inner: Box): Box {
  return { x: inner.x + b.x * inner.w, y: inner.y + b.y * inner.h, w: b.w * inner.w, h: b.h * inner.h };
}

/** Page pixels -> panel fractions, keeping the whole bubble inside its panel. */
export function toFrac(box: Box, inner: Box): Pick<Bubble, "x" | "y" | "w" | "h"> {
  const clamp = (v: number, max = 1) => Math.max(0, Math.min(max, v));
  const w = clamp(box.w / inner.w);
  const h = clamp(box.h / inner.h);
  return { x: clamp((box.x - inner.x) / inner.w, 1 - w), y: clamp((box.y - inner.y) / inner.h, 1 - h), w, h };
}

export function pointToPx(p: [number, number], inner: Box): [number, number] {
  return [inner.x + p[0] * inner.w, inner.y + p[1] * inner.h];
}

export function pointToFrac(p: [number, number], inner: Box): [number, number] {
  return [(p[0] - inner.x) / inner.w, (p[1] - inner.y) / inner.h];
}

/** Point on an ellipse (centre cx,cy, radii a,b) in the direction of `angle`. */
export function ellipseEdge(cx: number, cy: number, a: number, b: number, angle: number): [number, number] {
  const dx = Math.cos(angle);
  const dy = Math.sin(angle);
  const t = 1 / Math.sqrt((dx / a) ** 2 + (dy / b) ** 2);
  return [cx + dx * t, cy + dy * t];
}

/** Spiky "shout" outline (same shape as the backend renderer), in local coordinates. */
export function shoutPoints(w: number, h: number, spikes = 18): number[] {
  const pts: number[] = [];
  for (let k = 0; k < spikes * 2; k++) {
    const angle = (Math.PI * k) / spikes;
    const r = k % 2 === 0 ? 1 : 0.84;
    pts.push(w / 2 + Math.cos(angle) * (w / 2) * r, h / 2 + Math.sin(angle) * (h / 2) * r);
  }
  return pts;
}

/** Tail triangle from the ellipse edge toward the tip (local coordinates): [base1, tip, base2]. */
export function tailPoints(w: number, h: number, tip: [number, number]): number[] {
  const cx = w / 2;
  const cy = h / 2;
  const angle = Math.atan2(tip[1] - cy, tip[0] - cx);
  const b1 = ellipseEdge(cx, cy, (w / 2) * 0.9, (h / 2) * 0.9, angle - 0.22);
  const b2 = ellipseEdge(cx, cy, (w / 2) * 0.9, (h / 2) * 0.9, angle + 0.22);
  return [...b1, ...tip, ...b2];
}

/** Vertical text (Japanese "tategaki" style): characters stacked top to bottom, one column per
 * word where possible, columns read right to left. Returns the columns, first column first. */
export function verticalColumns(text: string, perColumn: number): string[] {
  const columns: string[] = [];
  for (const word of text.trim().split(/\s+/)) {
    const chars = [...word];
    for (let i = 0; i < chars.length; i += Math.max(1, perColumn)) columns.push(chars.slice(i, i + perColumn).join("\n"));
  }
  return columns;
}

let counter = 0;
export function newBubbleId(): string {
  counter += 1;
  return `u${Date.now().toString(36)}${counter}`;
}
