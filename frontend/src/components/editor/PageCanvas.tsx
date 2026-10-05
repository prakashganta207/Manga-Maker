"use client";

// The page canvas (react-konva). Layers, bottom to top:
//   1. paper + panel artwork (cover-fitted into each slot, like the backend renderer)
//   2. panel borders (click a panel to select it)
//   3. lettering: bubbles, narration boxes, sound effects (drag, resize, tail handle)
//   4. tools: selection outline, transformer, tail handle, inpainting mask strokes
// Everything is in page pixels; the Stage is scaled to fit the screen.

import Konva from "konva";
import { useEffect, useMemo, useRef, useState } from "react";
import { Circle, Ellipse, Group, Image as KImage, Layer, Line, Rect, Shape, Stage, Text, Transformer } from "react-konva";
import type { Box, Bubble, EditorPage } from "@/lib/api";
import { fileUrl } from "@/lib/api";
import { pointToFrac, pointToPx, shoutPoints, tailPoints, toFrac, toPx, verticalColumns } from "@/lib/bubbles";

export const FONT_FAMILY = "'Comic Neue', 'Comic Sans MS', 'Segoe UI', sans-serif";

export interface MaskStroke {
  points: number[]; // page pixels, x0 y0 x1 y1 ...
  size: number;
  erase: boolean;
}

/** Inpainting mask being painted on one panel (strokes in page pixels). */
export interface MaskState {
  panel: number;
  brush: number;
  erase: boolean;
  strokes: MaskStroke[];
}

export interface MaskTool extends MaskState {
  onStrokes: (strokes: MaskStroke[]) => void;
}

interface Props {
  data: EditorPage;
  bubbles: Bubble[];
  displayWidth: number;
  selectedId: string | null;
  selectedPanel: number | null;
  imageVersion?: string;
  mask?: MaskTool | null;
  onSelectBubble: (id: string | null) => void;
  onSelectPanel: (panel: number | null) => void;
  onChange: (bubble: Bubble) => void;
  onEditText?: (id: string) => void;
}

function useHtmlImage(src: string | null): HTMLImageElement | null {
  const [image, setImage] = useState<HTMLImageElement | null>(null);
  useEffect(() => {
    if (!src) return;
    const img = new window.Image();
    img.crossOrigin = "anonymous";
    img.onload = () => setImage(img);
    img.src = src;
    return () => {
      img.onload = null;
    };
  }, [src]);
  return src ? image : null;
}

/** "Cover" fit: crop the image so it fills the slot without distortion. */
function coverCrop(img: HTMLImageElement, box: Box) {
  const scale = Math.max(box.w / img.width, box.h / img.height);
  const w = box.w / scale;
  const h = box.h / scale;
  return { x: (img.width - w) / 2, y: (img.height - h) / 2, width: w, height: h };
}

function PanelArt({ src, rect }: { src: string | null; rect: Box }) {
  const img = useHtmlImage(src);
  if (!img) return <Rect x={rect.x} y={rect.y} width={rect.w} height={rect.h} fill="#e8e6e0" />;
  return <KImage image={img} x={rect.x} y={rect.y} width={rect.w} height={rect.h} crop={coverCrop(img, rect)} />;
}

/** Largest font size whose wrapped text fits in the box (auto-fit, like the backend). */
function fitFont(text: string, width: number, height: number, start: number, bold: boolean): number {
  const probe = new Konva.Text({ text, width, fontFamily: FONT_FAMILY, fontStyle: bold ? "bold" : "normal", lineHeight: 1.12 });
  for (let size = start; size > 10; size -= 2) {
    probe.fontSize(size);
    if (probe.height() <= height) {
      probe.destroy();
      return size;
    }
  }
  probe.destroy();
  return 10;
}

function BubbleText({ bubble, w, h }: { bubble: Bubble; w: number; h: number }) {
  const narration = bubble.kind === "narration";
  const factor = narration ? 1 : bubble.kind === "speech" ? 0.72 : 0.66;
  const tw = narration ? w - 20 : w * factor;
  const th = narration ? h - 12 : h * factor;
  const ox = (w - tw) / 2;
  const oy = (h - th) / 2;
  if (bubble.vertical && bubble.kind !== "sfx") {
    // Columns right to left, characters top to bottom.
    const perColumn = Math.max(1, Math.floor(th / (bubble.font_size * 1.05)));
    const columns = verticalColumns(bubble.text, perColumn);
    const colW = Math.min(bubble.font_size * 1.25, tw / Math.max(1, columns.length));
    const size = Math.min(bubble.font_size, Math.floor(colW / 1.15));
    const total = colW * columns.length;
    return (
      <>
        {columns.map((col, i) => (
          <Text
            key={i}
            text={col}
            x={ox + (tw + total) / 2 - colW * (i + 1)}
            y={oy}
            width={colW}
            height={th}
            align="center"
            fontSize={size}
            lineHeight={1.05}
            fontFamily={FONT_FAMILY}
            fontStyle="bold"
            fill="#111"
            listening={false}
          />
        ))}
      </>
    );
  }
  if (bubble.kind === "sfx") {
    const size = fitFont(bubble.text, w, h, Math.max(bubble.font_size, 40), true);
    return (
      <Text
        text={bubble.text}
        width={w}
        height={h}
        align="center"
        verticalAlign="middle"
        fontSize={size}
        fontFamily="'Bangers', Impact, sans-serif"
        fontStyle="bold"
        fill="#111"
        stroke="#fbfaf7"
        strokeWidth={Math.max(3, size / 9)}
        fillAfterStrokeEnabled
        skewX={-0.15}
        listening={false}
      />
    );
  }
  const size = fitFont(bubble.text, tw, th, bubble.font_size, true);
  return (
    <Text
      text={bubble.text}
      x={ox}
      y={oy}
      width={tw}
      height={th}
      align={narration ? "left" : "center"}
      verticalAlign="middle"
      fontSize={size}
      lineHeight={1.12}
      fontFamily={FONT_FAMILY}
      fontStyle="bold"
      fill="#111"
      listening={false}
    />
  );
}

function BubbleShape({ bubble, w, h, tipLocal }: { bubble: Bubble; w: number; h: number; tipLocal: [number, number] | null }) {
  const stroke = "#111";
  const tail =
    tipLocal && (bubble.kind === "speech" || bubble.kind === "shout") ? tailPoints(w, h, tipLocal) : null;
  switch (bubble.kind) {
    case "narration":
      return <Rect width={w} height={h} fill="#fbfaf7" stroke={stroke} strokeWidth={3} />;
    case "sfx":
      return <Rect width={w} height={h} fill="rgba(0,0,0,0)" />; // hit area only
    case "shout":
      return (
        <>
          <Line points={shoutPoints(w, h)} closed fill="#fbfaf7" stroke={stroke} strokeWidth={3} />
          {tail && <Line points={tail} closed fill="#fbfaf7" />}
          {tail && <Line points={tail} stroke={stroke} strokeWidth={3} />}
        </>
      );
    case "thought":
      return (
        <>
          <Shape
            sceneFunc={(ctx, shape) => {
              // A cloud: bumps around an ellipse, plus little circles toward the thinker.
              const cx = w / 2;
              const cy = h / 2;
              const bumps = Math.max(10, Math.floor((w + h) / 28));
              const r = Math.min(w, h) * 0.14;
              ctx.beginPath();
              for (let k = 0; k < bumps; k++) {
                const a = (2 * Math.PI * k) / bumps;
                const x = cx + Math.cos(a) * (w / 2 - r * 0.6);
                const y = cy + Math.sin(a) * (h / 2 - r * 0.6);
                ctx.moveTo(x + r, y);
                ctx.arc(x, y, r, 0, Math.PI * 2);
              }
              ctx.fillStrokeShape(shape);
            }}
            fill="#fbfaf7"
            stroke={stroke}
            strokeWidth={3}
          />
          <Ellipse x={w / 2} y={h / 2} radiusX={w / 2 - Math.min(w, h) * 0.12} radiusY={h / 2 - Math.min(w, h) * 0.12} fill="#fbfaf7" />
          {tipLocal &&
            [0.25, 0.5, 0.75].map((t, i) => (
              <Circle
                key={t}
                x={w / 2 + (tipLocal[0] - w / 2) * (0.55 + t * 0.4)}
                y={h / 2 + (tipLocal[1] - h / 2) * (0.55 + t * 0.4)}
                radius={[9, 6, 4][i]}
                fill="#fbfaf7"
                stroke={stroke}
                strokeWidth={2}
              />
            ))}
        </>
      );
    default:
      return (
        <>
          <Ellipse x={w / 2} y={h / 2} radiusX={w / 2} radiusY={h / 2} fill="#fbfaf7" stroke={stroke} strokeWidth={3} />
          {tail && <Line points={tail} closed fill="#fbfaf7" />}
          {tail && <Line points={tail} stroke={stroke} strokeWidth={3} />}
        </>
      );
  }
}

export default function PageCanvas({
  data,
  bubbles,
  displayWidth,
  selectedId,
  selectedPanel,
  imageVersion,
  mask,
  onSelectBubble,
  onSelectPanel,
  onChange,
  onEditText,
}: Props) {
  const scale = displayWidth / data.width;
  const inner = useMemo(() => Object.fromEntries(data.panels.map((p) => [p.panel, p.inner])), [data.panels]);
  const groupRefs = useRef<Record<string, Konva.Group | null>>({});
  const transformer = useRef<Konva.Transformer>(null);
  const drawing = useRef(false);
  const selected = bubbles.find((b) => b.id === selectedId) ?? null;

  useEffect(() => {
    const node = selected && !mask ? groupRefs.current[selected.id] : null;
    transformer.current?.nodes(node ? [node] : []);
    transformer.current?.getLayer()?.batchDraw();
  }, [selected, mask, bubbles]);

  const src = (image: string | null) => (image ? fileUrl(data.files_base + image) + (imageVersion ? `?v=${imageVersion}` : "") : null);

  // ---------------------------------------------------------------- mask painting (inpainting)
  function pagePoint(stage: Konva.Stage): [number, number] | null {
    const p = stage.getPointerPosition();
    return p ? [p.x / scale, p.y / scale] : null;
  }
  function onDown(e: Konva.KonvaEventObject<MouseEvent | TouchEvent>) {
    if (!mask) return;
    const pt = pagePoint(e.target.getStage()!);
    if (!pt) return;
    drawing.current = true;
    mask.onStrokes([...mask.strokes, { points: [...pt, ...pt], size: mask.brush, erase: mask.erase }]);
  }
  function onMove(e: Konva.KonvaEventObject<MouseEvent | TouchEvent>) {
    if (!mask || !drawing.current) return;
    const pt = pagePoint(e.target.getStage()!);
    if (!pt) return;
    const strokes = mask.strokes.slice();
    const last = strokes[strokes.length - 1];
    strokes[strokes.length - 1] = { ...last, points: [...last.points, ...pt] };
    mask.onStrokes(strokes);
  }
  const maskPanel = mask ? data.panels.find((p) => p.panel === mask.panel) : null;

  return (
    <Stage
      width={displayWidth}
      height={data.height * scale}
      scaleX={scale}
      scaleY={scale}
      onMouseDown={(e) => {
        if (mask) return onDown(e);
        if (e.target === e.target.getStage()) {
          onSelectBubble(null);
          onSelectPanel(null);
        }
      }}
      onTouchStart={onDown}
      onMouseMove={onMove}
      onTouchMove={onMove}
      onMouseUp={() => (drawing.current = false)}
      onTouchEnd={() => (drawing.current = false)}
      style={{ cursor: mask ? "crosshair" : "default" }}
    >
      <Layer listening={!mask}>
        <Rect width={data.width} height={data.height} fill="#ffffff" />
        {data.panels.map((p) => (
          <Group
            key={p.panel}
            onMouseDown={(e) => {
              if (mask) return;
              e.cancelBubble = true;
              onSelectBubble(null);
              onSelectPanel(p.panel);
            }}
          >
            <PanelArt src={src(p.image)} rect={p.rect} />
            <Rect x={p.rect.x} y={p.rect.y} width={p.rect.w} height={p.rect.h} stroke="#111" strokeWidth={data.border} />
          </Group>
        ))}
      </Layer>

      <Layer listening={!mask} opacity={mask ? 0.35 : 1}>
        {bubbles.map((b) => {
          const box = inner[b.panel];
          if (!box) return null;
          const px = toPx(b, box);
          const tip = b.tail ? pointToPx(b.tail, box) : null;
          const tipLocal: [number, number] | null = tip ? [tip[0] - px.x, tip[1] - px.y] : null;
          return (
            <Group
              key={b.id}
              ref={(node) => {
                groupRefs.current[b.id] = node;
              }}
              x={px.x}
              y={px.y}
              draggable={!mask}
              onMouseDown={(e) => {
                e.cancelBubble = true;
                onSelectBubble(b.id);
                onSelectPanel(b.panel);
              }}
              onTap={() => onSelectBubble(b.id)}
              onDblClick={() => onEditText?.(b.id)}
              onDragEnd={(e) => {
                onChange({ ...b, ...toFrac({ x: e.target.x(), y: e.target.y(), w: px.w, h: px.h }, box) });
              }}
              onTransformEnd={(e) => {
                const node = e.target;
                const w = Math.max(30, px.w * node.scaleX());
                const h = Math.max(24, px.h * node.scaleY());
                node.scale({ x: 1, y: 1 });
                onChange({ ...b, ...toFrac({ x: node.x(), y: node.y(), w, h }, box) });
              }}
            >
              <BubbleShape bubble={b} w={px.w} h={px.h} tipLocal={tipLocal} />
              <BubbleText bubble={b} w={px.w} h={px.h} />
            </Group>
          );
        })}
      </Layer>

      <Layer>
        {selectedPanel !== null && !mask && inner[selectedPanel] && (
          <Rect
            x={inner[selectedPanel].x}
            y={inner[selectedPanel].y}
            width={inner[selectedPanel].w}
            height={inner[selectedPanel].h}
            stroke="#d97706"
            strokeWidth={6 / scale}
            dash={[18, 10]}
            listening={false}
          />
        )}
        <Transformer
          ref={transformer}
          rotateEnabled={false}
          keepRatio={false}
          anchorSize={10 / Math.max(scale, 0.3)}
          borderStroke="#d97706"
          anchorStroke="#111"
          boundBoxFunc={(oldBox, newBox) => (newBox.width < 30 || newBox.height < 24 ? oldBox : newBox)}
        />
        {selected && selected.tail && !mask && inner[selected.panel] && (
          <Circle
            x={pointToPx(selected.tail, inner[selected.panel])[0]}
            y={pointToPx(selected.tail, inner[selected.panel])[1]}
            radius={11 / Math.max(scale, 0.3)}
            fill="#d97706"
            stroke="#111"
            strokeWidth={2}
            draggable
            onDragEnd={(e) => onChange({ ...selected, tail: pointToFrac([e.target.x(), e.target.y()], inner[selected.panel]) })}
          />
        )}
        {mask && maskPanel && (
          <Group clipX={maskPanel.inner.x} clipY={maskPanel.inner.y} clipWidth={maskPanel.inner.w} clipHeight={maskPanel.inner.h}>
            <Rect x={maskPanel.inner.x} y={maskPanel.inner.y} width={maskPanel.inner.w} height={maskPanel.inner.h} stroke="#d97706" strokeWidth={4 / scale} />
            {mask.strokes.map((s, i) => (
              <Line
                key={i}
                points={s.points}
                stroke={s.erase ? "#ffffff" : "#ef4444"}
                strokeWidth={s.size}
                lineCap="round"
                lineJoin="round"
                opacity={s.erase ? 1 : 0.55}
                globalCompositeOperation={s.erase ? "destination-out" : "source-over"}
              />
            ))}
          </Group>
        )}
      </Layer>
    </Stage>
  );
}
