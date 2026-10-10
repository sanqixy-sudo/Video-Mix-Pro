use std::path::PathBuf;

fn executable_dir() -> Option<PathBuf> {
    std::env::current_exe().ok()?.parent().map(|path| path.to_path_buf())
}

/// Portable distributions carry this marker; installed copies keep their existing profile.
pub fn data_dir() -> Option<PathBuf> {
    let directory = executable_dir()?;
    directory.join("portable.flag").is_file().then(|| directory.join("data"))
}

/// Run before Tauri starts threads or creates its WebView2 environment.
pub fn prepare() {
    if let Some(data) = data_dir() {
        if std::env::var_os("WEBVIEW2_USER_DATA_FOLDER").is_none() {
            std::env::set_var("WEBVIEW2_USER_DATA_FOLDER", data.join("webview2"));
        }
    }

    #[cfg(windows)]
    if let Some(runtime) = executable_dir().map(|directory| directory.join("WebView2")) {
        if runtime.join("msedgewebview2.exe").is_file() {
            // Fixed WebView2 v120+ requires sandbox read/execute access on Windows 10.
            // Touch only this bundled runtime; repeat to handle newly extracted copies.
            use std::os::windows::process::CommandExt;
            let windows = std::env::var_os("SystemRoot").map(PathBuf::from)
                .unwrap_or_else(|| PathBuf::from(r"C:\Windows"));
            for identity in ["*S-1-15-2-2:(OI)(CI)(RX)", "*S-1-15-2-1:(OI)(CI)(RX)"] {
                let result = std::process::Command::new(windows.join("System32").join("icacls.exe"))
                    .arg(&runtime).args(["/grant", identity, "/q"])
                    .creation_flags(0x08000000).output();
                if let Ok(output) = result {
                    if !output.status.success() {
                        eprintln!("WebView2 sandbox permissions could not be updated.");
                    }
                }
            }
            std::env::set_var("WEBVIEW2_BROWSER_EXECUTABLE_FOLDER", runtime);
        }
    }
}
