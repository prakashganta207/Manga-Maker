import type { DirectedPanel, LayoutTemplate } from "@/lib/api";

export const SHOT_ABBR: Record<string, string> = {
  "extreme close-up": "ECU",
  "close-up": "CU",
  medium: "MS",
  wide: "WS",
  establishing: "EST",
  "over-the-shoulder": "OTS",
};

export const ANGLE_ICON: Record<string, string> = {
  "eye level": "→",
  low: "↗",
  high: "↘",
  "bird's eye": "↓",
};

/** A small drawing of a page layout, with each slot labelled by panel number and shot. */
export default function LayoutThumb({
  template,
  panels = [],
  rtl = true,
  highlight,
  className = "w-28",
}: {
  template: LayoutTemplate;
  panels?: DirectedPanel[];
  rtl?: boolean;
  highlight?: number;
  className?: string;
}) {
  const W = 100;
  const H = 141; // A4 proportions
  const pad = 4;
  const gap = 2.2;
  const innerW = W - pad * 2;
  const innerH = H - pad * 2;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className={className} role="img" aria-label={`${template.name} layout`}>
      <rect x={0} y={0} width={W} height={H} fill="white" stroke="#111" strokeWidth={1} />
      {template.slots.map((slot, i) => {
        const x0 = rtl ? 1 - slot.x - slot.w : slot.x;
        const left = pad + x0 * innerW + (x0 > 0.001 ? gap / 2 : 0);
        const right = pad + (x0 + slot.w) * innerW - (x0 + slot.w < 0.999 ? gap / 2 : 0);
        const top = pad + slot.y * innerH + (slot.y > 0.001 ? gap / 2 : 0);
        const bottom = pad + (slot.y + slot.h) * innerH - (slot.y + slot.h < 0.999 ? gap / 2 : 0);
        const panel = panels[i];
        const active = highlight === i + 1;
        return (
          <g key={i}>
            <rect
              x={left}
              y={top}
              width={right - left}
              height={bottom - top}
              fill={active ? "#111" : slot.size === "large" || slot.size === "splash" ? "#e7e4dc" : "#fbfaf7"}
              stroke="#111"
              strokeWidth={1.4}
            />
            <text
              x={(left + right) / 2}
              y={(top + bottom) / 2 - (panel ? 3 : 0)}
              textAnchor="middle"
              dominantBaseline="middle"
              fontSize={9}
              fontWeight={800}
              fill={active ? "#fbfaf7" : "#111"}
            >
              {i + 1}
            </text>
            {panel && (
              <text
                x={(left + right) / 2}
                y={(top + bottom) / 2 + 8}
                textAnchor="middle"
                dominantBaseline="middle"
                fontSize={6.5}
                fill={active ? "#fbfaf7" : "#444"}
              >
                {SHOT_ABBR[panel.shot] ?? panel.shot} {ANGLE_ICON[panel.angle] ?? ""}
              </text>
            )}
          </g>
        );
      })}
    </svg>
  );
}
