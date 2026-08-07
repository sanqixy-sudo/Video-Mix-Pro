use std::fs;
use std::path::PathBuf;

use serde::{Deserialize, Serialize};

#[derive(Debug, Serialize, Deserialize, Default)]
#[serde(default, rename_all = "camelCase")]
pub struct AuthState {
    pub server_url: String,
    pub username: String,
    pub token: String,
    pub active: bool,
    pub plan: String,
    pub plan_label: String,
    pub expires_at: String,
    pub session_expires_at: String,
    pub device_id: String,
}

#[tauri::command]
pub fn load_auth_state() -> Result<AuthState, String> {
    let path = auth_file_path()?;
    if !path.exists() {
        return Ok(AuthState::default());
    }
    let data = fs::read_to_string(path).map_err(|err| err.to_string())?;
    serde_json::from_str(&data).map_err(|err| err.to_string())
}

#[tauri::command]
pub fn save_auth_state(auth: AuthState) -> Result<(), String> {
    let path = auth_file_path()?;
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|err| err.to_string())?;
    }
    let data = serde_json::to_string_pretty(&auth).map_err(|err| err.to_string())?;
    fs::write(path, data).map_err(|err| err.to_string())
}

fn auth_file_path() -> Result<PathBuf, String> {
    let base = dirs::document_dir()
        .or_else(dirs::home_dir)
        .ok_or_else(|| "无法定位用户文档目录".to_string())?;
    Ok(base.join("VideoMixPro").join("account").join("session.json"))
}
