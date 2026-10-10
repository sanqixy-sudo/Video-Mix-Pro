use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::sync::{Arc, Mutex, OnceLock};
use std::sync::atomic::AtomicBool;
use std::time::{Duration, SystemTime};

#[derive(Clone, Copy, Default)]
pub struct MediaInfo {
    pub has_audio: bool,
    pub duration: f64,
}

#[derive(Hash, PartialEq, Eq)]
struct Key { path: PathBuf, size: u64, modified: Option<SystemTime> }

#[derive(Default)]
pub struct ProbeCache {
    entries: Mutex<HashMap<Key, Arc<OnceLock<MediaInfo>>>>,
    #[cfg(test)]
    pub calls: std::sync::atomic::AtomicUsize,
}

impl ProbeCache {
    pub fn get(&self, ffprobe: &Path, video: &Path) -> MediaInfo {
        let Ok(meta) = video.metadata() else { return MediaInfo::default(); };
        let key = Key { path: video.to_path_buf(), size: meta.len(), modified: meta.modified().ok() };
        let entry = {
            let mut entries = self.entries.lock().unwrap_or_else(|error| error.into_inner());
            entries.entry(key).or_default().clone()
        };
        *entry.get_or_init(|| {
            #[cfg(test)]
            self.calls.fetch_add(1, std::sync::atomic::Ordering::SeqCst);
            probe(ffprobe, video)
        })
    }
}

fn probe(ffprobe: &Path, video: &Path) -> MediaInfo {
    let mut command = Command::new(ffprobe);
    command.args(["-v", "error", "-show_entries", "stream=codec_type:format=duration", "-of", "json"]).arg(video);
    let result = crate::process::run(command, &AtomicBool::new(false), Some(Duration::from_secs(10)), |_| {});
    let Ok(output) = result else { return MediaInfo::default(); };
    if !output.status.success() { return MediaInfo::default(); }
    let Ok(data) = serde_json::from_str::<serde_json::Value>(&output.stdout) else { return MediaInfo::default(); };
    MediaInfo {
        has_audio: data["streams"].as_array().is_some_and(|streams| streams.iter().any(|stream| stream["codec_type"] == "audio")),
        duration: data["format"]["duration"].as_str().and_then(|value| value.parse::<f64>().ok())
            .filter(|value| value.is_finite() && *value > 0.0).unwrap_or(0.0),
    }
}
