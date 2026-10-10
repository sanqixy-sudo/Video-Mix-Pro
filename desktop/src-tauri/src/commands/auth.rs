use std::fs;
use std::path::PathBuf;
use std::sync::{Mutex, OnceLock};
use std::time::Duration;
use std::io::Read;

use serde::{Deserialize, Serialize};

pub const SERVER_URL: &str = "https://videomix.7cloudvps.com";
static SESSION_IO: Mutex<()> = Mutex::new(());
static CLIENT: OnceLock<Result<reqwest::blocking::Client, String>> = OnceLock::new();

#[derive(Clone, PartialEq, Eq)]
pub struct Credentials {
    server_url: String,
    token: String,
    device_id: String,
}

fn credentials(auth: AuthState) -> Result<Credentials, String> {
    let base = auth.server_url.trim().trim_end_matches('/');
    if base != SERVER_URL {
        return Err("会员服务器地址不受信任，请恢复官方服务器后重新登录。".into());
    }
    if auth.token.is_empty() || auth.device_id.is_empty() {
        return Err("请先登录会员账号。".into());
    }
    Ok(Credentials { server_url: base.into(), token: auth.token, device_id: auth.device_id })
}

#[derive(Deserialize)]
struct Membership {
    active: bool,
    device_id: String,
    plan: String,
    expires_at: Option<String>,
    session_expires_at: Option<String>,
}

fn future(value: Option<&str>) -> bool {
    value.and_then(|value| chrono::DateTime::parse_from_rfc3339(value).ok())
        .is_some_and(|expiry| expiry > chrono::Utc::now())
}

fn validate_membership(data: &Membership, auth: &Credentials) -> Result<(), String> {
    if !data.active || data.device_id != auth.device_id {
        return Err("会员无效或设备不匹配，请刷新会员状态。".into());
    }
    if !future(data.session_expires_at.as_deref()) {
        return Err("登录已过期，请重新登录。".into());
    }
    if data.plan != "permanent" && !future(data.expires_at.as_deref()) {
        return Err("会员已过期或未开通。".into());
    }
    Ok(())
}

fn verify_remote(client: &reqwest::blocking::Client, endpoint: &str, auth: &Credentials) -> Result<(), String> {
    let response = client.post(format!("{endpoint}/api/auth/verify"))
        .json(&serde_json::json!({
            "token": auth.token, "device_id": auth.device_id,
            "app_version": env!("CARGO_PKG_VERSION"),
        }))
        .send().map_err(|_| "无法验证会员，请检查网络后重试；任务尚未开始。".to_owned())?;
    let status = response.status();
    if !status.is_success() {
        return Err(match status.as_u16() {
            401 => "登录已失效，请重新登录。",
            403 => "会员无效、账号受限或设备已变更，请刷新会员状态。",
            426 => "此版本已停止支持，请升级客户端。",
            429 => "会员验证过于频繁，请稍后重试。",
            _ => "会员服务器暂时不可用，请稍后重试。",
        }.into());
    }
    let mut bytes = Vec::new();
    response.take(16 * 1024 + 1).read_to_end(&mut bytes)
        .map_err(|_| "会员验证响应读取失败。".to_owned())?;
    if bytes.len() > 16 * 1024 { return Err("会员验证响应异常。".into()); }
    let data: Membership = serde_json::from_slice(&bytes).map_err(|_| "会员验证响应异常。".to_owned())?;
    validate_membership(&data, auth)
}

pub fn require_membership() -> Result<Credentials, String> {
    let auth = credentials(load_auth_state()?)?;
    revalidate_membership(&auth)?;
    Ok(auth)
}

/// Recheck at dispatch as membership/session/device may change while queued.
pub fn revalidate_membership(auth: &Credentials) -> Result<(), String> {
    if credentials(load_auth_state()?)? != *auth {
        return Err("登录账号已变更，请用当前账号重新提交任务。".into());
    }
    let client = CLIENT.get_or_init(|| reqwest::blocking::Client::builder()
        .timeout(Duration::from_secs(8))
        .connect_timeout(Duration::from_secs(4))
        .redirect(reqwest::redirect::Policy::none())
        .build().map_err(|_| "无法初始化会员验证连接。".to_owned()));
    verify_remote(client.as_ref().map_err(Clone::clone)?, SERVER_URL, auth)?;
    if credentials(load_auth_state()?)? != *auth {
        return Err("验证期间登录状态已变更，请重新提交任务。".into());
    }
    Ok(())
}

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
    let _lock = SESSION_IO.lock().map_err(|_| "登录状态不可用".to_owned())?;
    let path = auth_file_path()?;
    if !path.exists() {
        return Ok(AuthState::default());
    }
    let data = fs::read_to_string(path).map_err(|err| err.to_string())?;
    serde_json::from_str(&data).map_err(|err| err.to_string())
}

#[tauri::command]
pub fn save_auth_state(auth: AuthState) -> Result<(), String> {
    let _lock = SESSION_IO.lock().map_err(|_| "登录状态不可用".to_owned())?;
    let path = auth_file_path()?;
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|err| err.to_string())?;
    }
    let data = serde_json::to_string_pretty(&auth).map_err(|err| err.to_string())?;
    fs::write(path, data).map_err(|err| err.to_string())
}

fn auth_file_path() -> Result<PathBuf, String> {
    if let Some(base) = crate::portable::data_dir() {
        return Ok(base.join("account").join("session.json"));
    }
    let base = dirs::document_dir()
        .or_else(dirs::home_dir)
        .ok_or_else(|| "无法定位用户文档目录".to_string())?;
    Ok(base.join("VideoMixPro").join("account").join("session.json"))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::{Read, Write};
    use std::net::TcpListener;
    fn auth() -> Credentials {
        credentials(AuthState { server_url: SERVER_URL.into(), token: "test-token".into(), device_id: "test-device".into(), ..Default::default() }).unwrap()
    }
    fn payload() -> serde_json::Value {
        serde_json::json!({"active":true,"device_id":"test-device","plan":"month","expires_at":"2099-01-01T00:00:00Z","session_expires_at":"2099-01-01T00:00:00Z"})
    }
    fn validate(value: serde_json::Value) -> bool {
        serde_json::from_value::<Membership>(value).ok().is_some_and(|data| validate_membership(&data, &auth()).is_ok())
    }
    #[test]
    fn local_active_flag_is_not_authorization() {
        assert!(credentials(AuthState { server_url: SERVER_URL.into(), active: true, plan: "permanent".into(), ..Default::default() }).is_err());
    }
    #[test]
    fn rejects_fake_servers_before_sending_credentials() {
        for base in ["http://videomix.7cloudvps.com", "https://videomix.7cloudvps.com.evil.test", "https://videomix.7cloudvps.com@evil.test", "http://127.0.0.1:8000", "https://videomix.7cloudvps.com/path"] {
            assert!(credentials(AuthState { server_url:base.into(),token:"test".into(),device_id:"test".into(),..Default::default() }).is_err());
        }
    }
    #[test]
    fn validates_membership_expiry_device_and_session() {
        assert!(validate(payload()));
        for (key,value) in [("active",serde_json::json!(false)),("device_id",serde_json::json!("other")),("expires_at",serde_json::json!("2000-01-01T00:00:00Z")),("session_expires_at",serde_json::json!("2000-01-01T00:00:00Z")),("expires_at",serde_json::Value::Null)] {
            let mut data=payload(); data[key]=value; assert!(!validate(data), "{key}");
        }
        let mut permanent=payload(); permanent["plan"]=serde_json::json!("permanent"); permanent["expires_at"]=serde_json::Value::Null;
        assert!(validate(permanent.clone()));
        permanent["session_expires_at"]=serde_json::Value::Null;
        assert!(!validate(permanent));
        assert!(!validate(serde_json::json!({"active":true})));
    }
    fn server(status: u16, body: String, delay: Duration) -> (String, std::thread::JoinHandle<()>) {
        let listener=TcpListener::bind("127.0.0.1:0").unwrap();
        let url=format!("http://{}",listener.local_addr().unwrap());
        let handle=std::thread::spawn(move || {
            let (mut stream,_)=listener.accept().unwrap();
            stream.set_read_timeout(Some(Duration::from_secs(2))).unwrap();
            let mut request=Vec::new();
            let mut buffer=[0u8;1024];
            loop {
                let n=stream.read(&mut buffer).unwrap(); if n==0 { break; } request.extend_from_slice(&buffer[..n]);
                if let Some(end)=request.windows(4).position(|w| w==b"\r\n\r\n") {
                    let headers=String::from_utf8_lossy(&request[..end]).to_lowercase();
                    let size=headers.lines().find_map(|line| line.strip_prefix("content-length:")).unwrap().trim().parse::<usize>().unwrap();
                    if request.len()>=end+4+size {
                        let sent:serde_json::Value=serde_json::from_slice(&request[end+4..]).unwrap();
                        assert_eq!(sent["device_id"],"test-device");
                        assert_eq!(sent["app_version"],env!("CARGO_PKG_VERSION"));
                        break;
                    }
                }
            }
            std::thread::sleep(delay);
            let _=write!(stream,"HTTP/1.1 {status} Response\r\nContent-Type: application/json\r\nContent-Length: {}\r\nLocation: http://127.0.0.1:1/\r\nConnection: close\r\n\r\n{body}",body.len());
        });
        (url,handle)
    }
    #[test]
    fn remote_verification_accepts_only_valid_success_responses() {
        let client=reqwest::blocking::Client::builder().no_proxy().redirect(reqwest::redirect::Policy::none()).timeout(Duration::from_secs(2)).build().unwrap();
        for status in [200,401,403,426,429,500,302] {
            let (endpoint,handle)=server(status,payload().to_string(),Duration::ZERO);
            assert_eq!(verify_remote(&client,&endpoint,&auth()).is_ok(),status==200);
            handle.join().unwrap();
        }
        for body in ["not-json".to_owned(),"{\"active\":true}".to_owned(),"x".repeat(17000)] {
            let (endpoint,handle)=server(200,body,Duration::ZERO);
            assert!(verify_remote(&client,&endpoint,&auth()).is_err());handle.join().unwrap();
        }
    }
    #[test]
    fn network_timeout_fails_closed() {
        let client=reqwest::blocking::Client::builder().no_proxy().timeout(Duration::from_millis(100)).build().unwrap();
        let (endpoint,handle)=server(200,payload().to_string(),Duration::from_millis(300));
        assert!(verify_remote(&client,&endpoint,&auth()).is_err());handle.join().unwrap();
    }
    #[test]
    #[ignore = "read-only live HTTPS diagnostic"]
    fn official_https_health() {
        let client=reqwest::blocking::Client::builder().timeout(Duration::from_secs(8)).build().unwrap();
        let result=client.get(format!("{SERVER_URL}/api/health")).send();
        match result {
            Ok(response) => assert!(response.status().is_success(), "HTTP {}", response.status()),
            Err(error) => panic!("HTTPS diagnostic: {error:?}"),
        }
    }
}
