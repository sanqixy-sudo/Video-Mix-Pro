import type { Diagnostics, EncoderKey } from "../types";

export interface EncoderOption {
  key: EncoderKey;
  label: string;
  description: string;
  available: boolean;
  recommended: boolean;
}

export function recommendedEncoder(diagnostics: Diagnostics): EncoderKey {
  if (diagnostics.hasNvenc) return "nvidia_nvenc";
  if (diagnostics.hasQsv) return "intel_qsv";
  if (diagnostics.hasAmf) return "amd_amf";
  return "cpu_libx264";
}

export function getEncoderOptions(diagnostics: Diagnostics): EncoderOption[] {
  const recommended = recommendedEncoder(diagnostics);
  return [
    { key: "cpu_libx264", label: "CPU · libx264", description: "兼容性最好，所有电脑都可用", available: true, recommended: recommended === "cpu_libx264" },
    { key: "nvidia_nvenc", label: "NVIDIA · NVENC", description: "NVIDIA 显卡硬件编码", available: diagnostics.hasNvenc, recommended: recommended === "nvidia_nvenc" },
    { key: "intel_qsv", label: "Intel · QSV", description: "Intel 核显硬件编码", available: diagnostics.hasQsv, recommended: recommended === "intel_qsv" },
    { key: "amd_amf", label: "AMD · AMF", description: "AMD 显卡硬件编码", available: diagnostics.hasAmf, recommended: recommended === "amd_amf" },
    { key: "mixed_nvidia", label: "CPU + NVIDIA", description: "CPU 与 NVENC 混合并发", available: diagnostics.hasNvenc, recommended: false },
    { key: "mixed_intel", label: "CPU + Intel", description: "CPU 与 QSV 混合并发", available: diagnostics.hasQsv, recommended: false },
    { key: "mixed_amd", label: "CPU + AMD", description: "CPU 与 AMF 混合并发", available: diagnostics.hasAmf, recommended: false },
  ];
}

export function encoderLabel(encoder: string): string {
  const labels: Record<string, string> = {
    cpu_libx264: "CPU · libx264",
    nvidia_nvenc: "NVIDIA · NVENC",
    nvenc_h264: "NVIDIA · NVENC",
    intel_qsv: "Intel · QSV",
    qsv_h264: "Intel · QSV",
    amd_amf: "AMD · AMF",
    amf_h264: "AMD · AMF",
    mixed_nvidia: "CPU + NVIDIA",
    mixed_intel: "CPU + Intel",
    mixed_amd: "CPU + AMD",
  };
  return labels[encoder] || "CPU · libx264";
}
