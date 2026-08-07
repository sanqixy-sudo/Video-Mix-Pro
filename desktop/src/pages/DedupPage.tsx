import type { ReactNode } from "react";
import { Activity, FolderOpen, Image, ListPlus, Play, Video } from "lucide-react";
import { pickDirectory } from "../lib/tauri";
import type { DedupConfig, Diagnostics, RenderTaskStatus } from "../types";

export function DedupPage({
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
  config: DedupConfig;
  diagnostics: Diagnostics;
  diagnosticsReady: boolean;
  submitting: boolean;
  submitError: string;
  taskStatus: RenderTaskStatus;
  onUpdate: (patch: Partial<DedupConfig>) => void;
  onStart: () => void;
  onOpenTasks: () => void;
}) {
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

  const chooseOutput = async () => {
    const path = await pickDirectory();
    if (path) onUpdate({ outputFolder: path });
  };

  return (
    <div className="dedup-page">
      <div className="watermark-title-row">
        <div>
          <h1 className="page-title">批量视频去重</h1>
          <p className="page-subtitle">对文件夹内视频做轻微随机化处理：码率、帧率、速度与极淡画面滤镜都会小幅变化，输出文件名保持不变。</p>
        </div>
        <span className={`status-chip ${diagnosticsReady && diagnostics.hasFfmpeg ? "connected" : diagnosticsReady ? "failed" : "checking"}`}>
          FFmpeg：{diagnosticsReady ? (diagnostics.hasFfmpeg ? "已检测到" : "未检测到") : "检测中"}
        </span>
      </div>

      <section className="watermark-file-grid dedup-file-grid">
        <FileCard step="1" icon={<Video size={18} />} title="视频文件夹" hint="自动读取该目录下所有支持格式的视频。" value={config.sourceFolder} placeholder="请选择视频文件夹" onChange={updateSource} onPick={chooseSource} />
        <FileCard step="2" icon={<FolderOpen size={18} />} title="输出文件夹" hint="默认在原文件夹下新建“去重”。" value={config.outputFolder} placeholder={config.sourceFolder ? defaultOutputFolder(config.sourceFolder) : "选择素材后自动生成"} onChange={(outputFolder) => onUpdate({ outputFolder })} onPick={chooseOutput} />
      </section>

      <section className="panel dedup-settings-panel">
        <div className="panel-header">
          <span className="panel-title">去重方式</span>
          <span className="watermark-name-note">输出保持原视频文件名</span>
        </div>
        <div className="dedup-option-grid">
          <OptionToggle icon={<Activity size={18} />} title="随机码率" hint="每个视频使用不同的码率或 CRF。" checked={config.randomBitrate} onChange={(randomBitrate) => onUpdate({ randomBitrate })} />
          <OptionToggle icon={<Video size={18} />} title="抽帧" hint="轻微调整输出帧率，让帧序列发生变化。" checked={config.dropFrames} onChange={(dropFrames) => onUpdate({ dropFrames })} />
          <OptionToggle icon={<Activity size={18} />} title="微变速" hint="0.985x - 1.015x 范围内小幅变速。" checked={config.microSpeed} onChange={(microSpeed) => onUpdate({ microSpeed })} />
          <OptionToggle icon={<Image size={18} />} title="不可见滤镜" hint="极淡亮度、对比度、饱和度与色相扰动。" checked={config.subtleFilter} onChange={(subtleFilter) => onUpdate({ subtleFilter })} />
        </div>
        <div className="watermark-options-row dedup-options-row">
          <label className="checkbox-row"><input type="checkbox" checked={config.keepAudio} onChange={(event) => onUpdate({ keepAudio: event.target.checked })} /><Activity size={15} /><span>保留并同步处理音频</span></label>
          <label className="input-field watermark-workers"><span>并发处理</span><select value={config.workers} onChange={(event) => onUpdate({ workers: Number(event.target.value) })}><option value={1}>1 路</option><option value={2}>2 路</option><option value={3}>3 路</option><option value={4}>4 路</option></select></label>
          <label className="input-field watermark-workers"><span>同名文件</span><select value={config.conflictStrategy} onChange={(event) => onUpdate({ conflictStrategy: event.target.value as DedupConfig["conflictStrategy"] })}><option value="skip">跳过已存在</option><option value="overwrite">覆盖</option><option value="suffix">自动加后缀</option></select></label>
        </div>
        {submitError && <div className="form-error">{submitError}</div>}
      </section>

      <section className="panel watermark-submit-bar">
        <div>
          <strong>{queued > 0 ? `队列中已有 ${queued} 个任务` : "准备加入任务队列"}</strong>
          <span>每次提交处理当前文件夹内的全部视频，可继续配置下一批素材。</span>
        </div>
        <div className="watermark-submit-actions">
          <button className="btn btn-secondary" onClick={onOpenTasks}><ListPlus size={16} />查看队列</button>
          <button className="btn btn-primary btn-lg" disabled={submitting} onClick={onStart}><Play size={16} />{submitting ? "正在加入…" : "开始去重"}</button>
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

function OptionToggle({ icon, title, hint, checked, onChange }: { icon: ReactNode; title: string; hint: string; checked: boolean; onChange: (checked: boolean) => void }) {
  return (
    <button className={checked ? "dedup-option active" : "dedup-option"} onClick={() => onChange(!checked)}>
      <span className="dedup-option-icon">{icon}</span>
      <span className="dedup-option-copy">
        <strong>{title}</strong>
        <small>{hint}</small>
      </span>
      <span className={checked ? "switch on" : "switch"} />
    </button>
  );
}

function defaultOutputFolder(sourceFolder: string): string {
  const source = sourceFolder.trim().replace(/[\\/]+$/, "");
  if (!source) return "";
  return `${source}${source.includes("\\") ? "\\" : "/"}去重`;
}
