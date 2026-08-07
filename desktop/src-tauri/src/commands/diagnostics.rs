use std::path::PathBuf;
use std::process::{Command, Stdio};

use serde::Serialize;
use tauri::Manager;

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Diagnostics {
    pub ffmpeg_path: String,
    pub ffprobe_path: String,
    pub has_ffmpeg: bool,
    pub has_ffprobe: bool,
    pub has_qsv: bool,
    pub has_scale_qsv: bool,
    pub has_vpp_qsv: bool,
    pub has_nvenc: bool,
    pub has_amf: bool,
    pub recommended_workers: u8,
}

#[tauri::command]
pub fn get_diagnostics(app: tauri::AppHandle) -> Result<Diagnostics, String> {
    let ffmpeg = find_sidecar_or_path(&app, "ffmpeg.exe").or_else(|| find_sidecar_or_path(&app, "ffmpeg"));
    let ffprobe = find_sidecar_or_path(&app, "ffprobe.exe").or_else(|| find_sidecar_or_path(&app, "ffprobe"));

    let encoder_text = ffmpeg
        .as_ref()
        .and_then(|path| command_output(path, &["-hide_banner", "-encoders"]))
        .unwrap_or_default();
    let filter_text = ffmpeg
        .as_ref()
        .and_then(|path| command_output(path, &["-hide_banner", "-filters"]))
        .unwrap_or_default();

    let gpu_names = detected_gpu_names();
    let gpu_names_lower = gpu_names.to_ascii_lowercase();
    let has_nvidia_gpu = gpu_names_lower.contains("nvidia");
    let has_intel_gpu = gpu_names_lower.contains("intel");
    let has_amd_gpu = gpu_names_lower.contains("amd") || gpu_names_lower.contains("radeon");

    // FFmpeg 列出编码器只代表“编译时带了该模块”，不代表当前电脑真有对应显卡。
    // 推荐前同时检查显卡型号并实际编码一帧，避免无 NVIDIA 显卡时误推 NVENC。
    let has_qsv = has_intel_gpu
        && encoder_text.contains("h264_qsv")
        && ffmpeg.as_ref().map(|path| encoder_works(path, "h264_qsv")).unwrap_or(false);
    let has_nvenc = has_nvidia_gpu
        && encoder_text.contains("h264_nvenc")
        && ffmpeg.as_ref().map(|path| encoder_works(path, "h264_nvenc")).unwrap_or(false);
    let has_amf = has_amd_gpu
        && encoder_text.contains("h264_amf")
        && ffmpeg.as_ref().map(|path| encoder_works(path, "h264_amf")).unwrap_or(false);
    let has_scale_qsv = has_qsv && filter_text.contains("scale_qsv");
    let has_vpp_qsv = has_qsv && filter_text.contains("vpp_qsv");

    Ok(Diagnostics {
        ffmpeg_path: ffmpeg.as_ref().map(|p| p.to_string_lossy().to_string()).unwrap_or_default(),
        ffprobe_path: ffprobe.as_ref().map(|p| p.to_string_lossy().to_string()).unwrap_or_default(),
        has_ffmpeg: ffmpeg.is_some(),
        has_ffprobe: ffprobe.is_some(),
        has_qsv,
        has_scale_qsv,
        has_vpp_qsv,
        has_nvenc,
        has_amf,
        recommended_workers: if has_qsv || has_nvenc || has_amf { 2 } else { 1 },
    })
}

fn find_sidecar_or_path(app: &tauri::AppHandle, name: &str) -> Option<PathBuf> {
    let mut candidates = Vec::new();
    if let Ok(resource_dir) = app.path().resource_dir() {
        candidates.push(resource_dir.join("bin").join(name));
        candidates.push(resource_dir.join(name));
    }
    if let Ok(current) = std::env::current_exe() {
        if let Some(parent) = current.parent() {
            candidates.push(parent.join("bin").join(name));
            candidates.push(parent.join(name));
        }
    }

    candidates.into_iter().find(|path| path.exists() && path.is_file()).or_else(|| which_on_path(name))
}

fn which_on_path(name: &str) -> Option<PathBuf> {
    let path_var = std::env::var_os("PATH")?;
    std::env::split_paths(&path_var)
        .map(|folder| folder.join(name))
        .find(|candidate| candidate.exists() && candidate.is_file())
}

fn command_output(path: &PathBuf, args: &[&str]) -> Option<String> {
    let mut command = Command::new(path);
    command.args(args);
    hide_command_window(&mut command);
    let output = command.output().ok()?;
    let mut text = String::new();
    text.push_str(&String::from_utf8_lossy(&output.stdout));
    text.push_str(&String::from_utf8_lossy(&output.stderr));
    Some(text)
}

fn detected_gpu_names() -> String {
    #[cfg(windows)]
    {
        let mut command = Command::new("powershell.exe");
        command.args([
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            "(Get-CimInstance Win32_VideoController -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Name) -join [Environment]::NewLine",
        ]);
        hide_command_window(&mut command);
        return command
            .output()
            .ok()
            .filter(|output| output.status.success())
            .map(|output| String::from_utf8_lossy(&output.stdout).to_string())
            .unwrap_or_default();
    }

    #[cfg(not(windows))]
    {
        String::new()
    }
}

fn encoder_works(ffmpeg: &PathBuf, encoder: &str) -> bool {
    let mut command = Command::new(ffmpeg);
    command.args([
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        "color=c=black:s=64x64:d=0.04",
        "-frames:v",
        "1",
        "-an",
        "-c:v",
        encoder,
        "-f",
        "null",
        "-",
    ]);
    command.stdout(Stdio::null()).stderr(Stdio::null());
    hide_command_window(&mut command);
    command.status().map(|status| status.success()).unwrap_or(false)
}

fn hide_command_window(command: &mut Command) {
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x08000000);
    }
}
