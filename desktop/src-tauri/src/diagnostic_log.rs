use std::fs::{self, OpenOptions};
use std::io::Write;
use std::path::PathBuf;
use std::sync::{Mutex, OnceLock};
use std::time::{SystemTime, UNIX_EPOCH};

static LOG_PATH: OnceLock<Mutex<PathBuf>> = OnceLock::new();
const MAX_LOG_BYTES: u64 = 1024 * 1024;

pub fn init(directory: Option<PathBuf>) {
    if let Some(directory) = directory {
        if fs::create_dir_all(&directory).is_ok() {
            let _ = LOG_PATH.set(Mutex::new(directory.join("desktop.log")));
        }
    }
    let previous = std::panic::take_hook();
    std::panic::set_hook(Box::new(move |info| {
        event(&format!("panic: {info}"));
        previous(info);
    }));
    event(&format!("application started, version {}", env!("CARGO_PKG_VERSION")));
}

pub fn event(message: &str) {
    let Some(path) = LOG_PATH.get() else { return; };
    let Ok(path) = path.lock() else { return; };
    if fs::metadata(&*path).is_ok_and(|metadata| metadata.len() > MAX_LOG_BYTES) {
        let _ = fs::remove_file(&*path);
    }
    let Ok(mut file) = OpenOptions::new().create(true).append(true).open(&*path) else { return; };
    let timestamp = SystemTime::now().duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_secs()).unwrap_or(0);
    let _ = writeln!(file, "{timestamp} {message}");
}
