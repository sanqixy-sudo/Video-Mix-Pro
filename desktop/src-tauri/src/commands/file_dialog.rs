use tauri::Runtime;
use tauri_plugin_dialog::DialogExt;

fn apply_filters<R: Runtime>(mut builder: tauri_plugin_dialog::FileDialogBuilder<R>, kind: Option<String>) -> tauri_plugin_dialog::FileDialogBuilder<R> {
    match kind.as_deref().unwrap_or("any") {
        "image" => {
            builder = builder.add_filter("图片文件", &["png", "jpg", "jpeg", "webp", "bmp"]);
        }
        "video" => {
            builder = builder.add_filter("视频文件", &["mp4", "mov", "mkv", "avi", "webm", "m4v"]);
        }
        _ => {}
    }
    builder
}

#[tauri::command]
pub fn pick_directory(app: tauri::AppHandle) -> Result<Option<String>, String> {
    let path = app.dialog().file().blocking_pick_folder();
    Ok(path.map(|p| p.to_string()))
}

#[tauri::command]
pub fn pick_file(app: tauri::AppHandle, kind: Option<String>) -> Result<Option<String>, String> {
    let path = apply_filters(app.dialog().file(), kind).blocking_pick_file();
    Ok(path.map(|p| p.to_string()))
}

#[tauri::command]
pub fn pick_files(app: tauri::AppHandle, kind: Option<String>) -> Result<Vec<String>, String> {
    let paths = apply_filters(app.dialog().file(), kind).blocking_pick_files();
    Ok(paths.unwrap_or_default().into_iter().map(|p| p.to_string()).collect())
}

#[tauri::command]
pub fn open_directory(path: String) -> Result<(), String> {
    let directory = PathBuf::from(path.trim());
    if !directory.exists() || !directory.is_dir() {
        return Err("输出目录不存在或不可访问".to_string());
    }

    #[cfg(windows)]
    let mut command = Command::new("explorer.exe");
    #[cfg(target_os = "macos")]
    let mut command = Command::new("open");
    #[cfg(all(unix, not(target_os = "macos")))]
    let mut command = Command::new("xdg-open");

    command.arg(directory);
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x08000000);
    }
    command.spawn().map_err(|err| format!("无法打开输出目录：{err}"))?;
    Ok(())
}
use std::path::PathBuf;
use std::process::Command;
