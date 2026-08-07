import { useEffect, useMemo, useRef, useState } from "react";
import { convertFileSrc } from "@tauri-apps/api/core";
import { FolderOpen, Play } from "lucide-react";
import { pickDirectory, pickFile, pickFiles } from "../lib/tauri";
import type { Diagnostics, OverlayConfig } from "../types";

const OUT_W = 1080;
const OUT_H = 1920;
const MIN_LAYER_SIZE = 50;

type DragState =
  | { mode: "move"; startX: number; startY: number; startConfig: Pick<OverlayConfig, "x" | "y" | "width" | "height"> }
  | { mode: "resize"; handle: Handle; aspect: number | null; startX: number; startY: number; startConfig: Pick<OverlayConfig, "x" | "y" | "width" | "height"> };

type Handle = "nw" | "ne" | "sw" | "se";

export function OverlayPage({
  config,
  diagnostics,
  diagnosticsReady,
  submitting,
  submitError,
  onUpdate,
  onStart,
}: {
  config: OverlayConfig;
  diagnostics: Diagnostics;
  diagnosticsReady: boolean;
  submitting: boolean;
  submitError: string;
  onUpdate: (patch: Partial<OverlayConfig>) => void;
  onStart: () => void;
}) {
  const [videoAspect, setVideoAspect] = useState<number | null>(null);
  const [drag, setDrag] = useState<DragState | null>(null);
  const dragRef = useRef<DragState | null>(null);
  const stageWrapRef = useRef<HTMLDivElement | null>(null);
  const lastAutoFitVideoRef = useRef<string>("");
  const [frameError, setFrameError] = useState(false);
  const [videoError, setVideoError] = useState(false);
  const frameSrc = useFileSrc(config.frameFile);
  const videoSrc = useFileSrc(config.videoFiles[0] || "");
  const [previewScale, setPreviewScale] = useState(0.3);
  const layer = toPreviewRect(config, previewScale);
  const isLayerOutside = config.x >= OUT_W || config.y >= OUT_H || config.x + config.width <= 0 || config.y + config.height <= 0;
  const lockedAspect = config.lockAspect ? videoAspect || config.width / Math.max(1, config.height) : null;

  useEffect(() => {
    if (!drag) return;
    const handlePointerMove = (event: PointerEvent) => {
      const current = dragRef.current;
      if (!current) return;
      event.preventDefault();
      const dx = (event.clientX - current.startX) / previewScale;
      const dy = (event.clientY - current.startY) / previewScale;
      if (current.mode === "move") {
        updateLayer({ x: Math.round(current.startConfig.x + dx), y: Math.round(current.startConfig.y + dy) });
      } else {
        updateLayer(resizeFromCorner(current.startConfig, current.handle, dx, dy, current.aspect));
      }
    };
    const handlePointerUp = () => {
      dragRef.current = null;
      setDrag(null);
    };
    window.addEventListener("pointermove", handlePointerMove, { passive: false });
    window.addEventListener("pointerup", handlePointerUp);
    window.addEventListener("pointercancel", handlePointerUp);
    return () => {
      window.removeEventListener("pointermove", handlePointerMove);
      window.removeEventListener("pointerup", handlePointerUp);
      window.removeEventListener("pointercancel", handlePointerUp);
    };
  }, [drag, previewScale]);

  useEffect(() => {
    if (!stageWrapRef.current) return;
    const updateScale = () => {
      const rect = stageWrapRef.current?.getBoundingClientRect();
      if (!rect) return;
      const availableW = Math.max(260, rect.width - 36);
      const availableH = Math.max(360, rect.height - 36);
      const next = Math.min(availableW / OUT_W, availableH / OUT_H, 0.5);
      setPreviewScale(Math.max(0.18, next));
    };
    updateScale();
    const observer = new ResizeObserver(updateScale);
    observer.observe(stageWrapRef.current);
    window.addEventListener("resize", updateScale);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", updateScale);
    };
  }, []);

  const chooseFrame = async () => {
    const path = await pickFile("image");
    if (path) { setFrameError(false); onUpdate({ frameFile: path }); }
  };

  const chooseVideos = async () => {
    const paths = await pickFiles("video");
    if (paths.length) {
      setVideoError(false);
      lastAutoFitVideoRef.current = "";
      onUpdate({ videoFiles: paths });
    }
  };

  const chooseOutput = async () => {
    const path = await pickDirectory();
    if (path) onUpdate({ outputFolder: path });
  };

  const updateLayer = (patch: Partial<Pick<OverlayConfig, "x" | "y" | "width" | "height">>) => {
    const next = constrainLayer({
      x: patch.x ?? config.x,
      y: patch.y ?? config.y,
      width: patch.width ?? config.width,
      height: patch.height ?? config.height,
    });
    onUpdate(next);
  };

  const centerVideo = () => {
    updateLayer({ x: Math.round((OUT_W - config.width) / 2), y: Math.round((OUT_H - config.height) / 2) });
  };

  const defaultVideoSize = () => {
    const width = 800;
    const height = config.lockAspect && videoAspect ? Math.round(width / videoAspect) : 1080;
    updateLayer({ width, height, x: Math.round((OUT_W - width) / 2), y: Math.round((OUT_H - height) / 2) });
  };

  const fillCanvas = () => updateLayer({ x: 0, y: 0, width: OUT_W, height: OUT_H });

  const fitVertical = () => {
    const aspect = videoAspect || 9 / 16;
    const height = OUT_H;
    const width = Math.round(height * aspect);
    updateLayer({ width, height, x: Math.round((OUT_W - width) / 2), y: 0 });
  };

  const fitLayerToVideoAspect = (aspect: number, videoKey: string) => {
    if (!Number.isFinite(aspect) || aspect <= 0) return;
    if (lastAutoFitVideoRef.current === videoKey) return;
    lastAutoFitVideoRef.current = videoKey;
    const width = Math.min(OUT_W, Math.max(MIN_LAYER_SIZE, Math.round(config.width)));
    const heightByWidth = Math.round(width / aspect);
    let nextWidth = width;
    let nextHeight = heightByWidth;
    if (nextHeight > OUT_H) {
      nextHeight = OUT_H;
      nextWidth = Math.round(nextHeight * aspect);
    }
    updateLayer({
      width: nextWidth,
      height: nextHeight,
      x: Math.round((OUT_W - nextWidth) / 2),
      y: Math.round((OUT_H - nextHeight) / 2),
    });
  };

  const startPointer = (event: React.PointerEvent, mode: "move" | "resize", handle?: Handle) => {
    event.preventDefault();
    event.stopPropagation();
    const next = {
      mode,
      handle: handle || "se",
      aspect: mode === "resize" ? lockedAspect : null,
      startX: event.clientX,
      startY: event.clientY,
      startConfig: { x: config.x, y: config.y, width: config.width, height: config.height },
    } as DragState;
    dragRef.current = next;
    setDrag(next);
  };

  const zoomAt = (event: React.WheelEvent) => {
    event.preventDefault();
    const rect = event.currentTarget.getBoundingClientRect();
    const cx = (event.clientX - rect.left) / previewScale;
    const cy = (event.clientY - rect.top) / previewScale;
    if (cx < config.x || cy < config.y || cx > config.x + config.width || cy > config.y + config.height) return;
    const factor = event.deltaY < 0 ? 1.05 : 0.95;
    const oldW = config.width;
    const oldH = config.height;
    const width = Math.max(MIN_LAYER_SIZE, Math.round(oldW * factor));
    const height = Math.max(MIN_LAYER_SIZE, Math.round(lockedAspect ? width / lockedAspect : oldH * factor));
    const relX = oldW ? (cx - config.x) / oldW : 0.5;
    const relY = oldH ? (cy - config.y) / oldH : 0.5;
    updateLayer({ width, height, x: Math.round(cx - width * relX), y: Math.round(cy - height * relY) });
  };

  return (
    <div>
      <h1 className="page-title">背景图视频合成</h1>
      <p className="page-subtitle">选择静态背景图和一批视频，拖动预览中的视频层调整位置和大小，批量导出 1080×1920 MP4。</p>

      <div className="overlay-workbench">
        <section className="panel overlay-files-panel">
          <div className="panel-header"><span className="panel-title">文件</span></div>
          <PathField label="背景图片" value={config.frameFile} placeholder="PNG / JPG / WEBP / BMP" onChange={(frameFile) => onUpdate({ frameFile })} onPick={chooseFrame} />
          <div className="input-field">
            <label>视频文件</label>
            <div className="input-with-btn">
              <input value={videoSummary(config.videoFiles)} readOnly placeholder="选择一个或多个视频" />
              <button className="btn btn-secondary btn-sm" onClick={chooseVideos}><FolderOpen size={14} />多选</button>
            </div>
            {isLayerOutside && (
              <div className="overlay-warning-stack">
                <div className="overlay-warning danger">视频层已完全移出画布，导出会看不到视频。</div>
              </div>
            )}
            <span className="input-hint">当前预览使用第一个视频，批量导出会处理全部已选视频。</span>
          </div>
          <PathField label="输出文件夹" value={config.outputFolder} placeholder="默认：第一个视频同目录 / output" onChange={(outputFolder) => onUpdate({ outputFolder })} onPick={chooseOutput} />
        </section>

        <section className="panel overlay-preview-panel">
          <div className="panel-header overlay-preview-head">
            <span className="panel-title">预览</span>
            <span>拖动视频层；拉四角缩放；滚轮缩放</span>
          </div>
          <div ref={stageWrapRef} className="overlay-stage-wrap">
            <div className="overlay-stage" style={{ width: OUT_W * previewScale, height: OUT_H * previewScale }} onWheel={zoomAt}>
              {frameSrc && !frameError ? <img className="overlay-frame-img" src={frameSrc} alt="背景预览" draggable={false} onError={() => setFrameError(true)} /> : <div className="overlay-frame-placeholder">{config.frameFile ? "背景预览加载失败" : "请选择 9:16 背景图片"}</div>}
              <div className={`overlay-video-layer ${drag ? "dragging" : ""}`} style={{ left: layer.x, top: layer.y, width: layer.width, height: layer.height }} onPointerDown={(event) => startPointer(event, "move")}>
                {videoSrc && !videoError ? (
                  <video className={config.mode === "contain" ? "contain" : "cover"} src={videoSrc} muted autoPlay loop playsInline preload="metadata" onLoadedMetadata={(event) => {
                    const video = event.currentTarget;
                    if (video.videoWidth > 0 && video.videoHeight > 0) {
                      const aspect = video.videoWidth / video.videoHeight;
                      setVideoAspect(aspect);
                      fitLayerToVideoAspect(aspect, config.videoFiles[0] || videoSrc);
                    }
                  }} onError={() => setVideoError(true)} />
                ) : <div className="overlay-video-placeholder">{config.videoFiles.length ? "视频预览加载失败" : "中间视频区域"}</div>}
                <span className="overlay-size-label">{Math.round(config.width)}×{Math.round(config.height)}{config.lockAspect ? " 锁比例" : " 自由"}</span>
                {(["nw", "ne", "sw", "se"] as const).map((handle) => <button key={handle} type="button" className={`overlay-resize-handle ${handle}`} onPointerDown={(event) => startPointer(event, "resize", handle)} aria-label={`缩放 ${handle}`} />)}
              </div>
            </div>
          </div>
        </section>

        <section className="panel overlay-controls-panel">
          <div className="overlay-controls-scroll">
            <div className="panel-header"><span className="panel-title">视频层设置</span></div>
            <div className="form-row">
              <NumberField label="X" value={config.x} onChange={(x) => updateLayer({ x })} />
              <NumberField label="Y" value={config.y} onChange={(y) => updateLayer({ y })} />
            </div>
            <div className="form-row">
              <NumberField label="宽" value={config.width} min={1} onChange={(width) => updateLayer({ width })} />
              <NumberField label="高" value={config.height} min={1} onChange={(height) => updateLayer({ height })} />
            </div>
            <div className="overlay-button-grid">
              <button className="btn btn-secondary" onClick={centerVideo}>一键居中</button>
              <button className="btn btn-secondary" onClick={defaultVideoSize}>推荐大小</button>
              <button className="btn btn-secondary" onClick={fillCanvas}>铺满画布</button>
              <button className="btn btn-secondary" onClick={fitVertical}>竖屏适配</button>
            </div>
            <div className="input-field">
              <label>适配方式</label>
              <select value={config.mode} onChange={(e) => onUpdate({ mode: e.target.value as OverlayConfig["mode"] })}>
                <option value="cover">cover：铺满区域，允许裁剪</option>
                <option value="contain">contain：完整显示，可能黑边</option>
              </select>
            </div>
            <Toggle label="锁定原视频比例" hint="拖拽四角和滚轮缩放时保持视频比例" value={config.lockAspect} onChange={() => onUpdate({ lockAspect: !config.lockAspect })} />
            <Toggle label="保留原视频音频" value={config.keepAudio} onChange={() => onUpdate({ keepAudio: !config.keepAudio })} />

            <div className="panel-divider" />
            <div className="panel-header"><span className="panel-title">编码参数</span></div>
            <div className="form-row">
              <NumberField label="FPS" value={config.fps} min={1} onChange={(fps) => onUpdate({ fps })} />
              <NumberField label="CRF" value={config.crf} min={0} max={51} onChange={(crf) => onUpdate({ crf })} />
            </div>
            <div className="input-field">
              <label>Preset</label>
              <select value={config.preset} onChange={(e) => onUpdate({ preset: e.target.value as OverlayConfig["preset"] })}>
                {(["ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow"] as const).map((preset) => <option key={preset} value={preset}>{preset}</option>)}
              </select>
              <span className="input-hint">CRF 越小越清晰，推荐 18-23。</span>
            </div>
            <div className="input-field">
              <label>编码器</label>
              <select value={config.encoder} onChange={(e) => onUpdate({ encoder: e.target.value })}>
                <option value="auto">自动推荐</option>
                <option value="cpu_libx264">CPU libx264</option>
                <option value="nvenc_h264" disabled={diagnosticsReady && !diagnostics.hasNvenc}>NVIDIA NVENC{diagnosticsReady && !diagnostics.hasNvenc ? "（不可用）" : ""}</option>
                <option value="qsv_h264" disabled={diagnosticsReady && !diagnostics.hasQsv}>Intel QSV{diagnosticsReady && !diagnostics.hasQsv ? "（不可用）" : ""}</option>
                <option value="amf_h264" disabled={diagnosticsReady && !diagnostics.hasAmf}>AMD AMF{diagnosticsReady && !diagnostics.hasAmf ? "（不可用）" : ""}</option>
              </select>
            </div>
            <div className="form-row">
              <NumberField label="并发数" value={config.workers} min={1} max={4} onChange={(workers) => onUpdate({ workers })} />
              <div className="input-field">
                <label>重名处理</label>
                <select value={config.conflictStrategy} onChange={(e) => onUpdate({ conflictStrategy: e.target.value as OverlayConfig["conflictStrategy"] })}>
                  <option value="suffix">自动续号</option>
                  <option value="overwrite">覆盖</option>
                  <option value="skip">跳过</option>
                </select>
              </div>
            </div>

            <div className="panel-divider" />
            <div className="panel-header"><span className="panel-title">共用命名规则</span></div>
            <Toggle label="启用自定义命名" value={config.enableAutoNaming} onChange={() => onUpdate({ enableAutoNaming: !config.enableAutoNaming })} />
            <Toggle label="包含原视频名" value={config.namingUseSourceName} onChange={() => onUpdate({ namingUseSourceName: !config.namingUseSourceName })} />
            <div className="form-row">
              <TextField label="日期" value={config.namingDate} onChange={(namingDate) => onUpdate({ namingDate })} />
              <TextField label="字段 1" value={config.namingPart1} onChange={(namingPart1) => onUpdate({ namingPart1 })} />
            </div>
            <div className="form-row">
              <TextField label="字段 2" value={config.namingPart2} onChange={(namingPart2) => onUpdate({ namingPart2 })} />
              <TextField label="字段 3" value={config.namingPart3} onChange={(namingPart3) => onUpdate({ namingPart3 })} />
            </div>
            <div className="form-row">
              <TextField label="字段 4" value={config.namingPart4} onChange={(namingPart4) => onUpdate({ namingPart4 })} />
              <div className="input-field">
                <label>序号位数</label>
                <select value={config.namingSeqDigits} onChange={(e) => onUpdate({ namingSeqDigits: Number(e.target.value) })}>
                  <option value={3}>3</option>
                  <option value={4}>4</option>
                  <option value={5}>5</option>
                  <option value={6}>6</option>
                </select>
              </div>
            </div>
            <div className="naming-preview">{overlayPreview(config)}</div>
          </div>
          <div className="overlay-controls-footer">
            {submitError && <div className="form-error" role="alert">{submitError}</div>}
            <button className="btn btn-primary btn-lg btn-block" onClick={onStart} disabled={submitting}><Play size={16} />{submitting ? "正在提交..." : "加入任务队列"}</button>
          </div>
        </section>
      </div>
    </div>
  );
}

function useFileSrc(path: string): string {
  return useMemo(() => path ? convertFileSrc(path) : "", [path]);
}

function PathField({ label, value, placeholder, onChange, onPick }: { label: string; value: string; placeholder: string; onChange: (value: string) => void; onPick: () => void }) {
  return (
    <div className="input-field">
      <label>{label}</label>
      <div className="input-with-btn">
        <input value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} />
        <button className="btn btn-secondary btn-sm" onClick={onPick}><FolderOpen size={14} />选择</button>
      </div>
    </div>
  );
}

function Toggle({ label, hint, value, onChange }: { label: string; hint?: string; value: boolean; onChange: () => void }) {
  return (
    <div className="toggle-row">
      <div className="toggle-row-info"><strong>{label}</strong>{hint && <span>{hint}</span>}</div>
      <div className={value ? "switch on" : "switch"} onClick={onChange} />
    </div>
  );
}

function NumberField({ label, value, min, max, onChange }: { label: string; value: number; min?: number; max?: number; onChange: (value: number) => void }) {
  return (
    <div className="input-field">
      <label>{label}</label>
      <input type="number" min={min} max={max} value={Math.round(value)} onChange={(e) => onChange(Number(e.target.value) || 0)} />
    </div>
  );
}

function TextField({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  return (
    <div className="input-field">
      <label>{label}</label>
      <input value={value} onChange={(e) => onChange(e.target.value)} />
    </div>
  );
}

function toPreviewRect(config: OverlayConfig, scale: number) {
  return {
    x: config.x * scale,
    y: config.y * scale,
    width: Math.max(1, config.width * scale),
    height: Math.max(1, config.height * scale),
  };
}

function constrainLayer(layer: Pick<OverlayConfig, "x" | "y" | "width" | "height">) {
  const width = Math.min(2160, Math.max(MIN_LAYER_SIZE, Math.round(layer.width)));
  const height = Math.min(3840, Math.max(MIN_LAYER_SIZE, Math.round(layer.height)));
  const minX = -width + 1;
  const maxX = OUT_W - 1;
  const minY = -height + 1;
  const maxY = OUT_H - 1;
  return {
    width,
    height,
    x: Math.min(maxX, Math.max(minX, Math.round(layer.x))),
    y: Math.min(maxY, Math.max(minY, Math.round(layer.y))),
  };
}

function resizeFromCorner(start: Pick<OverlayConfig, "x" | "y" | "width" | "height">, handle: Handle, dx: number, dy: number, aspect: number | null) {
  let left = start.x;
  let top = start.y;
  let right = start.x + start.width;
  let bottom = start.y + start.height;
  if (handle.includes("w")) left += dx;
  if (handle.includes("e")) right += dx;
  if (handle.includes("n")) top += dy;
  if (handle.includes("s")) bottom += dy;

  if (aspect && aspect > 0) {
    const anchor = anchorFor(handle, start);
    const targetW = Math.max(MIN_LAYER_SIZE, Math.abs((handle.includes("w") ? left : right) - anchor.x));
    const targetH = Math.max(MIN_LAYER_SIZE, Math.abs((handle.includes("n") ? top : bottom) - anchor.y));
    const width = targetW / aspect >= targetH ? targetW : targetH * aspect;
    const height = width / aspect;
    left = handle.includes("w") ? anchor.x - width : anchor.x;
    right = handle.includes("w") ? anchor.x : anchor.x + width;
    top = handle.includes("n") ? anchor.y - height : anchor.y;
    bottom = handle.includes("n") ? anchor.y : anchor.y + height;
  } else {
    if (right - left < MIN_LAYER_SIZE) handle.includes("w") ? left = right - MIN_LAYER_SIZE : right = left + MIN_LAYER_SIZE;
    if (bottom - top < MIN_LAYER_SIZE) handle.includes("n") ? top = bottom - MIN_LAYER_SIZE : bottom = top + MIN_LAYER_SIZE;
  }

  return { x: Math.round(left), y: Math.round(top), width: Math.round(right - left), height: Math.round(bottom - top) };
}

function anchorFor(handle: Handle, start: Pick<OverlayConfig, "x" | "y" | "width" | "height">) {
  const left = start.x;
  const top = start.y;
  const right = start.x + start.width;
  const bottom = start.y + start.height;
  return {
    x: handle.includes("w") ? right : left,
    y: handle.includes("n") ? bottom : top,
  };
}

function videoSummary(paths: string[]): string {
  if (paths.length === 0) return "";
  return paths.length === 1 ? paths[0] : `已选择 ${paths.length} 个视频：${paths[0]}`;
}

function overlayPreview(config: OverlayConfig): string {
  if (!config.enableAutoNaming) return "overlay_0001.mp4";
  const parts = [config.namingDate, config.namingPart1, config.namingUseSourceName ? "原视频名" : "", config.namingPart2, config.namingPart3, config.namingPart4]
    .map((part) => part.replace(/[<>:"/\\|?*\x00-\x1F]/g, "").trim())
    .filter(Boolean);
  parts.push("1".padStart(config.namingSeqDigits, "0"));
  return `${parts.join("-")}.mp4`;
}
