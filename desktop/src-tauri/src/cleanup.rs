//! Keep Windows temporary-file deletion outside the WebView host process.
use std::ffi::OsStr;
use std::fs;
use std::path::Path;
use std::process::Command;
use std::sync::atomic::AtomicBool;
use std::time::Duration;

const HELPER_ARG: &str = "--video-mix-cleanup-temp";

pub fn run_helper_if_requested() -> Option<i32> {
    let mut args = std::env::args_os().skip(1);
    if args.next().as_deref() != Some(OsStr::new(HELPER_ARG)) {
        return None;
    }
    let Some(path) = args.next() else {
        return Some(2);
    };
    if args.next().is_some() {
        return Some(2);
    }
    let path = Path::new(&path);
    if let Err(error) = validate_temp_path(path)
        .and_then(|()| fs::remove_dir_all(path).map_err(|error| error.to_string()))
    {
        eprintln!("{error}");
        return Some(1);
    }
    Some(0)
}

pub fn remove_dir_all_isolated(path: &Path) -> Result<(), String> {
    let executable =
        std::env::current_exe().map_err(|error| format!("无法启动清理进程：{error}"))?;
    let mut command = Command::new(executable);
    command.arg(HELPER_ARG).arg(path);
    let result = crate::process::run(
        command,
        &AtomicBool::new(false),
        Some(Duration::from_secs(120)),
        |_| {},
    )?;
    if result.status.success() {
        Ok(())
    } else {
        let detail = result.stderr.trim();
        Err(if detail.is_empty() {
            "临时文件清理进程异常退出。".into()
        } else {
            format!("临时文件清理失败：{detail}")
        })
    }
}

fn validate_temp_path(path: &Path) -> Result<(), String> {
    let parent = path.parent().ok_or("无效的临时目录路径。")?;
    let is_root = path.file_name() == Some(OsStr::new("_temp_video_mix"));
    let is_job = parent.file_name() == Some(OsStr::new("_temp_video_mix"))
        && path
            .file_name()
            .and_then(OsStr::to_str)
            .is_some_and(|name| {
                let Some((index, millis)) = name.split_once('_') else {
                    return false;
                };
                index.len() == 4
                    && index.bytes().all(|c| c.is_ascii_digit())
                    && !millis.is_empty()
                    && millis.bytes().all(|c| c.is_ascii_digit())
            });
    if !is_root && !is_job {
        return Err("拒绝清理非混剪临时目录。".into());
    }
    if path
        .symlink_metadata()
        .map_err(|error| error.to_string())?
        .file_type()
        .is_symlink()
    {
        return Err("拒绝清理链接目录。".into());
    }
    let resolved = path.canonicalize().map_err(|error| error.to_string())?;
    let resolved_parent = parent.canonicalize().map_err(|error| error.to_string())?;
    if resolved.parent() != Some(resolved_parent.as_path()) {
        return Err("临时目录不在预期位置。".into());
    }
    if is_job && resolved_parent.file_name() != Some(OsStr::new("_temp_video_mix")) {
        return Err("临时目录不在混剪工作目录中。".into());
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn cleanup_only_accepts_mix_temp_directories() {
        let base =
            std::env::temp_dir().join(format!("video-mix-cleanup-test-{}", std::process::id()));
        let root = base.join("_temp_video_mix");
        let job = root.join("0001_123456789");
        fs::create_dir_all(&job).unwrap();
        fs::create_dir_all(base.join("other")).unwrap();
        assert!(validate_temp_path(&root).is_ok());
        assert!(validate_temp_path(&job).is_ok());
        assert!(validate_temp_path(&base).is_err());
        assert!(validate_temp_path(&base.join("other")).is_err());
        fs::remove_dir_all(base).unwrap();
    }
}
