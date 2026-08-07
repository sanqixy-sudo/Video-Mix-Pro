import { useMemo, useState, type ReactNode } from "react";
import { convertFileSrc } from "@tauri-apps/api/core";
import { FolderOpen, Image, ListPlus, Play, Video } from "lucide-react";
import { pickDirectory, pickFile } from "../lib/tauri";
import type { Diagnostics, RenderTaskStatus, WatermarkConfig } from "../types";

export function WatermarkPage({
  config,
  diagnostics,
  diagnosticsReady,
  submitting,
  submitError,
  taskStatus,
  onUpdate,
  onStart,
  onOpenTasks,
}: {
  config: WatermarkConfig;
  diagnostics: Diagnostics;
  diagnosticsReady: boolean;
  submitting: boolean;
  submitError: string;
  taskStatus: RenderTaskStatus;
  onUpdate: (patch: Partial<WatermarkConfig>) => void;
  onStart: () => void;
  onOpenTasks: () => void;
}) {
  const [logoError, setLogoError] = useState(false);
  const logoSrc = useMemo(() => config.logoFile ? convertFileSrc(config.logoFile) : "", [config.logoFile]);
  const queued = taskStatus.queue.filter((item) => ["waiting", "running", "cancelling"].includes(item.status)).length;

  const updateSource = (sourceFolder: string) => {
    const previousDefault = defaultOutputFolder(config.sourceFolder);
    const shouldFollowSource = !config.outputFolder.trim() || config.outputFolder === previousDefault;
    onUpdate({
      sourceFolder,
      ...(shouldFollowSource ? { outputFolder: defaultOutputFolder(sourceFolder) } : {}),
    });
  };

  const chooseSource = async () => {
    const path = await pickDirectory();
    if (path) updateSource(path);
  };

  const chooseLogo = async () => {
    const path = await pickFile("image");
    if (path) {
      setLogoError(false);
      onUpdate({ logoFile: path });
    }
  };

  const chooseOutput = async () => {
    const path = await pickDirectory();
    if (path) onUpdate({ outputFolder: path });
  };

  const animationSeconds = Math.max(2.8, Math.min(12, 900 / Math.max(40, config.speed)));
  const previewWidth = Math.max(10, Math.min(45, config.widthPercent * 1.6));

  return (
    <div className="watermark-page">
      <div className="watermark-title-row">
        <div>
          <h1 className="page-title">批量添加飘动水印</h1>
          <p className="page-subtitle">选择整个视频文件夹和一张 Logo，水印会像 DVD 标志一样在画面内斜向反弹。</p>
        </div>
        <span className={`status-chip ${diagnosticsReady && diagnostics.hasFfmpeg ? "connected" : diagnosticsReady ? "failed" : "checking"}`}>
          FFmpeg：{diagnosticsReady ? (diagnostics.hasFfmpeg ? "已检测到" : "未检测到") : "检测中"}
        </span>
      </div>

      <section className="watermark-file-grid">
        <FileCard step="1" icon={<Video size={18} />} title="视频文件夹" hint="自动读取该目录下所有支持格式的视频。" value={config.sourceFolder} placeholder="请选择素材文件夹" onChange={updateSource} onPick={chooseSource} />
        <FileCard step="2" icon={<Image size={18} />} title="Logo 图片" hint="建议使用透明底 PNG，显示效果更干净。" value={config.logoFile} placeholder="请选择 Logo 图片" onChange={(logoFile) => { setLogoError(false); onUpdate({ logoFile }); }} onPick={chooseLogo} />
        <FileCard step="3" icon={<FolderOpen size={18} />} title="输出文件夹" hint="默认在素材文件夹下新建“水印版”。" value={config.outputFolder} placeholder={config.sourceFolder ? defaultOutputFolder(config.sourceFolder) : "选择素材后自动生成"} onChange={(outputFolder) => onUpdate({ outputFolder })} onPick={chooseOutput} />
      </section>

      <section className="panel watermark-settings-panel">
        <div className="watermark-settings-main">
          <div className="panel-header"><span className="panel-title">参数设置</span><span className="watermark-name-note">输出保持原素材文件名</span></div>
          <div className="watermark-parameter-grid">
            <NumberField label="Logo 宽度占比" suffix="%" hint="5 - 35" value={config.widthPercent} min={5} max={35} step={0.5} onChange={(widthPercent) => onUpdate({ widthPercent })} />
            <NumberField label="飘动速度" suffix="px/秒" hint="40 - 600" value={config.speed} min={40} max={600} step={5} onChange={(speed) => onUpdate({ speed })} />
            <NumberField label="透明度" hint="0.1 - 1.0" value={config.opacity} min={0.1} max={1} step={0.05} onChange={(opacity) => onUpdate({ opacity })} />
          </div>
          <div className="watermark-options-row">
            <label className="checkbox-row"><input type="checkbox" checked={config.keepAudio} onChange={(event) => onUpdate({ keepAudio: event.target.checked })} /><span>保留原视频音频</span></label>
            <label className="input-field watermark-workers"><span>并发处理</span><select value={config.workers} onChange={(event) => onUpdate({ workers: Number(event.target.value) })}><option value={1}>1 路</option><option value={2}>2 路</option><option value={3}>3 路</option><option value={4}>4 路</option></select></label>
            <label className="input-field watermark-workers"><span>同名文件</span><select value={config.conflictStrategy} onChange={(event) => onUpdate({ conflictStrategy: event.target.value as WatermarkConfig["conflictStrategy"] })}><option value="skip">跳过已存在</option><option value="overwrite">覆盖</option><option value="suffix">自动加后缀</option></select></label>
          </div>
          {submitError && <div className="form-error">{submitError}</div>}
        </div>

        <div className="watermark-preview-card">
          <div className="watermark-preview-label">运动预览</div>
          <div className="watermark-preview-stage">
            {logoSrc && !logoError ? (
              <img
                key={logoSrc}
                src={logoSrc}
                alt="Logo 预览"
                className="watermark-preview-logo"
                style={{ width: `${previewWidth}%`, opacity: config.opacity, animationDuration: `${animationSeconds}s` }}
                onError={() => setLogoError(true)}
              />
            ) : <span>{config.logoFile ? "Logo 预览加载失败" : "选择 Logo 后预览飘动效果"}</span>}
          </div>
        </div>
      </section>

      <section className="panel watermark-submit-bar">
        <div>
          <strong>{queued > 0 ? `队列中已有 ${queued} 个任务` : "准备加入任务队列"}</strong>
          <span>每次提交处理当前文件夹内的全部视频，可继续配置下一批素材。</span>
        </div>
        <div className="watermark-submit-actions">
          <button className="btn btn-secondary" onClick={onOpenTasks}><ListPlus size={16} />查看队列</button>
          <button className="btn btn-primary btn-lg" disabled={submitting} onClick={onStart}><Play size={16} />{submitting ? "正在加入…" : "加入任务队列"}</button>
        </div>
      </section>
    </div>
  );
}

function FileCard({ step, icon, title, hint, value, placeholder, onChange, onPick }: { step: string; icon: ReactNode; title: string; hint: string; value: string; placeholder: string; onChange: (value: string) => void; onPick: () => void }) {
  return (
    <div className="panel watermark-file-card">
      <div className="watermark-file-title"><span className="watermark-step">{step}</span>{icon}<strong>{title}</strong></div>
      <p>{hint}</p>
      <input value={value} title={value} placeholder={placeholder} onChange={(event) => onChange(event.target.value)} />
      <button className="btn btn-secondary" onClick={onPick}><FolderOpen size={15} />选择</button>
    </div>
  );
}

function NumberField({ label, suffix, hint, value, min, max, step, onChange }: { label: string; suffix?: string; hint: string; value: number; min: number; max: number; step: number; onChange: (value: number) => void }) {
  return (
    <label className="input-field">
      <span>{label}{suffix ? `（${suffix}）` : ""}</span>
      <input type="number" value={value} min={min} max={max} step={step} onChange={(event) => onChange(Number(event.target.value))} />
      <span className="input-hint">{hint}</span>
    </label>
  );
}

function defaultOutputFolder(sourceFolder: string): string {
  const source = sourceFolder.trim().replace(/[\\/]+$/, "");
  if (!source) return "";
  return `${source}${source.includes("\\") ? "\\" : "/"}水印版`;
}
