import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { Activity, AlertTriangle, CheckCircle2, FolderOpen, ListChecks, Play } from "lucide-react";
import { pickDirectory, pickFile } from "../lib/tauri";
import { formatNumber, maxUniqueCount } from "../lib/math";
import { encoderLabel } from "../lib/performance";
import type { Diagnostics, MaterialConfig, RenderTaskStatus, ScanSummary } from "../types";

const MODE_KEY = "video_mix_workflow_mode";

export type ScanViewState = {
  status: "idle" | "scanning" | "ready" | "error";
  message: string;
};

export function MixWorkflowPage({
  materials,
  scan,
  scanState,
  diagnostics,
  diagnosticsReady,
  authActive,
  submitting,
  submitError,
  taskStatus,
  onUpdate,
  onStart,
  onOpenAuth,
  onOpenTasks,
  onOpenPerformance,
}: {
  materials: MaterialConfig;
  scan: ScanSummary;
  scanState: ScanViewState;
  diagnostics: Diagnostics;
  diagnosticsReady: boolean;
  authActive: boolean;
  submitting: boolean;
  submitError: string;
  taskStatus: RenderTaskStatus;
  onUpdate: (patch: Partial<MaterialConfig>) => void;
  onStart: () => void;
  onOpenAuth: () => void;
  onOpenTasks: () => void;
  onOpenPerformance: () => void;
}) {
  const [mode, setMode] = useState<"simple" | "advanced">(() => localStorage.getItem(MODE_KEY) === "advanced" ? "advanced" : "simple");
  const selectedEncoderLabel = encoderLabel(materials.encoder);
  const maxCombos = maxUniqueCount(scan.mainCount, materials.segmentCount, materials.allowRepeatInsideOneVideo);
  const repeatOverflow = Math.max(0, materials.outputCount - maxCombos);
  const unfinished = taskStatus.pendingCount + (taskStatus.running ? 1 : 0);

  useEffect(() => {
    localStorage.setItem(MODE_KEY, mode);
  }, [mode]);

  const blockingIssues = getBlockingIssues(materials, scan, scanState, diagnosticsReady, diagnostics);
  const canSubmit = blockingIssues.length === 0 && !submitting;

  const pickSource = async () => {
    const path = await pickDirectory();
    if (path) onUpdate({ sourceFolder: path });
  };
  const pickOutput = async () => {
    const path = await pickDirectory();
    if (path) onUpdate({ outputFolder: path });
  };

  return (
    <div className="mix-workflow-page">
      <div className="workflow-title-row">
        <div>
          <h1 className="page-title">批量混剪</h1>
          <p className="page-subtitle">按步骤完成配置，提交后可以继续添加下一批任务</p>
        </div>
        <div className="mode-switch" aria-label="配置模式">
          <button className={mode === "simple" ? "active" : ""} onClick={() => setMode("simple")}><CheckCircle2 size={14} />简单模式</button>
          <button className={mode === "advanced" ? "active" : ""} onClick={() => setMode("advanced")}><ListChecks size={14} />高级模式</button>
        </div>
      </div>

      <section className="workflow-step panel">
        <StepHeader number={1} title="选择素材与输出位置" description="选择后会自动扫描，不需要手动刷新" />
        <div className="workflow-two-columns">
          <PathField label="素材文件夹" value={materials.sourceFolder} placeholder="选择包含主素材视频的文件夹" onChange={(sourceFolder) => onUpdate({ sourceFolder })} onPick={pickSource} />
          <PathField label="输出文件夹" value={materials.outputFolder} placeholder="留空则使用素材目录下的 output" onChange={(outputFolder) => onUpdate({ outputFolder })} onPick={pickOutput} />
        </div>
        <ScanFeedback state={scanState} scan={scan} />
      </section>

      <section className="workflow-step panel">
        <StepHeader number={2} title="设置生成数量" description="普通用户通常只需要调整这三项" />
        <div className="workflow-basic-grid">
          <NumberField label="每条使用素材数" value={materials.segmentCount} min={1} onChange={(segmentCount) => onUpdate({ segmentCount })} />
          <NumberField label="计划生成数量" value={materials.outputCount} min={1} onChange={(outputCount) => onUpdate({ outputCount })} />
          <Toggle label="保留原视频声音" value={materials.keepAudio} onChange={() => onUpdate({ keepAudio: !materials.keepAudio })} />
        </div>
        <div className="input-field">
          <label htmlFor="mix-orientation">输出画面</label>
          <select id="mix-orientation" value={materials.orientation} onChange={(event) => onUpdate({ orientation: event.target.value as MaterialConfig["orientation"] })}>
            <option value="portrait">竖屏 · 1080×1920</option>
            <option value="landscape">横屏 · 1920×1080</option>
          </select>
          <span className="input-hint">素材会按比例适配画面，空余区域补黑边。</span>
        </div>
        <div className="workflow-summary-strip">
          <span>主素材 <strong>{formatNumber(scan.mainCount)}</strong></span>
          <span>理论组合 <strong>{formatNumber(maxCombos)}</strong></span>
          <span>计划生成 <strong>{formatNumber(materials.outputCount)}</strong></span>
          <span className={repeatOverflow > 0 ? "warning" : ""}>重复预估 <strong>{formatNumber(repeatOverflow)}</strong></span>
        </div>
      </section>

      {mode === "advanced" && (
        <>
          <section className="workflow-step panel">
            <StepHeader number={3} title="附加素材结构" description="片头、插片、片尾和底栏不会计入主素材去重组合" />
            <AdvancedMaterials materials={materials} scan={scan} onUpdate={onUpdate} />
          </section>

          <section className="workflow-step panel">
            <StepHeader number={4} title="生成策略与命名" description="控制去重、临时文件和输出文件名" />
            <div className="workflow-two-columns align-start">
              <div className="workflow-option-stack">
                <Toggle label="同一条成片允许重复主素材" value={materials.allowRepeatInsideOneVideo} onChange={() => onUpdate({ allowRepeatInsideOneVideo: !materials.allowRepeatInsideOneVideo })} />
                <Toggle label="重复组合自动去重" value={materials.enableDedupWhenComboRepeated} onChange={() => onUpdate({ enableDedupWhenComboRepeated: !materials.enableDedupWhenComboRepeated })} />
                <Toggle label="完成后清理临时文件" value={materials.cleanupTemp} onChange={() => onUpdate({ cleanupTemp: !materials.cleanupTemp })} />
                <NumberField label="每段开头裁剪秒数" value={materials.trimStartSeconds} min={0} step={0.1} onChange={(trimStartSeconds) => onUpdate({ trimStartSeconds })} />
              </div>
              <NamingFields materials={materials} onUpdate={onUpdate} />
            </div>
          </section>

        </>
      )}

      <div className="workflow-bottom-spacer" />
      <div className="task-ready-bar">
        <div className="task-ready-main">
          <div className={`readiness-icon ${blockingIssues.length ? "warning" : "ready"}`}>
            {scanState.status === "scanning" ? <Activity size={18} className="spin" /> : blockingIssues.length ? <AlertTriangle size={18} /> : <CheckCircle2 size={18} />}
          </div>
          <div className="task-ready-copy">
            <strong>{blockingIssues.length ? blockingIssues[0] : `准备完成：将生成 ${materials.outputCount} 条视频`}</strong>
            <span>{submitError || `全局编码：${selectedEncoderLabel} · 输出：${materials.outputFolder || "素材目录 / output"}`}</span>
          </div>
        </div>
        <div className="task-ready-actions">
          {unfinished > 0 && <button className="btn btn-ghost" onClick={onOpenTasks}>队列中 {unfinished} 个</button>}
          <button className="btn btn-ghost" onClick={onOpenPerformance}>编码性能</button>
          {!authActive && <button className="btn btn-secondary" onClick={onOpenAuth}>登录会员</button>}
          <button className="btn btn-primary btn-lg" onClick={onStart} disabled={!canSubmit}>
            <Play size={16} />{submitting ? "正在提交..." : "加入任务队列"}
          </button>
        </div>
      </div>
    </div>
  );
}

function StepHeader({ number, title, description }: { number: number; title: string; description: string }) {
  return <div className="workflow-step-header"><span>{number}</span><div><h2>{title}</h2><p>{description}</p></div></div>;
}

function ScanFeedback({ state, scan }: { state: ScanViewState; scan: ScanSummary }) {
  if (state.status === "idle") return <div className="scan-feedback idle">选择素材文件夹后自动扫描</div>;
  if (state.status === "scanning") return <div className="scan-feedback scanning"><Activity size={15} className="spin" />正在扫描视频素材…</div>;
  if (state.status === "error") return <div className="scan-feedback error"><AlertTriangle size={15} />{state.message}</div>;
  return <div className="scan-feedback ready"><CheckCircle2 size={15} />扫描完成：主素材 {scan.mainCount} 个，片头 {scan.firstCount} 个，Top {scan.topCount} 个，片尾 {scan.tailCount} 个</div>;
}

function AdvancedMaterials({ materials, scan, onUpdate }: { materials: MaterialConfig; scan: ScanSummary; onUpdate: (patch: Partial<MaterialConfig>) => void }) {
  return (
    <div className="advanced-material-list">
      <AdvancedMaterialRow label="指定片头" hint={`已发现 ${scan.firstCount} 个`} value={materials.enableFirstVideo} onToggle={() => onUpdate({ enableFirstVideo: !materials.enableFirstVideo })}>
        <PathField label="片头文件夹" value={materials.firstVideoFolder} placeholder="默认可使用素材目录下的 1 文件夹" onChange={(firstVideoFolder) => onUpdate({ firstVideoFolder })} onPick={async () => { const path = await pickDirectory(); if (path) onUpdate({ firstVideoFolder: path }); }} />
      </AdvancedMaterialRow>
      <AdvancedMaterialRow label="Top 随机插片" hint={`素材目录 / top：${scan.topCount} 个`} value={materials.enableTopInsert} onToggle={() => onUpdate({ enableTopInsert: !materials.enableTopInsert })} />
      <AdvancedMaterialRow label="指定片尾" hint={`已发现 ${scan.tailCount} 个`} value={materials.enableTailVideo} onToggle={() => onUpdate({ enableTailVideo: !materials.enableTailVideo })}>
        <PathField label="片尾文件夹" value={materials.tailVideoFolder} placeholder="选择片尾视频文件夹" onChange={(tailVideoFolder) => onUpdate({ tailVideoFolder })} onPick={async () => { const path = await pickDirectory(); if (path) onUpdate({ tailVideoFolder: path }); }} />
      </AdvancedMaterialRow>
      <AdvancedMaterialRow label="底栏视频" hint={scan.bannerDetected ? "已识别底栏文件" : "尚未选择"} value={materials.enableBannerOverlay} onToggle={() => onUpdate({ enableBannerOverlay: !materials.enableBannerOverlay })}>
        <PathField label="底栏视频文件" value={materials.bannerFile} placeholder="选择覆盖到成片底部的视频" onChange={(bannerFile) => onUpdate({ bannerFile })} onPick={async () => { const path = await pickFile("video"); if (path) onUpdate({ bannerFile: path }); }} />
      </AdvancedMaterialRow>
    </div>
  );
}

function AdvancedMaterialRow({ label, hint, value, onToggle, children }: { label: string; hint: string; value: boolean; onToggle: () => void; children?: ReactNode }) {
  return <div className="advanced-material-row"><Toggle label={label} hint={hint} value={value} onChange={onToggle} />{value && children}</div>;
}

function NamingFields({ materials, onUpdate }: { materials: MaterialConfig; onUpdate: (patch: Partial<MaterialConfig>) => void }) {
  return (
    <div className="naming-card">
      <Toggle label="启用自定义命名" value={materials.enableAutoNaming} onChange={() => onUpdate({ enableAutoNaming: !materials.enableAutoNaming })} />
      {materials.enableAutoNaming && <>
        <div className="form-row"><TextField label="日期" value={materials.namingDate} onChange={(namingDate) => onUpdate({ namingDate })} /><TextField label="项目名" value={materials.namingPart1} onChange={(namingPart1) => onUpdate({ namingPart1 })} /></div>
        <div className="form-row"><TextField label="地区 / 渠道" value={materials.namingPart2} onChange={(namingPart2) => onUpdate({ namingPart2 })} /><TextField label="内容标签" value={materials.namingPart3} onChange={(namingPart3) => onUpdate({ namingPart3 })} /></div>
        <div className="form-row"><TextField label="自定义标签" value={materials.namingPart4} onChange={(namingPart4) => onUpdate({ namingPart4 })} /><NumberField label="序号位数" value={materials.namingSeqDigits} min={3} max={6} onChange={(namingSeqDigits) => onUpdate({ namingSeqDigits })} /></div>
        <div className="input-field"><label>重名处理</label><select value={materials.conflictStrategy} onChange={(event) => onUpdate({ conflictStrategy: event.target.value as MaterialConfig["conflictStrategy"] })}><option value="skip">跳过已有文件</option><option value="suffix">自动追加序号</option><option value="overwrite">覆盖原文件</option></select></div>
        <div className="naming-preview">{namingPreview(materials)}</div>
      </>}
    </div>
  );
}

function PathField({ label, value, placeholder, onChange, onPick }: { label: string; value: string; placeholder: string; onChange: (value: string) => void; onPick: () => void }) {
  return <div className="input-field"><label>{label}</label><div className="input-with-btn"><input value={value} onChange={(event) => onChange(event.target.value)} placeholder={placeholder} /><button className="btn btn-secondary btn-sm" onClick={onPick}><FolderOpen size={14} />选择</button></div></div>;
}

function NumberField({ label, value, min, max, step, onChange }: { label: string; value: number; min?: number; max?: number; step?: number; onChange: (value: number) => void }) {
  return <div className="input-field"><label>{label}</label><input type="number" value={value} min={min} max={max} step={step} onChange={(event) => onChange(Number(event.target.value) || 0)} /></div>;
}

function TextField({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  return <div className="input-field"><label>{label}</label><input value={value} onChange={(event) => onChange(event.target.value)} /></div>;
}

function Toggle({ label, hint, value, onChange }: { label: string; hint?: string; value: boolean; onChange: () => void }) {
  return <button type="button" className="workflow-toggle" aria-pressed={value} onClick={onChange}><span><strong>{label}</strong>{hint && <small>{hint}</small>}</span><span className={value ? "switch on" : "switch"} /></button>;
}

function getBlockingIssues(materials: MaterialConfig, scan: ScanSummary, scanState: ScanViewState, diagnosticsReady: boolean, diagnostics: Diagnostics): string[] {
  const issues: string[] = [];
  if (!materials.sourceFolder.trim()) issues.push("请先选择素材文件夹");
  else if (scanState.status === "scanning") issues.push("正在扫描素材，请稍候");
  else if (scanState.status === "error") issues.push(scanState.message || "素材扫描失败");
  else if (scan.mainCount <= 0) issues.push("素材目录中没有可用主视频");
  if (materials.segmentCount <= 0 || materials.outputCount <= 0) issues.push("素材数和生成数量必须大于 0");
  if (!materials.allowRepeatInsideOneVideo && scan.mainCount > 0 && materials.segmentCount > scan.mainCount) issues.push("每条素材数不能超过主素材数量");
  if (diagnosticsReady && !diagnostics.hasFfmpeg) issues.push("未找到 FFmpeg，请检查安装组件");
  return issues;
}

function namingPreview(materials: MaterialConfig): string {
  const parts = [materials.namingDate, materials.namingPart1 || "项目", materials.namingPart2, materials.namingPart3, materials.namingPart4]
    .map((part) => part.replace(/[<>:"/\\|?*\x00-\x1F]/g, "").trim())
    .filter(Boolean);
  parts.push("1".padStart(materials.namingSeqDigits, "0"));
  return `${parts.join("-")}.mp4`;
}
