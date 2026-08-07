import { AlertTriangle, CheckCircle2, Cpu } from "lucide-react";
import { getEncoderOptions, recommendedEncoder } from "../lib/performance";
import type { Diagnostics, PerformanceConfig } from "../types";

export function PerformancePage({
  config,
  diagnostics,
  diagnosticsReady,
  onUpdate,
}: {
  config: PerformanceConfig;
  diagnostics: Diagnostics;
  diagnosticsReady: boolean;
  onUpdate: (patch: Partial<PerformanceConfig>) => void;
}) {
  const options = getEncoderOptions(diagnostics);
  const recommended = recommendedEncoder(diagnostics);
  const recommendedOption = options.find((item) => item.key === recommended);
  const selected = options.find((item) => item.key === config.encoder);

  return (
    <div className="performance-page">
      <div className="workflow-title-row">
        <div>
          <h1 className="page-title">编码与性能</h1>
          <p className="page-subtitle">一处设置，全局应用到批量混剪、套外框、飘动水印和视频去重。</p>
        </div>
        <span className={`status-chip ${diagnosticsReady && diagnostics.hasFfmpeg ? "connected" : diagnosticsReady ? "failed" : "checking"}`}>
          {diagnosticsReady ? (diagnostics.hasFfmpeg ? "硬件检测完成" : "FFmpeg 未检测到") : "正在检测硬件"}
        </span>
      </div>

      <section className="panel performance-summary-card">
        <div className="performance-summary-icon"><Cpu size={24} /></div>
        <div>
          <strong>当前全局方案：{selected?.label || "CPU · libx264"}</strong>
          <span>{config.concurrencyMode === "auto" ? "自动并发" : config.concurrencyMode === "safe" ? "安全并发" : "手动并发"} · 上限 {config.workers} 路</span>
        </div>
        <div className={diagnosticsReady && diagnostics.hasFfmpeg ? "performance-ready" : "performance-warning"}>
          {diagnosticsReady && diagnostics.hasFfmpeg ? <CheckCircle2 size={16} /> : <AlertTriangle size={16} />}
          {diagnosticsReady && diagnostics.hasFfmpeg ? "可用于全部生成任务" : "请检查 FFmpeg 组件"}
        </div>
      </section>

      <section className="panel performance-settings-card">
        <div className="panel-header">
          <span className="panel-title">编码器</span>
          <span className="input-hint">不可用的硬件编码器已自动禁用</span>
        </div>
        <div className="encoder-recommendation">
          <div>
            <strong>系统推荐：{recommendedOption?.label}</strong>
            <span>同时检查显卡型号、FFmpeg 支持和实际编码能力</span>
          </div>
          {config.encoder !== recommended && <button className="btn btn-secondary btn-sm" onClick={() => onUpdate({ encoder: recommended })}>应用推荐</button>}
        </div>
        <div className="encoder-list performance-encoder-list">
          {options.map((item) => (
            <label key={item.key} className={`${config.encoder === item.key ? "encoder-option selected" : "encoder-option"}${item.available ? "" : " unavailable"}`}>
              <input type="radio" name="global-encoder" checked={config.encoder === item.key} disabled={!item.available} onChange={() => onUpdate({ encoder: item.key })} />
              <div className="encoder-option-info">
                <strong>{item.label}{item.recommended ? " · 推荐" : ""}</strong>
                <span>{item.available ? item.description : `${item.description}（当前设备不可用）`}</span>
              </div>
            </label>
          ))}
        </div>

        <div className="workflow-two-columns workflow-performance-controls">
          <div className="input-field">
            <label>并发模式</label>
            <select value={config.concurrencyMode} onChange={(event) => onUpdate({ concurrencyMode: event.target.value as PerformanceConfig["concurrencyMode"] })}>
              <option value="auto">自动推荐</option>
              <option value="safe">安全模式</option>
              <option value="manual">手动</option>
            </select>
            <span className="input-hint">自动模式会按当前 CPU / 显卡能力分配任务。</span>
          </div>
          <div className="input-field">
            <label>{config.concurrencyMode === "manual" ? "并发数量" : "并发上限"}</label>
            <input type="number" min={1} max={4} value={config.workers} onChange={(event) => onUpdate({ workers: Math.min(4, Math.max(1, Number(event.target.value) || 1)) })} />
            <span className="input-hint">全局统一为 1 - 4 路，避免多任务争抢显存或 CPU。</span>
          </div>
        </div>
      </section>

      <section className="panel performance-scope-card">
        <div className="panel-header"><span className="panel-title">应用范围</span></div>
        <div className="performance-scope-grid">
          {["批量混剪", "套外框", "飘动水印", "视频去重"].map((label) => <span key={label}><CheckCircle2 size={15} />{label}</span>)}
        </div>
      </section>
    </div>
  );
}
