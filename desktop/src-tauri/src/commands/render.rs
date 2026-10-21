use std::fs;
use std::collections::{HashMap, VecDeque};
use std::path::{Path, PathBuf};
use std::process::Command;
use std::sync::{Arc, Mutex};
use std::sync::atomic::{AtomicBool, AtomicU32, Ordering};
use std::thread;
use std::time::{SystemTime, UNIX_EPOCH};

use serde::{Deserialize, Serialize};
use tauri::Manager;

#[cfg(test)]
#[path = "render_tests.rs"]
mod tests;

const VIDEO_EXTS: &[&str] = &["mp4", "mov", "mkv", "avi", "webm", "m4v", "flv", "wmv", "ts"];
const IMAGE_EXTS: &[&str] = &["png", "jpg", "jpeg", "webp", "bmp"];
static QUEUE_SEQUENCE: AtomicU32 = AtomicU32::new(1);
const BANNER_KEYWORDS: &[&str] = &[
    "banner", "overlay", "adbar", "ad_bar", "install_banner", "hengfu", "横幅", "安装条",
    "底部条", "bottom", "bottom_bar", "bottombar", "footer", "footer_bar", "底栏", "底部", "广告条",
];

#[derive(Clone, Default)]
pub struct RenderState {
    inner: Arc<Mutex<RenderTaskStatus>>,
    cancel: Arc<AtomicBool>,
    queue: Arc<Mutex<QueueRuntime>>,
    queue_items: Arc<Mutex<Vec<QueueTaskStatus>>>,
    task_archive: Arc<Mutex<HashMap<String, QueuedTaskPlan>>>,
}

#[derive(Default)]
struct QueueRuntime {
    active: bool,
    pending: VecDeque<QueuedTask>,
}

struct QueuedTask {
    id: String,
    plan: QueuedTaskPlan,
    item: QueueTaskStatus,
    authorization: Option<super::auth::Credentials>,
}

#[derive(Clone)]
enum QueuedTaskPlan {
    Render(RenderPlan),
    Overlay(OverlayPlan),
    Watermark(WatermarkPlan),
    Dedup(DedupPlan),
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct QueueTaskStatus {
    pub id: String,
    pub name: String,
    pub task_kind: String,
    pub status: String,
    pub progress: u8,
    pub completed: u32,
    pub failed: u32,
    pub total: u32,
    pub output_folder: String,
    pub created_at: u64,
    pub is_retry: bool,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct RenderTaskStatus {
    pub running: bool,
    pub cancelled: bool,
    pub status: String,
    pub progress: u8,
    #[serde(skip)]
    in_flight: HashMap<u32, f64>,
    pub completed: u32,
    pub failed: u32,
    pub total: u32,
    pub output_folder: String,
    pub task_kind: String,
    pub logs: Vec<String>,
    pub current_task_id: String,
    pub pending_count: u32,
    pub queue: Vec<QueueTaskStatus>,
}

impl Default for RenderTaskStatus {
    fn default() -> Self {
        Self {
            in_flight: HashMap::new(),
            running: false,
            cancelled: false,
            status: "就绪".to_string(),
            progress: 0,
            completed: 0,
            failed: 0,
            total: 0,
            output_folder: String::new(),
            task_kind: String::new(),
            logs: vec!["等待任务开始...".to_string()],
            current_task_id: String::new(),
            pending_count: 0,
            queue: Vec::new(),
        }
    }
}

#[derive(Debug, Deserialize, Clone)]
#[serde(rename_all = "camelCase")]
pub struct RenderConfig {
    pub source_folder: String,
    pub output_folder: String,
    #[serde(default)]
    pub orientation: OutputOrientation,
    pub segment_count: u32,
    pub output_count: u32,
    pub trim_start_seconds: f64,
    pub enable_first_video: bool,
    pub first_video_folder: String,
    pub enable_top_insert: bool,
    pub enable_tail_video: bool,
    pub tail_video_folder: String,
    pub enable_banner_overlay: bool,
    pub banner_file: String,
    pub allow_repeat_inside_one_video: bool,
    pub enable_dedup_when_combo_repeated: bool,
    pub keep_audio: bool,
    pub cleanup_temp: bool,
    pub encoder: String,
    pub workers: u32,
    pub concurrency_mode: String,
    pub enable_auto_naming: bool,
    pub naming_use_source_name: bool,
    pub naming_date: String,
    pub naming_part1: String,
    pub naming_part2: String,
    pub naming_part3: String,
    pub naming_part4: String,
    pub naming_seq_digits: u32,
    #[serde(rename = "conflictStrategy")]
    pub conflict_strategy: String,
}

#[derive(Debug, Deserialize, Clone)]
#[serde(rename_all = "camelCase")]
pub struct OverlayConfig {
    pub frame_file: String,
    pub video_files: Vec<String>,
    pub output_folder: String,
    #[serde(default)]
    pub orientation: OutputOrientation,
    pub x: i32,
    pub y: i32,
    pub width: u32,
    pub height: u32,
    pub mode: String,
    pub fps: u32,
    pub crf: u8,
    pub preset: String,
    pub keep_audio: bool,
    pub encoder: String,
    pub workers: u32,
    pub concurrency_mode: String,
    pub enable_auto_naming: bool,
    pub naming_use_source_name: bool,
    pub naming_date: String,
    pub naming_part1: String,
    pub naming_part2: String,
    pub naming_part3: String,
    pub naming_part4: String,
    pub naming_seq_digits: u32,
    #[serde(rename = "conflictStrategy")]
    pub conflict_strategy: String,
}

#[derive(Clone, Copy, Debug, Default, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub enum OutputOrientation {
    #[default]
    Portrait,
    Landscape,
}

impl OutputOrientation {
    fn dimensions(self) -> (i32, i32) {
        match self {
            Self::Portrait => (1080, 1920),
            Self::Landscape => (1920, 1080),
        }
    }
}

#[derive(Debug, Deserialize, Clone)]
#[serde(rename_all = "camelCase")]
pub struct WatermarkConfig {
    pub source_folder: String,
    pub logo_file: String,
    pub output_folder: String,
    pub width_percent: f64,
    pub speed: f64,
    pub opacity: f64,
    pub keep_audio: bool,
    pub encoder: String,
    pub workers: u32,
    pub concurrency_mode: String,
    #[serde(rename = "conflictStrategy")]
    pub conflict_strategy: String,
}

#[derive(Debug, Deserialize, Clone)]
#[serde(rename_all = "camelCase")]
pub struct DedupConfig {
    pub source_folder: String,
    pub output_folder: String,
    pub random_bitrate: bool,
    pub drop_frames: bool,
    pub micro_speed: bool,
    pub subtle_filter: bool,
    pub keep_audio: bool,
    pub encoder: String,
    pub workers: u32,
    pub concurrency_mode: String,
    #[serde(rename = "conflictStrategy")]
    pub conflict_strategy: String,
}

#[derive(Clone)]
struct RenderJob {
    index: u32,
    combo: Vec<PathBuf>,
    is_repeat: bool,
    repeat_index: u128,
    output_path: PathBuf,
    actual_output_name: String,
    job_dir: PathBuf,
    encoder: EncoderKind,
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum EncoderKind {
    Cpu,
    Nvidia,
    Intel,
    Amd,
}

impl EncoderKind {
    fn label(self) -> &'static str {
        match self {
            EncoderKind::Cpu => "CPU - libx264",
            EncoderKind::Nvidia => "NVIDIA GPU - h264_nvenc",
            EncoderKind::Intel => "Intel 核显 - h264_qsv",
            EncoderKind::Amd => "AMD GPU - h264_amf",
        }
    }
}

#[derive(Clone)]
struct RenderPlan {
    config: RenderConfig,
    source: PathBuf,
    output: PathBuf,
    ffmpeg: PathBuf,
    ffprobe: Option<PathBuf>,
    probes: Arc<crate::media::ProbeCache>,
    videos: Vec<PathBuf>,
    first_videos: Vec<PathBuf>,
    top_videos: Vec<PathBuf>,
    tail_videos: Vec<PathBuf>,
    banner: Option<PathBuf>,
}

#[derive(Clone)]
struct OverlayPlan {
    config: OverlayConfig,
    frame: PathBuf,
    videos: Vec<PathBuf>,
    output: PathBuf,
    ffmpeg: PathBuf,
    ffprobe: Option<PathBuf>,
    probes: Arc<crate::media::ProbeCache>,
}

#[derive(Clone)]
struct WatermarkPlan {
    config: WatermarkConfig,
    source: PathBuf,
    logo: PathBuf,
    videos: Vec<PathBuf>,
    output: PathBuf,
    ffmpeg: PathBuf,
    ffprobe: Option<PathBuf>,
    probes: Arc<crate::media::ProbeCache>,
}

#[derive(Clone)]
struct DedupPlan {
    config: DedupConfig,
    source: PathBuf,
    videos: Vec<PathBuf>,
    output: PathBuf,
    ffmpeg: PathBuf,
    ffprobe: Option<PathBuf>,
    probes: Arc<crate::media::ProbeCache>,
}

#[derive(Clone)]
struct Variant {
    is_dedup: bool,
    speed: f64,
    fps: &'static str,
    bitrate: Option<String>,
    crf: Option<u8>,
    audio_rate: u32,
    note: String,
}

impl Variant {
    fn normal() -> Self {
        Self {
            is_dedup: false,
            speed: 1.0,
            fps: "30",
            bitrate: None,
            crf: Some(23),
            audio_rate: 44100,
            note: "正常".to_string(),
        }
    }

    fn dedup(seed: u32) -> Self {
        let speeds = [0.980, 0.985, 0.990, 0.995, 1.005, 1.010, 1.015, 1.020];
        let fps_values = ["24", "25", "29.97", "30"];
        let audio_rates = [44100, 48000];
        let speed = speeds[(seed as usize * 3 + 1) % speeds.len()];
        let fps = fps_values[(seed as usize * 5 + 2) % fps_values.len()];
        let bitrate_num = 2500 + ((seed as usize * 317) % 2101);
        let bitrate = format!("{bitrate_num}k");
        let audio_rate = audio_rates[seed as usize % audio_rates.len()];
        Self {
            is_dedup: true,
            speed,
            fps,
            bitrate: Some(bitrate.clone()),
            crf: None,
            audio_rate,
            note: format!("去重：速度 {speed:.3}x / fps {fps} / 码率 {bitrate}"),
        }
    }
}

struct DedupVariant {
    speed: f64,
    fps: &'static str,
    bitrate: String,
    crf: u8,
    brightness: f64,
    contrast: f64,
    saturation: f64,
    hue: f64,
}

impl DedupVariant {
    fn from_seed(seed: u32) -> Self {
        let speed_values = [0.985, 0.990, 0.995, 1.005, 1.010, 1.015];
        let fps_values = ["23.976", "24", "25", "29.97", "30"];
        let speed = speed_values[(seed as usize * 7 + 2) % speed_values.len()];
        let fps = fps_values[(seed as usize * 5 + 1) % fps_values.len()];
        let bitrate_num = 2200 + ((seed as usize * 379) % 2600);
        let crf = 20 + ((seed as u8).wrapping_mul(3) % 5);
        let signed = |value: i32, scale: f64| -> f64 { value as f64 / scale };
        Self {
            speed,
            fps,
            bitrate: format!("{bitrate_num}k"),
            crf,
            brightness: signed((seed.wrapping_mul(11) % 7) as i32 - 3, 1000.0),
            contrast: 1.0 + signed((seed.wrapping_mul(13) % 9) as i32 - 4, 1000.0),
            saturation: 1.0 + signed((seed.wrapping_mul(17) % 11) as i32 - 5, 1000.0),
            hue: signed((seed.wrapping_mul(19) % 9) as i32 - 4, 100.0),
        }
    }
}

#[tauri::command]
pub async fn start_render_task(
    app: tauri::AppHandle,
    state: tauri::State<'_, RenderState>,
    config: RenderConfig,
) -> Result<RenderTaskStatus, String> {
    let state = state.inner().clone();
    tauri::async_runtime::spawn_blocking(move || {
        crate::diagnostic_log::event("mix submission requested");
        let authorization = super::auth::require_membership()?;
        crate::diagnostic_log::event("mix membership verified");
        let plan = validate_plan(&app, config)?;
        crate::diagnostic_log::event("mix plan validated");
        let task = queued_render_task(plan);
        enqueue_task(&state, task, authorization)
    }).await.map_err(|_| "提交任务失败".to_owned())?
}

#[tauri::command]
pub fn get_render_status(state: tauri::State<RenderState>) -> Result<RenderTaskStatus, String> {
    snapshot_status(&state)
}

#[tauri::command]
pub fn cancel_render_task(state: tauri::State<RenderState>) -> Result<RenderTaskStatus, String> {
    if let Ok(mut status) = state.inner.lock() {
        if status.running {
            state.cancel.store(true, Ordering::SeqCst);
            status.cancelled = true;
            status.status = "正在取消".to_string();
            push_log(&mut status, "已请求取消当前任务；队列中的后续任务会继续执行。".to_string());
        }
    }
    snapshot_status(&state)
}

#[tauri::command]
pub async fn start_overlay_task(
    app: tauri::AppHandle,
    state: tauri::State<'_, RenderState>,
    config: OverlayConfig,
) -> Result<RenderTaskStatus, String> {
    let state = state.inner().clone();
    tauri::async_runtime::spawn_blocking(move || {
        let authorization = super::auth::require_membership()?;
        let plan = validate_overlay_plan(&app, config)?;
        let task = queued_overlay_task(plan);
        enqueue_task(&state, task, authorization)
    }).await.map_err(|_| "提交任务失败".to_owned())?
}

#[tauri::command]
pub async fn start_watermark_task(
    app: tauri::AppHandle,
    state: tauri::State<'_, RenderState>,
    config: WatermarkConfig,
) -> Result<RenderTaskStatus, String> {
    let state = state.inner().clone();
    tauri::async_runtime::spawn_blocking(move || {
        let authorization = super::auth::require_membership()?;
        let plan = validate_watermark_plan(&app, config)?;
        let task = queued_watermark_task(plan);
        enqueue_task(&state, task, authorization)
    }).await.map_err(|_| "提交任务失败".to_owned())?
}

#[tauri::command]
pub async fn start_dedup_task(
    app: tauri::AppHandle,
    state: tauri::State<'_, RenderState>,
    config: DedupConfig,
) -> Result<RenderTaskStatus, String> {
    let state = state.inner().clone();
    tauri::async_runtime::spawn_blocking(move || {
        let authorization = super::auth::require_membership()?;
        let plan = validate_dedup_plan(&app, config)?;
        let task = queued_dedup_task(plan);
        enqueue_task(&state, task, authorization)
    }).await.map_err(|_| "提交任务失败".to_owned())?
}

#[tauri::command]
pub fn remove_queued_task(
    state: tauri::State<RenderState>,
    task_id: String,
) -> Result<RenderTaskStatus, String> {
    let removed = {
        let mut runtime = state.queue.lock().map_err(|_| "任务队列不可用".to_string())?;
        let position = runtime.pending.iter().position(|task| task.id == task_id);
        position.and_then(|index| runtime.pending.remove(index)).is_some()
    };
    if removed {
        let mut items = state.queue_items.lock().map_err(|_| "任务队列不可用".to_string())?;
        items.retain(|item| item.id != task_id);
        if let Ok(mut archive) = state.task_archive.lock() {
            archive.remove(&task_id);
        }
    }
    snapshot_status(&state)
}

#[tauri::command]
pub fn clear_pending_tasks(state: tauri::State<RenderState>) -> Result<RenderTaskStatus, String> {
    let pending_ids = {
        let mut runtime = state.queue.lock().map_err(|_| "任务队列不可用".to_string())?;
        let ids = runtime.pending.iter().map(|task| task.id.clone()).collect::<Vec<_>>();
        runtime.pending.clear();
        ids
    };
    if !pending_ids.is_empty() {
        let mut items = state.queue_items.lock().map_err(|_| "任务队列不可用".to_string())?;
        items.retain(|item| !pending_ids.contains(&item.id));
        if let Ok(mut archive) = state.task_archive.lock() {
            archive.retain(|id, _| !pending_ids.contains(id));
        }
    }
    snapshot_status(&state)
}

#[tauri::command]
pub fn clear_finished_tasks(state: tauri::State<RenderState>) -> Result<RenderTaskStatus, String> {
    let current_id = state
        .inner
        .lock()
        .map_err(|_| "任务状态不可用".to_string())?
        .current_task_id
        .clone();
    let mut items = state.queue_items.lock().map_err(|_| "任务队列不可用".to_string())?;
    let removed_ids = items
        .iter()
        .filter(|item| item.id != current_id && !matches!(item.status.as_str(), "waiting" | "running" | "cancelling"))
        .map(|item| item.id.clone())
        .collect::<Vec<_>>();
    items.retain(|item| item.id == current_id || item.status == "waiting" || item.status == "running");
    drop(items);
    if let Ok(mut archive) = state.task_archive.lock() {
        archive.retain(|id, _| !removed_ids.contains(id));
    }
    snapshot_status(&state)
}

#[tauri::command]
pub async fn retry_queue_task(
    state: tauri::State<'_, RenderState>,
    task_id: String,
) -> Result<RenderTaskStatus, String> {
    let state = state.inner().clone();
    tauri::async_runtime::spawn_blocking(move || {
    let authorization = super::auth::require_membership()?;
    let plan = state
        .task_archive
        .lock()
        .map_err(|_| "任务归档不可用".to_string())?
        .get(&task_id)
        .cloned()
        .ok_or_else(|| "找不到可重试的任务配置".to_string())?;
    let task = match plan {
        QueuedTaskPlan::Render(plan) => queued_render_task_with_retry(plan, true),
        QueuedTaskPlan::Overlay(plan) => queued_overlay_task_with_retry(plan, true),
        QueuedTaskPlan::Watermark(plan) => queued_watermark_task_with_retry(plan, true),
        QueuedTaskPlan::Dedup(plan) => queued_dedup_task_with_retry(plan, true),
    };
    enqueue_task(&state, task, authorization)
    }).await.map_err(|_| "重试任务失败".to_owned())?
}

fn queued_render_task(plan: RenderPlan) -> QueuedTask {
    queued_render_task_with_retry(plan, false)
}

fn queued_render_task_with_retry(mut plan: RenderPlan, is_retry: bool) -> QueuedTask {
    if is_retry {
        plan.config.conflict_strategy = "skip".to_string();
    }
    let id = next_task_id();
    let source_name = plan
        .source
        .file_name()
        .and_then(|name| name.to_str())
        .unwrap_or("混剪任务");
    let item = QueueTaskStatus {
        id: id.clone(),
        name: format!("{}{source_name} · {} 条", if is_retry { "重试 · " } else { "" }, plan.config.output_count),
        task_kind: "批量混剪".to_string(),
        status: "waiting".to_string(),
        progress: 0,
        completed: 0,
        failed: 0,
        total: plan.config.output_count,
        output_folder: plan.output.to_string_lossy().to_string(),
        created_at: unix_millis() as u64,
        is_retry,
    };
    QueuedTask { id, plan: QueuedTaskPlan::Render(plan), item, authorization: None }
}

fn queued_overlay_task(plan: OverlayPlan) -> QueuedTask {
    queued_overlay_task_with_retry(plan, false)
}

fn queued_overlay_task_with_retry(mut plan: OverlayPlan, is_retry: bool) -> QueuedTask {
    if is_retry {
        plan.config.conflict_strategy = "skip".to_string();
    }
    let id = next_task_id();
    let item = QueueTaskStatus {
        id: id.clone(),
        name: format!("{}{} 个视频", if is_retry { "重试 · " } else { "" }, plan.videos.len()),
        task_kind: "视频套外框".to_string(),
        status: "waiting".to_string(),
        progress: 0,
        completed: 0,
        failed: 0,
        total: plan.videos.len() as u32,
        output_folder: plan.output.to_string_lossy().to_string(),
        created_at: unix_millis() as u64,
        is_retry,
    };
    QueuedTask { id, plan: QueuedTaskPlan::Overlay(plan), item, authorization: None }
}

fn queued_watermark_task(plan: WatermarkPlan) -> QueuedTask {
    queued_watermark_task_with_retry(plan, false)
}

fn queued_watermark_task_with_retry(mut plan: WatermarkPlan, is_retry: bool) -> QueuedTask {
    if is_retry {
        plan.config.conflict_strategy = "skip".to_string();
    }
    let id = next_task_id();
    let source_name = plan
        .source
        .file_name()
        .and_then(|name| name.to_str())
        .unwrap_or("视频文件夹");
    let item = QueueTaskStatus {
        id: id.clone(),
        name: format!("{}{source_name} · {} 个视频", if is_retry { "重试 · " } else { "" }, plan.videos.len()),
        task_kind: "飘动水印".to_string(),
        status: "waiting".to_string(),
        progress: 0,
        completed: 0,
        failed: 0,
        total: plan.videos.len() as u32,
        output_folder: plan.output.to_string_lossy().to_string(),
        created_at: unix_millis() as u64,
        is_retry,
    };
    QueuedTask { id, plan: QueuedTaskPlan::Watermark(plan), item, authorization: None }
}

fn queued_dedup_task(plan: DedupPlan) -> QueuedTask {
    queued_dedup_task_with_retry(plan, false)
}

fn queued_dedup_task_with_retry(mut plan: DedupPlan, is_retry: bool) -> QueuedTask {
    if is_retry {
        plan.config.conflict_strategy = "skip".to_string();
    }
    let id = next_task_id();
    let source_name = plan
        .source
        .file_name()
        .and_then(|name| name.to_str())
        .unwrap_or("视频文件夹");
    let item = QueueTaskStatus {
        id: id.clone(),
        name: format!("{}{source_name} · {} 个视频", if is_retry { "重试 · " } else { "" }, plan.videos.len()),
        task_kind: "视频去重".to_string(),
        status: "waiting".to_string(),
        progress: 0,
        completed: 0,
        failed: 0,
        total: plan.videos.len() as u32,
        output_folder: plan.output.to_string_lossy().to_string(),
        created_at: unix_millis() as u64,
        is_retry,
    };
    QueuedTask { id, plan: QueuedTaskPlan::Dedup(plan), item, authorization: None }
}

fn enqueue_task(state: &RenderState, mut task: QueuedTask, authorization: super::auth::Credentials) -> Result<RenderTaskStatus, String> {
    task.authorization = Some(authorization);
    let item = task.item.clone();
    let archived_plan = task.plan.clone();
    {
        let mut items = state.queue_items.lock().map_err(|_| "任务队列不可用".to_string())?;
        let removed = prune_queue_history(&mut items);
        if let Ok(mut archive) = state.task_archive.lock() {
            for id in removed { archive.remove(&id); }
        }
        items.push(item);
    }
    state
        .task_archive
        .lock()
        .map_err(|_| "任务归档不可用".to_string())?
        .insert(task.id.clone(), archived_plan);
    let should_start = {
        let mut runtime = state.queue.lock().map_err(|_| "任务队列不可用".to_string())?;
        runtime.pending.push_back(task);
        if runtime.active {
            false
        } else {
            runtime.active = true;
            true
        }
    };
    if should_start {
        let worker_state = state.clone();
        thread::spawn(move || run_queue_loop(worker_state));
    }
    snapshot_status(state)
}

fn run_queue_loop(state: RenderState) {
    loop {
        let task = {
            let mut runtime = match state.queue.lock() {
                Ok(runtime) => runtime,
                Err(_) => return,
            };
            match runtime.pending.pop_front() {
                Some(task) => task,
                None => {
                    runtime.active = false;
                    return;
                }
            }
        };

        state.cancel.store(false, Ordering::SeqCst);
        let initial = match &task.plan {
            QueuedTaskPlan::Render(plan) => initial_render_status(plan, &task.id),
            QueuedTaskPlan::Overlay(plan) => initial_overlay_status(plan, &task.id),
            QueuedTaskPlan::Watermark(plan) => initial_watermark_status(plan, &task.id),
            QueuedTaskPlan::Dedup(plan) => initial_dedup_status(plan, &task.id),
        };
        if let Ok(mut status) = state.inner.lock() {
            *status = initial;
        }
        set_queue_item_running(&state.queue_items, &task.id);

        crate::diagnostic_log::event(&format!("task {} started ({})", task.id, task.item.task_kind));

        let outcome = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            let authorization = task.authorization.as_ref()
                .ok_or_else(|| "任务缺少有效授权".to_owned())
                .and_then(super::auth::revalidate_membership);
            if let Err(error) = authorization {
                if let Ok(mut status) = state.inner.lock() {
                    status.running = false;
                    status.failed = status.total;
                    status.status = "授权验证失败".into();
                    push_log(&mut status, error);
                }
            } else {
                match task.plan {
                    QueuedTaskPlan::Render(plan) => run_render_task(plan, state.inner.clone(), state.cancel.clone()),
                    QueuedTaskPlan::Overlay(plan) => run_overlay_task(plan, state.inner.clone(), state.cancel.clone()),
                    QueuedTaskPlan::Watermark(plan) => run_watermark_task(plan, state.inner.clone(), state.cancel.clone()),
                    QueuedTaskPlan::Dedup(plan) => run_dedup_task(plan, state.inner.clone(), state.cancel.clone()),
                }
            }
        }));
        if outcome.is_err() {
            crate::diagnostic_log::event(&format!("task {} failed after a worker panic", task.id));
            if let Ok(mut status) = state.inner.lock() {
                status.running = false;
                status.failed = status.total.saturating_sub(status.completed);
                status.status = "处理异常".into();
                push_log(&mut status, "处理线程异常退出，请在日志中查看原因后重试。".into());
                update_progress(&mut status);
            }
        }
        let final_status = state.inner.lock().ok().map(|status| status.clone());
        if let Some(final_status) = final_status {
            crate::diagnostic_log::event(&format!("task {} ended: completed={}, failed={}, cancelled={}", task.id, final_status.completed, final_status.failed, final_status.cancelled));
            finish_queue_item(&state.queue_items, &task.id, &final_status);
        }
        if let Ok(mut status) = state.inner.lock() {
            status.current_task_id.clear();
        }
    }
}

fn initial_render_status(plan: &RenderPlan, task_id: &str) -> RenderTaskStatus {
    let mut status = RenderTaskStatus {
        in_flight: HashMap::new(),
        running: true,
        cancelled: false,
        status: "运行中".to_string(),
        progress: 0,
        completed: 0,
        failed: 0,
        total: plan.config.output_count,
        output_folder: plan.output.to_string_lossy().to_string(),
        task_kind: "批量混剪".to_string(),
        logs: vec!["队列任务已开始。".to_string()],
        current_task_id: task_id.to_string(),
        pending_count: 0,
        queue: Vec::new(),
    };
    push_log(&mut status, format!("找到主素材：{} 个。", plan.videos.len()));
    if plan.config.enable_first_video {
        push_log(&mut status, format!("首视频已启用：{} 个。", plan.first_videos.len()));
    }
    if plan.config.enable_top_insert {
        push_log(&mut status, format!("top 插片已启用：{} 个。", plan.top_videos.len()));
    }
    if plan.config.enable_tail_video {
        push_log(&mut status, format!("尾视频已启用：{} 个。", plan.tail_videos.len()));
    }
    if let Some(banner) = plan.banner.as_ref() {
        push_log(&mut status, format!("底栏视频已启用：{}。", file_name(banner)));
    }
    push_log(&mut status, format!("素材目录：{}", plan.source.to_string_lossy()));
    push_log(&mut status, format!("每条拼接：{} 个素材。", plan.config.segment_count));
    push_log(&mut status, format!("计划生成：{} 条。", plan.config.output_count));
    push_log(&mut status, format!("编码模式：{}。", encoder_mode_label(&plan.config.encoder)));
    push_log(&mut status, format!("并发生成：{} 路；策略：{}。", worker_count(plan), concurrency_label(&plan.config.concurrency_mode)));
    push_log(&mut status, format!("输出冲突策略：{}。", conflict_label(&plan.config.conflict_strategy)));
    if plan.config.keep_audio && plan.ffprobe.is_none() {
        push_log(&mut status, "警告：找不到 ffprobe，无法检测音频，本次会自动输出无音频。".to_string());
    }
    push_log(&mut status, format!("输出目录：{}", plan.output.to_string_lossy()));
    status
}

fn initial_overlay_status(plan: &OverlayPlan, task_id: &str) -> RenderTaskStatus {
    let mut status = RenderTaskStatus {
        in_flight: HashMap::new(),
        running: true,
        cancelled: false,
        status: "运行中".to_string(),
        progress: 0,
        completed: 0,
        failed: 0,
        total: plan.videos.len() as u32,
        output_folder: plan.output.to_string_lossy().to_string(),
        task_kind: "视频套外框".to_string(),
        logs: vec!["队列任务已开始。".to_string()],
        current_task_id: task_id.to_string(),
        pending_count: 0,
        queue: Vec::new(),
    };
    push_log(&mut status, format!("外框图片：{}", plan.frame.to_string_lossy()));
    push_log(&mut status, format!("视频数量：{} 个。", plan.videos.len()));
    push_log(&mut status, format!("输出目录：{}", plan.output.to_string_lossy()));
    status
}

fn initial_watermark_status(plan: &WatermarkPlan, task_id: &str) -> RenderTaskStatus {
    let mut status = RenderTaskStatus {
        in_flight: HashMap::new(),
        running: true,
        cancelled: false,
        status: "运行中".to_string(),
        progress: 0,
        completed: 0,
        failed: 0,
        total: plan.videos.len() as u32,
        output_folder: plan.output.to_string_lossy().to_string(),
        task_kind: "飘动水印".to_string(),
        logs: vec!["队列任务已开始。".to_string()],
        current_task_id: task_id.to_string(),
        pending_count: 0,
        queue: Vec::new(),
    };
    push_log(&mut status, format!("视频文件夹：{}", plan.source.to_string_lossy()));
    push_log(&mut status, format!("Logo 图片：{}", plan.logo.to_string_lossy()));
    push_log(&mut status, format!("找到视频：{} 个。", plan.videos.len()));
    push_log(&mut status, format!("Logo 宽度：{:.1}%；速度：{:.1} px/秒；透明度：{:.2}。", plan.config.width_percent, plan.config.speed, plan.config.opacity));
    push_log(&mut status, format!("输出目录：{}", plan.output.to_string_lossy()));
    status
}

fn initial_dedup_status(plan: &DedupPlan, task_id: &str) -> RenderTaskStatus {
    let mut status = RenderTaskStatus {
        in_flight: HashMap::new(),
        running: true,
        cancelled: false,
        status: "运行中".to_string(),
        progress: 0,
        completed: 0,
        failed: 0,
        total: plan.videos.len() as u32,
        output_folder: plan.output.to_string_lossy().to_string(),
        task_kind: "视频去重".to_string(),
        logs: vec!["队列任务已开始。".to_string()],
        current_task_id: task_id.to_string(),
        pending_count: 0,
        queue: Vec::new(),
    };
    push_log(&mut status, format!("视频文件夹：{}", plan.source.to_string_lossy()));
    push_log(&mut status, format!("找到视频：{} 个。", plan.videos.len()));
    push_log(&mut status, format!(
        "处理项：随机码率={}，抽帧={}，微变速={}，极淡滤镜={}，音频={}。",
        if plan.config.random_bitrate { "开启" } else { "关闭" },
        if plan.config.drop_frames { "开启" } else { "关闭" },
        if plan.config.micro_speed { "开启" } else { "关闭" },
        if plan.config.subtle_filter { "开启" } else { "关闭" },
        if plan.config.keep_audio { "保留" } else { "不保留" },
    ));
    push_log(&mut status, format!("输出目录：{}", plan.output.to_string_lossy()));
    status
}

fn snapshot_status(state: &RenderState) -> Result<RenderTaskStatus, String> {
    let mut status = state
        .inner
        .lock()
        .map_err(|_| "任务状态不可用".to_string())?
        .clone();
    let mut items = state.queue_items.lock().map_err(|_| "任务队列不可用".to_string())?.clone();
    if status.running && !status.current_task_id.is_empty() {
        if let Some(item) = items.iter_mut().find(|item| item.id == status.current_task_id) {
            item.status = if status.cancelled { "cancelling" } else { "running" }.to_string();
            item.progress = status.progress;
            item.completed = status.completed;
            item.failed = status.failed;
        }
    }
    status.pending_count = items.iter().filter(|item| item.status == "waiting").count() as u32;
    status.queue = items;
    Ok(status)
}

fn set_queue_item_running(items: &Arc<Mutex<Vec<QueueTaskStatus>>>, task_id: &str) {
    if let Ok(mut items) = items.lock() {
        if let Some(item) = items.iter_mut().find(|item| item.id == task_id) {
            item.status = "running".to_string();
        }
    }
}

fn finish_queue_item(items: &Arc<Mutex<Vec<QueueTaskStatus>>>, task_id: &str, status: &RenderTaskStatus) {
    if let Ok(mut items) = items.lock() {
        if let Some(item) = items.iter_mut().find(|item| item.id == task_id) {
            item.status = if status.cancelled {
                "cancelled"
            } else if status.failed > 0 {
                "completed_with_errors"
            } else {
                "completed"
            }
            .to_string();
            item.progress = status.progress;
            item.completed = status.completed;
            item.failed = status.failed;
        }
    }
}

fn prune_queue_history(items: &mut Vec<QueueTaskStatus>) -> Vec<String> {
    let mut removed = Vec::new();
    while items.len() >= 50 {
        if let Some(index) = items.iter().position(|item| !matches!(item.status.as_str(), "waiting" | "running" | "cancelling")) {
            removed.push(items.remove(index).id);
        } else {
            break;
        }
    }
    removed
}

fn next_task_id() -> String {
    let sequence = QUEUE_SEQUENCE.fetch_add(1, Ordering::SeqCst);
    format!("task-{}-{sequence}", unix_millis())
}

fn validate_plan(app: &tauri::AppHandle, config: RenderConfig) -> Result<RenderPlan, String> {
    if config.segment_count == 0 {
        return Err("每条主素材数必须大于 0。".to_string());
    }
    if config.output_count == 0 {
        return Err("生成数量必须大于 0。".to_string());
    }

    let source = PathBuf::from(config.source_folder.trim());
    if !source.exists() || !source.is_dir() {
        return Err("素材目录不存在或不可访问。".to_string());
    }

    let output = resolve_output_folder(&source, &config.output_folder);
    fs::create_dir_all(&output).map_err(|err| format!("输出目录无法创建：{err}"))?;
    ensure_output_writable(&output)?;

    let banner = resolve_banner(&source, &config);
    let videos = scan_main_videos(&source, banner.as_deref());
    if videos.is_empty() {
        return Err("当前素材目录没有找到可用主素材。".to_string());
    }
    if !config.allow_repeat_inside_one_video && config.segment_count as usize > videos.len() {
        return Err("关闭同条重复时，每条主素材数不能大于主素材数量。".to_string());
    }

    let first_videos = if config.enable_first_video {
        let folder = PathBuf::from(config.first_video_folder.trim());
        let videos = scan_videos(&folder);
        if !folder.exists() || !folder.is_dir() || videos.is_empty() {
            return Err("已启用首视频，但首视频文件夹不存在或没有视频。".to_string());
        }
        videos
    } else {
        Vec::new()
    };

    let top_videos = if config.enable_top_insert {
        let videos = scan_videos(&source.join("top"));
        if videos.is_empty() {
            return Err("已启用 top 插片，但素材目录下 top 文件夹没有视频。".to_string());
        }
        videos
    } else {
        Vec::new()
    };

    let tail_videos = if config.enable_tail_video {
        let folder = PathBuf::from(config.tail_video_folder.trim());
        let videos = scan_videos(&folder);
        if !folder.exists() || !folder.is_dir() || videos.is_empty() {
            return Err("已启用尾视频，但尾视频文件夹不存在或没有视频。".to_string());
        }
        videos
    } else {
        Vec::new()
    };

    if config.enable_banner_overlay && banner.as_ref().map(|path| !path.exists()).unwrap_or(true) {
        return Err("已启用底栏视频，但没有找到可用底栏视频。".to_string());
    }

    let ffmpeg = find_binary(app, "ffmpeg.exe", &source).or_else(|| find_binary(app, "ffmpeg", &source));
    let Some(ffmpeg) = ffmpeg else {
        return Err("找不到 ffmpeg，请放入程序 bin 目录、素材目录或加入系统 PATH。".to_string());
    };
    validate_encoder(&ffmpeg, &config.encoder)?;
    let ffprobe = find_binary(app, "ffprobe.exe", &source).or_else(|| find_binary(app, "ffprobe", &source));

    Ok(RenderPlan { probes: Arc::default(), config, source, output, ffmpeg, ffprobe, videos, first_videos, top_videos, tail_videos, banner })
}

fn validate_overlay_plan(app: &tauri::AppHandle, config: OverlayConfig) -> Result<OverlayPlan, String> {
    let frame = PathBuf::from(config.frame_file.trim());
    if !frame.exists() || !frame.is_file() {
        return Err("背景图片不存在或不可访问。".to_string());
    }
    let frame_ext = frame.extension().and_then(|ext| ext.to_str()).unwrap_or("").to_lowercase();
    if !IMAGE_EXTS.contains(&frame_ext.as_str()) {
        return Err("背景图片格式不支持，请选择 png/jpg/jpeg/webp/bmp。".to_string());
    }
    if config.video_files.is_empty() {
        return Err("请至少选择一个视频。".to_string());
    }
    let videos = config
        .video_files
        .iter()
        .map(|value| PathBuf::from(value.trim()))
        .filter(|path| {
            path.exists()
                && path.is_file()
                && path.extension()
                    .and_then(|ext| ext.to_str())
                    .map(|ext| VIDEO_EXTS.contains(&ext.to_lowercase().as_str()))
                    .unwrap_or(false)
        })
        .collect::<Vec<_>>();
    if videos.is_empty() {
        return Err("选择的视频不存在、不可访问或格式不支持。".to_string());
    }

    let (canvas_w, canvas_h) = config.orientation.dimensions();
    let w = even_dimension(config.width.max(2));
    let h = even_dimension(config.height.max(2));
    if w > (canvas_w * 2) as u32 || h > (canvas_h * 2) as u32 {
        return Err(format!("视频层尺寸过大，请将宽高控制在 {}x{} 以内。", canvas_w * 2, canvas_h * 2));
    }
    let x = config.x.clamp(-canvas_w, canvas_w);
    let y = config.y.clamp(-canvas_h, canvas_h);
    let outside = x >= canvas_w || y >= canvas_h || x + w as i32 <= 0 || y + h as i32 <= 0;
    if outside {
        return Err(format!("视频层完全位于 {canvas_w}x{canvas_h} 画布外，请调整 X/Y/宽高。"));
    }

    if config.fps == 0 || config.fps > 120 {
        return Err("帧率需要在 1-120 之间。".to_string());
    }
    if config.crf > 51 {
        return Err("CRF 需要在 0-51 之间。".to_string());
    }

    let source = videos
        .first()
        .and_then(|path| path.parent())
        .map(|path| path.to_path_buf())
        .unwrap_or_else(|| PathBuf::from("."));
    let output = resolve_output_folder(&source, &config.output_folder);
    fs::create_dir_all(&output).map_err(|err| format!("输出目录无法创建：{err}"))?;

    let ffmpeg = find_binary(app, "ffmpeg.exe", &source).or_else(|| find_binary(app, "ffmpeg", &source));
    let Some(ffmpeg) = ffmpeg else {
        return Err("找不到 ffmpeg，请放入程序 bin 目录、素材目录或加入系统 PATH。".to_string());
    };
    let ffprobe = find_binary(app, "ffprobe.exe", &source).or_else(|| find_binary(app, "ffprobe", &source));
    match config.encoder.as_str() {
        "auto" | "nvenc_h264" | "qsv_h264" | "amf_h264" | "nvidia_nvenc" | "intel_qsv" | "amd_amf" | "mixed_nvidia" | "mixed_intel" | "mixed_amd" => validate_encoder(&ffmpeg, &config.encoder)?,
        _ => validate_encoder(&ffmpeg, "cpu_libx264")?,
    }
    ensure_output_writable(&output)?;

    Ok(OverlayPlan { probes: Arc::default(), config, frame, videos, output, ffmpeg, ffprobe })
}

fn validate_watermark_plan(app: &tauri::AppHandle, config: WatermarkConfig) -> Result<WatermarkPlan, String> {
    let source = PathBuf::from(config.source_folder.trim());
    if !source.exists() || !source.is_dir() {
        return Err("视频文件夹不存在或不可访问。".to_string());
    }
    let videos = scan_videos(&source);
    if videos.is_empty() {
        return Err("当前文件夹没有找到支持的视频。".to_string());
    }

    let logo = PathBuf::from(config.logo_file.trim());
    if !logo.exists() || !logo.is_file() {
        return Err("Logo 图片不存在或不可访问。".to_string());
    }
    let logo_ext = logo.extension().and_then(|ext| ext.to_str()).unwrap_or("").to_ascii_lowercase();
    if !IMAGE_EXTS.contains(&logo_ext.as_str()) {
        return Err("Logo 图片格式不支持，请选择 png/jpg/jpeg/webp/bmp。".to_string());
    }
    if !(5.0..=35.0).contains(&config.width_percent) {
        return Err("Logo 宽度占比需要在 5% - 35% 之间。".to_string());
    }
    if !(40.0..=600.0).contains(&config.speed) {
        return Err("飘动速度需要在 40 - 600 px/秒之间。".to_string());
    }
    if !(0.1..=1.0).contains(&config.opacity) {
        return Err("透明度需要在 0.1 - 1.0 之间。".to_string());
    }

    let configured = config.output_folder.trim();
    let selected_output = if configured.is_empty() { source.join("水印版") } else { PathBuf::from(configured) };
    let output = if same_path(&selected_output, &source) { source.join("水印版") } else { selected_output };
    fs::create_dir_all(&output).map_err(|err| format!("输出目录无法创建：{err}"))?;
    ensure_output_writable(&output)?;

    let ffmpeg = find_binary(app, "ffmpeg.exe", &source).or_else(|| find_binary(app, "ffmpeg", &source));
    let Some(ffmpeg) = ffmpeg else {
        return Err("找不到 ffmpeg，请放入程序 bin 目录、素材目录或加入系统 PATH。".to_string());
    };
    match config.encoder.as_str() {
        "auto" | "nvenc_h264" | "qsv_h264" | "amf_h264" | "nvidia_nvenc" | "intel_qsv" | "amd_amf" | "mixed_nvidia" | "mixed_intel" | "mixed_amd" => validate_encoder(&ffmpeg, &config.encoder)?,
        _ => validate_encoder(&ffmpeg, "cpu_libx264")?,
    }
    let ffprobe = find_binary(app, "ffprobe.exe", &source).or_else(|| find_binary(app, "ffprobe", &source));

    Ok(WatermarkPlan { probes: Arc::default(), config, source, logo, videos, output, ffmpeg, ffprobe })
}

fn validate_dedup_plan(app: &tauri::AppHandle, config: DedupConfig) -> Result<DedupPlan, String> {
    let source = PathBuf::from(config.source_folder.trim());
    if !source.exists() || !source.is_dir() {
        return Err("视频文件夹不存在或不可访问。".to_string());
    }
    let videos = scan_videos(&source);
    if videos.is_empty() {
        return Err("当前文件夹没有找到支持的视频。".to_string());
    }

    let configured = config.output_folder.trim();
    let selected_output = if configured.is_empty() { source.join("去重") } else { PathBuf::from(configured) };
    let output = if same_path(&selected_output, &source) { source.join("去重") } else { selected_output };
    fs::create_dir_all(&output).map_err(|err| format!("输出目录无法创建：{err}"))?;
    ensure_output_writable(&output)?;

    let ffmpeg = find_binary(app, "ffmpeg.exe", &source).or_else(|| find_binary(app, "ffmpeg", &source));
    let Some(ffmpeg) = ffmpeg else {
        return Err("找不到 ffmpeg，请放入程序 bin 目录、素材目录或加入系统 PATH。".to_string());
    };
    match config.encoder.as_str() {
        "auto" | "nvenc_h264" | "qsv_h264" | "amf_h264" | "nvidia_nvenc" | "intel_qsv" | "amd_amf" | "mixed_nvidia" | "mixed_intel" | "mixed_amd" => validate_encoder(&ffmpeg, &config.encoder)?,
        _ => validate_encoder(&ffmpeg, "cpu_libx264")?,
    }
    let ffprobe = find_binary(app, "ffprobe.exe", &source).or_else(|| find_binary(app, "ffprobe", &source));

    Ok(DedupPlan { probes: Arc::default(), config, source, videos, output, ffmpeg, ffprobe })
}

fn run_watermark_task(plan: WatermarkPlan, state: Arc<Mutex<RenderTaskStatus>>, cancel: Arc<AtomicBool>) {
    let total = plan.videos.len() as u32;
    let workers = watermark_worker_count(&plan);
    let next_index = Arc::new(AtomicU32::new(0));
    log_state(&state, format!(
        "飘动水印参数：宽度={:.1}%，速度={:.1}px/秒，透明度={:.2}，音频={}，编码={}，并发={}，冲突={}。",
        plan.config.width_percent,
        plan.config.speed,
        plan.config.opacity,
        if plan.config.keep_audio { "保留" } else { "不保留" },
        encoder_mode_label(&plan.config.encoder),
        workers,
        conflict_label(&plan.config.conflict_strategy),
    ));
    if plan.ffprobe.is_none() {
        log_state(&state, "未找到 ffprobe：精确进度会降级。".to_string());
    }

    thread::scope(|scope| {
        for _ in 0..workers {
            let plan_ref = &plan;
            let state_ref = state.clone();
            let cancel_ref = cancel.clone();
            let next_ref = next_index.clone();
            scope.spawn(move || loop {
                if cancel_ref.load(Ordering::SeqCst) {
                    break;
                }
                let offset = next_ref.fetch_add(1, Ordering::SeqCst) as usize;
                if offset >= plan_ref.videos.len() {
                    break;
                }
                let video = &plan_ref.videos[offset];
                let index = offset as u32 + 1;
                let output_name = video.file_name().map(|name| name.to_os_string()).unwrap_or_else(|| format!("video_{index:04}.mp4").into());
                let requested = plan_ref.output.join(output_name);
                let Some(out_file) = resolve_output_path_with_strategy(&requested, &plan_ref.config.conflict_strategy) else {
                    log_state(&state_ref, format!("[{index}] 输出已存在，按 skip 策略跳过：{}", file_name(&requested)));
                    mark_completed(&state_ref, index, format!("跳过：{}", file_name(&requested)));
                    continue;
                };
                log_state(&state_ref, format!("[{index}] 开始添加飘动水印：{}", file_name(video)));
                let staging = staging_path(&out_file);
                let result = run_watermark_ffmpeg(plan_ref, video, &staging, index, total, &state_ref, &cancel_ref)
                    .and_then(|_| publish_output(&staging, &out_file, &cancel_ref));
                if result.is_err() { let _ = fs::remove_file(&staging); }
                match result {
                    Ok(()) => mark_completed(&state_ref, index, file_name(&out_file)),
                    Err(err) => {
                        if cancel_ref.load(Ordering::SeqCst) {
                            log_state(&state_ref, format!("[{index}] 已取消当前 FFmpeg：{}", file_name(video)));
                            break;
                        }
                        log_state(&state_ref, err.chars().take(3000).collect::<String>());
                        mark_failed(&state_ref, index, format!("[{index}] 飘动水印处理失败：{}", file_name(video)));
                    }
                }
            });
        }
    });

    if let Ok(mut status) = state.lock() {
        status.running = false;
        if cancel.load(Ordering::SeqCst) {
            status.cancelled = true;
            status.status = "已取消".to_string();
        } else if status.failed > 0 {
            status.status = "已完成，有失败".to_string();
        } else {
            status.status = "已完成".to_string();
        }
        update_progress(&mut status);
        let completed = status.completed;
        let failed = status.failed;
        let total = status.total;
        push_log(&mut status, format!("任务结束：完成 {completed}，失败 {failed}，总计 {total}。"));
    }
}

fn run_watermark_ffmpeg(
    plan: &WatermarkPlan,
    video: &Path,
    out_file: &Path,
    index: u32,
    total: u32,
    state: &Arc<Mutex<RenderTaskStatus>>,
    cancel: &Arc<AtomicBool>,
) -> Result<(), String> {
    let ratio = (plan.config.width_percent / 100.0).clamp(0.05, 0.35);
    let opacity = plan.config.opacity.clamp(0.1, 1.0);
    let speed = plan.config.speed.clamp(40.0, 600.0);
    let vx = speed * 0.8;
    let vy = speed * 0.6;
    let filter_complex = format!(
        "[1:v]format=rgba,colorchannelmixer=aa={opacity:.3}[wm_alpha];[wm_alpha][0:v]scale2ref=w='trunc(main_w*{ratio:.6}/2)*2':h=-2[wm][base];[base][wm]overlay=x='abs(mod({vx:.3}*t\\,2*max(1\\,main_w-overlay_w))-max(1\\,main_w-overlay_w))':y='abs(mod({vy:.3}*t\\,2*max(1\\,main_h-overlay_h))-max(1\\,main_h-overlay_h))':eval=frame:shortest=1,format=yuv420p[v]"
    );

    let mut cmd = Command::new(&plan.ffmpeg);
    cmd.args(["-hide_banner", "-loglevel", "error", "-y"]);
    cmd.arg("-i").arg(video);
    cmd.arg("-loop").arg("1").arg("-i").arg(&plan.logo);
    cmd.args(["-filter_complex", &filter_complex, "-map", "[v]"]);
    if plan.config.keep_audio {
        cmd.args(["-map", "0:a?", "-c:a", "copy"]);
    } else {
        cmd.arg("-an");
    }
    append_watermark_encoder_args(&mut cmd, out_file, encoder_for_job(&plan.config.encoder, index));
    cmd.args(["-map_metadata", "0", "-shortest", "-progress", "pipe:1", "-nostats"]);
    cmd.arg(out_file);

    run_progress_cmd(cmd, &plan.probes, plan.ffprobe.as_deref(), video, index, total, state, cancel)
}

fn run_dedup_task(plan: DedupPlan, state: Arc<Mutex<RenderTaskStatus>>, cancel: Arc<AtomicBool>) {
    let total = plan.videos.len() as u32;
    let workers = dedup_worker_count(&plan);
    let next_index = Arc::new(AtomicU32::new(0));
    let task_seed = unix_millis() as u32;
    log_state(&state, format!(
        "视频去重参数：随机码率={}，抽帧={}，微变速={}，极淡滤镜={}，音频={}，编码={}，并发={}，冲突={}。",
        if plan.config.random_bitrate { "开启" } else { "关闭" },
        if plan.config.drop_frames { "开启" } else { "关闭" },
        if plan.config.micro_speed { "开启" } else { "关闭" },
        if plan.config.subtle_filter { "开启" } else { "关闭" },
        if plan.config.keep_audio { "保留" } else { "不保留" },
        encoder_mode_label(&plan.config.encoder),
        workers,
        conflict_label(&plan.config.conflict_strategy),
    ));
    if plan.ffprobe.is_none() && plan.config.keep_audio {
        log_state(&state, "未找到 ffprobe：无法可靠检测音频，本次会自动输出无音频，避免无音轨视频失败。".to_string());
    }

    thread::scope(|scope| {
        for _ in 0..workers {
            let plan_ref = &plan;
            let state_ref = state.clone();
            let cancel_ref = cancel.clone();
            let next_ref = next_index.clone();
            let task_seed_ref = task_seed;
            scope.spawn(move || loop {
                if cancel_ref.load(Ordering::SeqCst) {
                    break;
                }
                let offset = next_ref.fetch_add(1, Ordering::SeqCst) as usize;
                if offset >= plan_ref.videos.len() {
                    break;
                }
                let video = &plan_ref.videos[offset];
                let index = offset as u32 + 1;
                let output_name = video.file_name().map(|name| name.to_os_string()).unwrap_or_else(|| format!("video_{index:04}.mp4").into());
                let requested = plan_ref.output.join(output_name);
                let Some(out_file) = resolve_output_path_with_strategy(&requested, &plan_ref.config.conflict_strategy) else {
                    log_state(&state_ref, format!("[{index}] 输出已存在，按 skip 策略跳过：{}", file_name(&requested)));
                    mark_completed(&state_ref, index, format!("跳过：{}", file_name(&requested)));
                    continue;
                };
                let has_audio = plan_ref.config.keep_audio
                    && plan_ref
                        .ffprobe
                        .as_deref()
                        .map(|ffprobe| plan_ref.probes.get(ffprobe, video).has_audio)
                        .unwrap_or(false);
                log_state(&state_ref, format!("[{index}] 开始视频去重：{} -> {}", file_name(video), file_name(&out_file)));
                let variant_seed = task_seed_ref ^ index.wrapping_mul(0x9E37_79B9);
                let staging = staging_path(&out_file);
                let result = run_dedup_ffmpeg(plan_ref, video, &staging, index, total, variant_seed, has_audio, &state_ref, &cancel_ref)
                    .and_then(|_| publish_output(&staging, &out_file, &cancel_ref));
                if result.is_err() { let _ = fs::remove_file(&staging); }
                match result {
                    Ok(()) => mark_completed(&state_ref, index, file_name(&out_file)),
                    Err(err) => {
                        if cancel_ref.load(Ordering::SeqCst) {
                            log_state(&state_ref, format!("[{index}] 已取消当前 FFmpeg：{}", file_name(video)));
                            break;
                        }
                        log_state(&state_ref, err.chars().take(3000).collect::<String>());
                        mark_failed(&state_ref, index, format!("[{index}] 视频去重失败：{}", file_name(video)));
                    }
                }
            });
        }
    });

    if let Ok(mut status) = state.lock() {
        status.running = false;
        if cancel.load(Ordering::SeqCst) {
            status.cancelled = true;
            status.status = "已取消".to_string();
        } else if status.failed > 0 {
            status.status = "已完成，有失败".to_string();
        } else {
            status.status = "已完成".to_string();
        }
        update_progress(&mut status);
        let completed = status.completed;
        let failed = status.failed;
        let total = status.total;
        push_log(&mut status, format!("任务结束：完成 {completed}，失败 {failed}，总计 {total}。"));
    }
}

fn run_dedup_ffmpeg(
    plan: &DedupPlan,
    video: &Path,
    out_file: &Path,
    index: u32,
    total: u32,
    variant_seed: u32,
    has_audio: bool,
    state: &Arc<Mutex<RenderTaskStatus>>,
    cancel: &Arc<AtomicBool>,
) -> Result<(), String> {
    let variant = DedupVariant::from_seed(variant_seed);
    let speed = if plan.config.micro_speed { variant.speed } else { 1.0 };
    let mut video_filters = vec![format!("setpts={:.6}*PTS", 1.0 / speed)];
    if plan.config.drop_frames {
        video_filters.push(format!("fps={}", variant.fps));
    }
    if plan.config.subtle_filter {
        video_filters.push(format!(
            "eq=brightness={:.5}:contrast={:.5}:saturation={:.5},hue=h={:.5}",
            variant.brightness,
            variant.contrast,
            variant.saturation,
            variant.hue,
        ));
    }
    video_filters.push("format=yuv420p".to_string());

    let mut filter_complex = format!("[0:v]{}[v]", video_filters.join(","));
    if has_audio && plan.config.micro_speed {
        filter_complex.push_str(&format!(";[0:a]atempo={speed:.6}[a]"));
    }

    let mut cmd = Command::new(&plan.ffmpeg);
    cmd.args(["-hide_banner", "-loglevel", "error", "-y"]);
    cmd.arg("-i").arg(video);
    cmd.args(["-filter_complex", &filter_complex, "-map", "[v]"]);
    if has_audio {
        if plan.config.micro_speed {
            cmd.args(["-map", "[a]"]);
            append_dedup_audio_args(&mut cmd, out_file);
        } else {
            cmd.args(["-map", "0:a?", "-c:a", "copy"]);
        }
    } else {
        cmd.arg("-an");
    }
    append_dedup_encoder_args(
        &mut cmd,
        out_file,
        encoder_for_job(&plan.config.encoder, index),
        plan.config.random_bitrate.then_some(variant.bitrate.as_str()),
        if plan.config.random_bitrate { variant.crf } else { 23 },
    );
    cmd.args(["-map_metadata", "-1"]);
    if supports_faststart(out_file) {
        cmd.args(["-movflags", "+faststart"]);
    }
    cmd.args(["-progress", "pipe:1", "-nostats"]);
    cmd.arg(out_file);

    run_progress_cmd(cmd, &plan.probes, plan.ffprobe.as_deref(), video, index, total, state, cancel)
}

fn run_overlay_task(plan: OverlayPlan, state: Arc<Mutex<RenderTaskStatus>>, cancel: Arc<AtomicBool>) {
    let total = plan.videos.len() as u32;
    let workers = overlay_worker_count(&plan);
    let next_index = Arc::new(AtomicU32::new(0));
    let (canvas_w, canvas_h) = plan.config.orientation.dimensions();
    log_state(&state, format!(
        "背景合成任务参数：背景图={}，输出={}x{}，视频层 x={} y={} w={} h={}，适配={}，音频={}，编码={}，并发={}，冲突={}。",
        file_name(&plan.frame),
        canvas_w,
        canvas_h,
        plan.config.x,
        plan.config.y,
        plan.config.width,
        plan.config.height,
        plan.config.mode,
        if plan.config.keep_audio { "保留" } else { "不保留" },
        encoder_mode_label(&plan.config.encoder),
        workers,
        conflict_label(&plan.config.conflict_strategy),
    ));
    if plan.ffprobe.is_none() {
        log_state(&state, "未找到 ffprobe：时长、音频检测和精确进度会降级。".to_string());
    }

    thread::scope(|scope| {
        for _ in 0..workers {
            let plan_ref = &plan;
            let state_ref = state.clone();
            let cancel_ref = cancel.clone();
            let next_ref = next_index.clone();
            scope.spawn(move || loop {
                if cancel_ref.load(Ordering::SeqCst) {
                    break;
                }
                let offset = next_ref.fetch_add(1, Ordering::SeqCst) as usize;
                if offset >= plan_ref.videos.len() {
                    break;
                }
                let video = &plan_ref.videos[offset];
                let index = offset as u32 + 1;
                let source_stem = video.file_stem().and_then(|name| name.to_str());
                let output_name = common_output_name(
                    plan_ref.config.enable_auto_naming,
                    plan_ref.config.naming_use_source_name,
                    &plan_ref.config.naming_date,
                    &plan_ref.config.naming_part1,
                    &plan_ref.config.naming_part2,
                    &plan_ref.config.naming_part3,
                    &plan_ref.config.naming_part4,
                    plan_ref.config.naming_seq_digits,
                    index,
                    source_stem,
                    "overlay",
                );
                let Some(out_file) = resolve_output_path_with_strategy(&plan_ref.output.join(output_name.clone()), &plan_ref.config.conflict_strategy) else {
                    log_state(&state_ref, format!("[{index}] 输出已存在，按 skip 策略跳过：{output_name}"));
                    mark_completed(&state_ref, index, format!("跳过：{output_name}"));
                    continue;
                };
                log_state(&state_ref, format!("[{index}] 开始背景合成：{} -> {}", file_name(video), file_name(&out_file)));
                if plan_ref.config.keep_audio {
                    match plan_ref.ffprobe.as_deref() {
                        Some(ffprobe) if !plan_ref.probes.get(ffprobe, video).has_audio => log_state(&state_ref, format!("[{index}] 该视频无音频，将输出无声视频：{}", file_name(video))),
                        None => log_state(&state_ref, format!("[{index}] 未找到 ffprobe，无法预检音频：{}", file_name(video))),
                        _ => {}
                    }
                }
                let staging = staging_path(&out_file);
                let result = run_overlay_ffmpeg(plan_ref, video, &staging, index, total, &state_ref, &cancel_ref)
                    .and_then(|_| publish_output(&staging, &out_file, &cancel_ref));
                if result.is_err() { let _ = fs::remove_file(&staging); }
                match result {
                    Ok(()) => mark_completed(&state_ref, index, file_name(&out_file)),
                    Err(err) => {
                        if cancel_ref.load(Ordering::SeqCst) {
                            log_state(&state_ref, format!("[{index}] 已取消当前 FFmpeg：{}", file_name(video)));
                            break;
                        }
                        log_state(&state_ref, err.chars().take(3000).collect::<String>());
                        mark_failed(&state_ref, index, format!("[{index}] 背景合成失败：{}", file_name(video)));
                    }
                }
            });
        }
    });

    if let Ok(mut status) = state.lock() {
        status.running = false;
        if cancel.load(Ordering::SeqCst) {
            status.cancelled = true;
            status.status = "已取消".to_string();
        } else if status.failed > 0 {
            status.status = "已完成，有失败".to_string();
        } else {
            status.status = "已完成".to_string();
        }
        update_progress(&mut status);
        let completed = status.completed;
        let failed = status.failed;
        let total = status.total;
        push_log(&mut status, format!("任务结束：完成 {completed}，失败 {failed}，总计 {total}。"));
    }
}

fn run_overlay_ffmpeg(
    plan: &OverlayPlan,
    video: &Path,
    out_file: &Path,
    index: u32,
    total: u32,
    state: &Arc<Mutex<RenderTaskStatus>>,
    cancel: &Arc<AtomicBool>,
) -> Result<(), String> {
    let (canvas_w, canvas_h) = plan.config.orientation.dimensions();
    let x = plan.config.x.clamp(-canvas_w, canvas_w);
    let y = plan.config.y.clamp(-canvas_h, canvas_h);
    let w = even_dimension(plan.config.width.max(2).min((canvas_w * 2) as u32));
    let h = even_dimension(plan.config.height.max(2).min((canvas_h * 2) as u32));
    let fps = plan.config.fps.clamp(1, 120);
    let crf = plan.config.crf.min(51) as u8;
    let preset = match plan.config.preset.as_str() {
        "ultrafast" | "superfast" | "veryfast" | "faster" | "fast" | "medium" | "slow" => plan.config.preset.as_str(),
        _ => "medium",
    };
    let video_filter = if plan.config.mode == "contain" {
        format!("[1:v]scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black[vid]")
    } else {
        format!("[1:v]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}[vid]")
    };
    let filter_complex = format!(
        "[0:v]scale={canvas_w}:{canvas_h}:force_original_aspect_ratio=increase,crop={canvas_w}:{canvas_h},fps={fps},format=rgba[bg];{video_filter};[bg][vid]overlay={x}:{y}:format=auto,fps={fps},format=yuv420p[v]"
    );

    let mut cmd = Command::new(&plan.ffmpeg);
    cmd.args(["-hide_banner", "-loglevel", "error", "-y", "-loop", "1"]);
    cmd.arg("-i").arg(&plan.frame);
    cmd.arg("-i").arg(video);
    cmd.args(["-filter_complex", &filter_complex, "-map", "[v]"]);
    if plan.config.keep_audio {
        cmd.args(["-map", "1:a?"]);
    }
    append_overlay_encoder_args(&mut cmd, encoder_for_job(&plan.config.encoder, index), preset, crf);
    cmd.args(["-movflags", "+faststart"]);
    if plan.config.keep_audio {
        cmd.args(["-c:a", "aac", "-b:a", "160k"]);
    } else {
        cmd.arg("-an");
    }
    cmd.args(["-shortest", "-progress", "pipe:1", "-nostats"]);
    cmd.arg(out_file);

    run_progress_cmd(cmd, &plan.probes, plan.ffprobe.as_deref(), video, index, total, state, cancel)
}

fn run_progress_cmd(
    cmd: Command,
    probes: &crate::media::ProbeCache,
    ffprobe: Option<&Path>,
    video: &Path,
    index: u32,
    total: u32,
    state: &Arc<Mutex<RenderTaskStatus>>,
    cancel: &Arc<AtomicBool>,
) -> Result<(), String> {
    let duration = ffprobe.map(|path| probes.get(path, video).duration).unwrap_or(0.0);
    let output = crate::process::run(cmd, cancel, None, |line| {
        if duration > 0.0 && line.starts_with("out_time_us=") {
            if let Some(value) = line.split('=').nth(1).and_then(|v| v.parse::<f64>().ok()) {
                update_running_progress(state, index, total, value / 1_000_000.0 / duration);
            }
        }
    })?;
    if output.status.success() { Ok(()) }
    else { Err(format!("FFmpeg 执行失败：\n{}", output.stderr.chars().take(3000).collect::<String>())) }
}

fn staging_path(output: &Path) -> PathBuf {
    let stem = output.file_stem().unwrap_or_default().to_string_lossy();
    let extension = output.extension().unwrap_or_default().to_string_lossy();
    output.with_file_name(format!(".{stem}.{}.partial.{extension}", next_task_id()))
}

fn publish_output(staging: &Path, output: &Path, cancel: &AtomicBool) -> Result<(), String> {
    if cancel.load(Ordering::SeqCst) { return Err("任务已取消。".into()); }
    fs::rename(staging, output).map_err(|error| format!("无法保存输出文件：{error}"))
}

fn ensure_output_writable(output: &Path) -> Result<(), String> {
    let test_path = output.join(format!(".write_test_{}.tmp", unix_millis()));
    fs::write(&test_path, b"test").map_err(|err| format!("输出目录不可写：{err}"))?;
    let _ = fs::remove_file(test_path);
    Ok(())
}

fn even_dimension(value: u32) -> u32 {
    if value % 2 == 0 { value } else { value + 1 }
}

fn run_render_task(plan: RenderPlan, state: Arc<Mutex<RenderTaskStatus>>, cancel: Arc<AtomicBool>) {
    let (output_w, output_h) = plan.config.orientation.dimensions();
    log_state(&state, format!("批量混剪输出：{output_w}x{output_h}。"));
    let temp_root = plan.output.join("_temp_video_mix");
    let _ = fs::create_dir_all(&temp_root);

    let max_unique = max_unique_count(
        plan.videos.len() as u128,
        plan.config.segment_count as u128,
        plan.config.allow_repeat_inside_one_video,
    );
    log_state(&state, format!("理论不重复组合数：{}。", max_unique));
    let workers = worker_count(&plan);
    crate::diagnostic_log::event(&format!(
        "mix workers={workers}, outputs={}, segments={}, encoder={}, concurrency={}, cleanup_temp={}, available_memory_mib={:?}",
        plan.config.output_count,
        plan.config.segment_count,
        plan.config.encoder,
        plan.config.concurrency_mode,
        plan.config.cleanup_temp,
        available_memory_bytes().map(|bytes| bytes / (1024 * 1024)),
    ));
    let mut batch = Vec::new();
    for index in 1..=plan.config.output_count {
        if cancel.load(Ordering::SeqCst) {
            log_state(&state, "任务已取消，停止创建后续视频。".to_string());
            break;
        }

        let combo = pick_combo(&plan.videos, plan.config.segment_count as usize, plan.config.allow_repeat_inside_one_video, index - 1);
        let repeat_index = if max_unique > 0 { ((index as u128 - 1) / max_unique) + 1 } else { 1 };
        let is_repeat = repeat_index > 1;
        let output_name = output_name(&plan.config, index);
        let Some(output_path) = resolve_output_path_with_strategy(&plan.output.join(&output_name), &plan.config.conflict_strategy) else {
            log_state(&state, format!("[{index}] 输出已存在，按 skip 策略跳过：{output_name}"));
            mark_completed(&state, index, format!("跳过：{output_name}"));
            continue;
        };
        let actual_output_name = output_path
            .file_name()
            .and_then(|name| name.to_str())
            .unwrap_or(&output_name)
            .to_string();
        let job_dir = temp_root.join(format!("{:04}_{}", index, unix_millis()));

        if let Err(err) = fs::create_dir_all(&job_dir) {
            mark_failed(&state, index, format!("[{index}] 临时目录创建失败：{err}"));
            continue;
        }
        batch.push(RenderJob {
            index,
            combo,
            is_repeat,
            repeat_index,
            output_path,
            actual_output_name,
            job_dir,
            encoder: encoder_for_job(&plan.config.encoder, index),
        });

        if batch.len() >= workers {
            run_job_batch(&plan, &state, &cancel, std::mem::take(&mut batch));
        }
    }
    if !batch.is_empty() {
        run_job_batch(&plan, &state, &cancel, batch);
    }

    if plan.config.cleanup_temp {
        cleanup_mix_temp(&state, &temp_root, "mix temp root");
    }

    if let Ok(mut status) = state.lock() {
        status.running = false;
        if cancel.load(Ordering::SeqCst) {
            status.cancelled = true;
            status.status = "已取消".to_string();
        } else if status.failed > 0 {
            status.status = "已完成，有失败".to_string();
        } else {
            status.status = "已完成".to_string();
        }
        update_progress(&mut status);
        let completed = status.completed;
        let failed = status.failed;
        let total = status.total;
        push_log(&mut status, format!("任务结束：完成 {completed}，失败 {failed}，总计 {total}。"));
    }
}

fn run_job_batch(
    plan: &RenderPlan,
    state: &Arc<Mutex<RenderTaskStatus>>,
    cancel: &Arc<AtomicBool>,
    jobs: Vec<RenderJob>,
) {
    thread::scope(|scope| {
        for job in jobs {
            let state = state.clone();
            let cancel = cancel.clone();
            scope.spawn(move || process_render_job(plan, job, state, cancel));
        }
    });
}

fn process_render_job(
    plan: &RenderPlan,
    job: RenderJob,
    state: Arc<Mutex<RenderTaskStatus>>,
    cancel: Arc<AtomicBool>,
) {
    if cancel.load(Ordering::SeqCst) {
        if plan.config.cleanup_temp {
            cleanup_mix_temp(&state, &job.job_dir, &format!("mix job {}", job.index));
        }
        return;
    }

    let variant = if job.is_repeat && plan.config.enable_dedup_when_combo_repeated {
        Variant::dedup(job.index)
    } else {
        Variant::normal()
    };
    let (effective_sequence, first_pick, top_picks, tail_pick) = build_effective_sequence(&plan, &job.combo, job.index);
    crate::diagnostic_log::event(&format!(
        "mix job {} started, parts={}, encoder={}",
        job.index,
        effective_sequence.len(),
        job.encoder.label(),
    ));
    log_state(&state, format!("[{}] 开始：主组合：{}；编码器：{}", job.index, combo_names(&job.combo), job.encoder.label()));
    if let Some(path) = first_pick.as_ref() {
        log_state(&state, format!("[{}] 首视频：{}", job.index, file_name(path)));
    }
    if !top_picks.is_empty() {
        log_state(&state, format!("[{}] top 插片：{}", job.index, combo_names(&top_picks)));
    }
    if let Some(path) = tail_pick.as_ref() {
        log_state(&state, format!("[{}] 尾视频：{}", job.index, file_name(path)));
    }
    if job.is_repeat {
        if variant.is_dedup {
            log_state(&state, format!("[{}] 组合重复，第 {} 次出现，启用 {}", job.index, job.repeat_index, variant.note));
        } else {
            log_state(&state, format!("[{}] 组合重复，第 {} 次出现，但未启用去重增强。", job.index, job.repeat_index));
        }
    }

    let keep_audio = should_keep_audio(&plan.probes, &plan.ffprobe, &effective_sequence, &state, job.index, plan.config.keep_audio);
    let staged_output = job.job_dir.join("result.mp4");
    let mut part_paths = Vec::new();
    let mut ok = true;

    for (part_index, src) in effective_sequence.iter().enumerate() {
        if cancel.load(Ordering::SeqCst) {
            ok = false;
            break;
        }
        let part_path = job.job_dir.join(format!("part_{:03}.mp4", part_index + 1));
        let cmd = build_preprocess_cmd(&plan.ffmpeg, src, &part_path, &plan.config, &variant, keep_audio, job.encoder);
        crate::diagnostic_log::event(&format!("mix job {} part {} started", job.index, part_index + 1));
        match run_cmd(cmd, &cancel) {
            Ok(()) => {
                crate::diagnostic_log::event(&format!("mix job {} part {} completed", job.index, part_index + 1));
                part_paths.push(part_path);
            }
            Err(err) => {
                crate::diagnostic_log::event(&format!("mix job {} part {} failed: {}", job.index, part_index + 1, diagnostic_error_tail(&err, src, &job.job_dir)));
                ok = false;
                log_state(&state, format!("[{}] 处理素材失败：{}", job.index, file_name(src)));
                log_state(&state, err.chars().take(3000).collect::<String>());
                break;
            }
        }
    }

    if ok && !part_paths.is_empty() {
        let concat_output = if plan.banner.is_some() { job.job_dir.join("merged_before_banner.mp4") } else { staged_output.clone() };
        crate::diagnostic_log::event(&format!("mix job {} concat started", job.index));
        match concat_parts(&plan.ffmpeg, &part_paths, &concat_output, &job.job_dir, &cancel) {
            Ok(()) => {
                crate::diagnostic_log::event(&format!("mix job {} concat completed", job.index));
                if let Some(banner) = plan.banner.as_ref() {
                    crate::diagnostic_log::event(&format!("mix job {} banner started", job.index));
                    if let Err(err) = apply_banner_overlay(&plan.ffmpeg, &concat_output, banner, &staged_output, keep_audio, job.encoder, plan.config.orientation.dimensions().0, &cancel) {
                        crate::diagnostic_log::event(&format!("mix job {} banner failed", job.index));
                        log_state(&state, format!("[{}] 底栏视频覆盖失败：{}", job.index, job.actual_output_name));
                        log_state(&state, err.chars().take(3000).collect::<String>());
                        mark_failed(&state, job.index, String::new());
                        ok = false;
                    }
                }
                if ok {
                    match publish_output(&staged_output, &job.output_path, &cancel) {
                        Ok(()) => {
                            crate::diagnostic_log::event(&format!("mix job {} published", job.index));
                            mark_completed(&state, job.index, job.actual_output_name.clone());
                        }
                        Err(error) => if !cancel.load(Ordering::SeqCst) {
                            crate::diagnostic_log::event(&format!("mix job {} publish failed", job.index));
                            mark_failed(&state, job.index, error);
                        },
                    }
                }
            }
            Err(err) => {
                crate::diagnostic_log::event(&format!("mix job {} concat failed", job.index));
                log_state(&state, format!("[{}] 拼接失败：{}", job.index, job.actual_output_name));
                log_state(&state, err.chars().take(3000).collect::<String>());
                mark_failed(&state, job.index, String::new());
            }
        }
    } else if !cancel.load(Ordering::SeqCst) {
        mark_failed(&state, job.index, String::new());
    }

    if plan.config.cleanup_temp {
        cleanup_mix_temp(&state, &job.job_dir, &format!("mix job {}", job.index));
    }
    crate::diagnostic_log::event(&format!(
        "mix job {} ended, available_memory_mib={:?}",
        job.index,
        available_memory_bytes().map(|bytes| bytes / (1024 * 1024)),
    ));
}

fn cleanup_mix_temp(state: &Arc<Mutex<RenderTaskStatus>>, path: &Path, label: &str) {
    crate::diagnostic_log::event(&format!("{label} cleanup started"));
    match crate::cleanup::remove_dir_all_isolated(path) {
        Ok(()) => crate::diagnostic_log::event(&format!("{label} cleanup completed")),
        Err(error) => {
            crate::diagnostic_log::event(&format!("{label} cleanup failed: {error}"));
            log_state(state, format!("临时文件清理失败，文件保留在输出目录的 _temp_video_mix 中：{error}"));
        }
    }
}

fn diagnostic_error_tail(error: &str, source: &Path, workdir: &Path) -> String {
    let tail = error.chars().rev().take(1200).collect::<String>().chars().rev().collect::<String>();
    tail.replace(source.to_string_lossy().as_ref(), "<source>")
        .replace(workdir.to_string_lossy().as_ref(), "<temp>")
        .replace(['\r', '\n'], " | ")
}

fn build_preprocess_cmd(ffmpeg: &Path, src: &Path, dst: &Path, config: &RenderConfig, variant: &Variant, keep_audio: bool, encoder: EncoderKind) -> Command {
    let mut cmd = Command::new(ffmpeg);
    cmd.args(["-hide_banner", "-loglevel", "error", "-filter_threads", "2", "-y"]);
    if config.trim_start_seconds > 0.0 {
        cmd.args(["-ss", &format!("{:.3}", config.trim_start_seconds)]);
    }
    cmd.arg("-i").arg(src);
    cmd.args(["-map", "0:v:0"]);
    if keep_audio {
        cmd.args(["-map", "0:a:0"]);
    }
    let (output_w, output_h) = config.orientation.dimensions();
    let vf = format!("scale={output_w}:{output_h}:force_original_aspect_ratio=decrease,pad={output_w}:{output_h}:(ow-iw)/2:(oh-ih)/2:black,setsar=1,setpts=PTS/{:.5},fps={}", variant.speed, variant.fps);
    cmd.args(["-vf", &vf]);
    append_video_encoder_args(&mut cmd, encoder, variant.bitrate.as_deref(), variant.crf.unwrap_or(23));
    if encoder == EncoderKind::Cpu {
        cmd.args(["-threads:v", "4"]);
    }
    if encoder != EncoderKind::Cpu || variant.bitrate.is_some() {
        let bitrate = variant.bitrate.as_deref().unwrap_or("3500k");
        let bitrate_num = bitrate.trim_end_matches('k').parse::<u32>().unwrap_or(3500);
        cmd.args(["-b:v", bitrate, "-maxrate", bitrate, "-bufsize", &format!("{}k", bitrate_num * 2)]);
    } else {
        cmd.args(["-crf", &variant.crf.unwrap_or(23).to_string()]);
    }
    if keep_audio {
        if (variant.speed - 1.0).abs() > 0.0001 {
            cmd.args(["-filter:a", &format!("atempo={:.5}", variant.speed)]);
        }
        cmd.args(["-c:a", "aac", "-ar", &variant.audio_rate.to_string(), "-ac", "2", "-b:a", "128k"]);
    } else {
        cmd.arg("-an");
    }
    if variant.is_dedup {
        cmd.args(["-metadata", &format!("mix_variant={}", unix_millis())]);
    }
    cmd.args(["-movflags", "+faststart"]);
    cmd.arg(dst);
    cmd
}

fn concat_parts(ffmpeg: &Path, part_paths: &[PathBuf], output_path: &Path, job_dir: &Path, cancel: &AtomicBool) -> Result<(), String> {
    let list_path = job_dir.join("concat_list.txt");
    let lines = part_paths
        .iter()
        .map(|path| format!("file '{}'", escape_concat_path(path)))
        .collect::<Vec<_>>()
        .join("\n");
    fs::write(&list_path, lines).map_err(|err| err.to_string())?;

    let mut cmd = Command::new(ffmpeg);
    cmd.args(["-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0"]);
    cmd.arg("-i").arg(&list_path);
    cmd.args(["-c", "copy", "-movflags", "+faststart"]);
    cmd.arg(output_path);
    run_cmd(cmd, cancel)
}

fn apply_banner_overlay(ffmpeg: &Path, src: &Path, banner: &Path, dst: &Path, keep_audio: bool, encoder: EncoderKind, output_w: i32, cancel: &AtomicBool) -> Result<(), String> {
    let filter_complex = format!("[1:v]scale={output_w}:-2,setpts=PTS-STARTPTS[bar];[0:v][bar]overlay=(main_w-overlay_w)/2:main_h-overlay_h:format=auto:shortest=0[v]");
    let mut cmd = Command::new(ffmpeg);
    cmd.args(["-hide_banner", "-loglevel", "error", "-y"]);
    cmd.arg("-i").arg(src);
    cmd.args(["-stream_loop", "-1"]);
    cmd.arg("-i").arg(banner);
    cmd.args(["-filter_complex", &filter_complex, "-map", "[v]"]);
    if keep_audio {
        cmd.args(["-map", "0:a?"]);
    }
    append_video_encoder_args(&mut cmd, encoder, Some("3500k"), 22);
    let bitrate = "3500k";
    cmd.args(["-b:v", bitrate, "-maxrate", bitrate, "-bufsize", "7000k"]);
    if keep_audio {
        cmd.args(["-c:a", "copy"]);
    } else {
        cmd.arg("-an");
    }
    cmd.args(["-shortest", "-movflags", "+faststart"]);
    cmd.arg(dst);
    run_cmd(cmd, cancel)
}

fn run_cmd(cmd: Command, cancel: &AtomicBool) -> Result<(), String> {
    let output = crate::process::run(cmd, cancel, None, |_| {})?;
    if output.status.success() { Ok(()) }
    else { Err(output.stderr.trim().to_owned()) }
}

fn append_overlay_encoder_args(cmd: &mut Command, encoder: EncoderKind, preset: &str, crf: u8) {
    match encoder {
        EncoderKind::Cpu => {
            cmd.args(["-c:v", "libx264", "-preset", preset, "-crf", &crf.to_string(), "-pix_fmt", "yuv420p"]);
        }
        EncoderKind::Nvidia => {
            let cq = crf.clamp(1, 51).to_string();
            cmd.args(["-c:v", "h264_nvenc", "-preset", "fast", "-cq", &cq, "-pix_fmt", "yuv420p"]);
        }
        EncoderKind::Intel => {
            let qp = crf.clamp(1, 51).to_string();
            cmd.args(["-c:v", "h264_qsv", "-preset", "veryfast", "-global_quality", &qp, "-pix_fmt", "yuv420p"]);
        }
        EncoderKind::Amd => {
            let qp = crf.clamp(1, 51).to_string();
            cmd.args(["-c:v", "h264_amf", "-quality", "speed", "-qp_i", &qp, "-qp_p", &qp, "-pix_fmt", "yuv420p"]);
        }
    }
}

fn append_watermark_encoder_args(cmd: &mut Command, output: &Path, encoder: EncoderKind) {
    let extension = output.extension().and_then(|ext| ext.to_str()).unwrap_or("").to_ascii_lowercase();
    match extension.as_str() {
        "webm" => {
            cmd.args(["-c:v", "libvpx-vp9", "-deadline", "good", "-cpu-used", "4", "-crf", "30", "-b:v", "0", "-pix_fmt", "yuv420p"]);
        }
        "wmv" => {
            cmd.args(["-c:v", "wmv2", "-q:v", "3", "-pix_fmt", "yuv420p"]);
        }
        _ => append_overlay_encoder_args(cmd, encoder, "veryfast", 21),
    }
}

fn append_dedup_encoder_args(cmd: &mut Command, output: &Path, encoder: EncoderKind, bitrate: Option<&str>, crf: u8) {
    let extension = output.extension().and_then(|ext| ext.to_str()).unwrap_or("").to_ascii_lowercase();
    match extension.as_str() {
        "webm" => {
            cmd.args(["-c:v", "libvpx-vp9", "-deadline", "good", "-cpu-used", "4", "-crf", &crf.to_string(), "-b:v", "0", "-pix_fmt", "yuv420p"]);
        }
        "wmv" => {
            cmd.args(["-c:v", "wmv2", "-q:v", "3", "-pix_fmt", "yuv420p"]);
        }
        _ => match encoder {
            EncoderKind::Cpu => {
                cmd.args(["-c:v", "libx264", "-preset", "veryfast"]);
                if let Some(bitrate) = bitrate {
                    cmd.args(["-b:v", bitrate, "-maxrate", bitrate, "-bufsize", bitrate]);
                } else {
                    cmd.args(["-crf", &crf.to_string()]);
                }
                cmd.args(["-pix_fmt", "yuv420p"]);
            }
            EncoderKind::Nvidia => {
                cmd.args(["-c:v", "h264_nvenc", "-preset", "fast"]);
                if let Some(bitrate) = bitrate {
                    cmd.args(["-b:v", bitrate, "-maxrate", bitrate, "-bufsize", bitrate]);
                } else {
                    cmd.args(["-cq", &crf.clamp(1, 51).to_string()]);
                }
                cmd.args(["-pix_fmt", "yuv420p"]);
            }
            EncoderKind::Intel => {
                cmd.args(["-c:v", "h264_qsv", "-preset", "veryfast"]);
                if let Some(bitrate) = bitrate {
                    cmd.args(["-b:v", bitrate]);
                } else {
                    cmd.args(["-global_quality", &crf.clamp(1, 51).to_string()]);
                }
                cmd.args(["-pix_fmt", "yuv420p"]);
            }
            EncoderKind::Amd => {
                cmd.args(["-c:v", "h264_amf", "-quality", "speed"]);
                if let Some(bitrate) = bitrate {
                    cmd.args(["-b:v", bitrate]);
                } else {
                    let qp = crf.clamp(1, 51).to_string();
                    cmd.args(["-qp_i", &qp, "-qp_p", &qp]);
                }
                cmd.args(["-pix_fmt", "yuv420p"]);
            }
        },
    }
}

fn append_dedup_audio_args(cmd: &mut Command, output: &Path) {
    let extension = output.extension().and_then(|ext| ext.to_str()).unwrap_or("").to_ascii_lowercase();
    match extension.as_str() {
        "webm" => {
            cmd.args(["-c:a", "libopus", "-b:a", "128k"]);
        }
        "wmv" => {
            cmd.args(["-c:a", "wmav2", "-b:a", "160k"]);
        }
        _ => {
            cmd.args(["-c:a", "aac", "-b:a", "160k"]);
        }
    }
}

fn supports_faststart(output: &Path) -> bool {
    matches!(
        output.extension().and_then(|ext| ext.to_str()).map(|ext| ext.to_ascii_lowercase()),
        Some(ext) if matches!(ext.as_str(), "mp4" | "mov" | "m4v")
    )
}

fn overlay_worker_count(plan: &OverlayPlan) -> usize {
    let total = plan.videos.len().max(1);
    let manual = plan.config.workers.max(1) as usize;
    let cores = thread::available_parallelism().map(|n| n.get()).unwrap_or(4).max(1);
    let auto = match plan.config.encoder.as_str() {
        "cpu_libx264" => (cores / 2).max(1),
        "mixed_nvidia" | "mixed_intel" | "mixed_amd" => (cores / 2).max(2),
        "auto" | "nvenc_h264" | "qsv_h264" | "amf_h264" | "nvidia_nvenc" | "intel_qsv" | "amd_amf" => 2.max(cores / 3),
        _ => manual,
    };
    let selected = match plan.config.concurrency_mode.as_str() {
        "safe" => (((auto as f64) * 0.75).floor().max(1.0) as usize).min(manual),
        "manual" => manual,
        _ => auto.min(manual),
    };
    selected.min(4).min(total)
}

fn watermark_worker_count(plan: &WatermarkPlan) -> usize {
    let total = plan.videos.len().max(1);
    let manual = plan.config.workers.max(1) as usize;
    let cores = thread::available_parallelism().map(|n| n.get()).unwrap_or(4).max(1);
    let auto = match plan.config.encoder.as_str() {
        "cpu_libx264" => (cores / 2).max(1),
        "mixed_nvidia" | "mixed_intel" | "mixed_amd" => (cores / 2).max(2),
        "auto" | "nvenc_h264" | "qsv_h264" | "amf_h264" | "nvidia_nvenc" | "intel_qsv" | "amd_amf" => 2.max(cores / 3),
        _ => manual,
    };
    let selected = match plan.config.concurrency_mode.as_str() {
        "safe" => (((auto as f64) * 0.75).floor().max(1.0) as usize).min(manual),
        "auto" => auto.min(manual),
        _ => manual,
    };
    selected.min(4).min(total)
}

fn dedup_worker_count(plan: &DedupPlan) -> usize {
    let total = plan.videos.len().max(1);
    let manual = plan.config.workers.max(1) as usize;
    let cores = thread::available_parallelism().map(|n| n.get()).unwrap_or(4).max(1);
    let auto = match plan.config.encoder.as_str() {
        "cpu_libx264" => (cores / 2).max(1),
        "mixed_nvidia" | "mixed_intel" | "mixed_amd" => (cores / 2).max(2),
        "auto" | "nvenc_h264" | "qsv_h264" | "amf_h264" | "nvidia_nvenc" | "intel_qsv" | "amd_amf" => 2.max(cores / 3),
        _ => manual,
    };
    let selected = match plan.config.concurrency_mode.as_str() {
        "safe" => (((auto as f64) * 0.75).floor().max(1.0) as usize).min(manual),
        "auto" => auto.min(manual),
        _ => manual,
    };
    selected.min(4).min(total)
}

fn append_video_encoder_args(cmd: &mut Command, encoder: EncoderKind, bitrate: Option<&str>, crf: u8) {
    let _ = (bitrate, crf);
    match encoder {
        EncoderKind::Cpu => {
            cmd.args(["-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p"]);
        }
        EncoderKind::Nvidia => {
            cmd.args(["-c:v", "h264_nvenc", "-preset", "fast", "-pix_fmt", "yuv420p"]);
        }
        EncoderKind::Intel => {
            cmd.args(["-c:v", "h264_qsv", "-preset", "veryfast", "-pix_fmt", "yuv420p"]);
        }
        EncoderKind::Amd => {
            cmd.args(["-c:v", "h264_amf", "-quality", "speed", "-pix_fmt", "yuv420p"]);
        }
    }
}

fn validate_encoder(ffmpeg: &Path, mode: &str) -> Result<(), String> {
    let required = match mode {
        "cpu_libx264" => return Ok(()),
        "auto" | "nvidia_nvenc" | "mixed_nvidia" | "nvenc_h264" => "h264_nvenc",
        "intel_qsv" | "mixed_intel" | "qsv_h264" => "h264_qsv",
        "amd_amf" | "mixed_amd" | "amf_h264" => "h264_amf",
        _ => return Err(format!("未知编码模式：{mode}")),
    };
    let text = command_text(ffmpeg, &["-hide_banner", "-encoders"])?;
    if text.contains(required) {
        Ok(())
    } else {
        Err(format!("当前 FFmpeg 不支持 {required}，请切回 CPU 或更换包含该硬件编码器的 FFmpeg。"))
    }
}

fn command_text(path: &Path, args: &[&str]) -> Result<String, String> {
    let mut cmd = Command::new(path);
    cmd.args(args);
    let output = crate::process::run(cmd, &AtomicBool::new(false), Some(std::time::Duration::from_secs(10)), |_| {})?;
    if !output.status.success() { return Err(output.stderr); }
    Ok(output.stdout + &output.stderr)
}

fn encoder_for_job(mode: &str, index: u32) -> EncoderKind {
    match mode {
        "nvidia_nvenc" | "nvenc_h264" => EncoderKind::Nvidia,
        "intel_qsv" | "qsv_h264" => EncoderKind::Intel,
        "amd_amf" | "amf_h264" => EncoderKind::Amd,
        "auto" => match index % 3 { 0 => EncoderKind::Nvidia, 1 => EncoderKind::Intel, _ => EncoderKind::Amd },
        "mixed_nvidia" => if index % 2 == 0 { EncoderKind::Nvidia } else { EncoderKind::Cpu },
        "mixed_intel" => if index % 2 == 0 { EncoderKind::Intel } else { EncoderKind::Cpu },
        "mixed_amd" => if index % 2 == 0 { EncoderKind::Amd } else { EncoderKind::Cpu },
        _ => EncoderKind::Cpu,
    }
}

fn encoder_mode_label(mode: &str) -> String {
    match mode {
        "nvidia_nvenc" | "nvenc_h264" => "NVIDIA GPU - h264_nvenc".to_string(),
        "intel_qsv" | "qsv_h264" => "Intel 核显 - h264_qsv".to_string(),
        "amd_amf" | "amf_h264" => "AMD GPU - h264_amf".to_string(),
        "auto" => "自动硬件编码".to_string(),
        "mixed_nvidia" => "混合 CPU + NVIDIA".to_string(),
        "mixed_intel" => "混合 CPU + Intel 核显".to_string(),
        "mixed_amd" => "混合 CPU + AMD".to_string(),
        _ => "CPU - libx264".to_string(),
    }
}

fn worker_count(plan: &RenderPlan) -> usize {
    let output_count = plan.config.output_count.max(1) as usize;
    let manual = plan.config.workers.max(1) as usize;
    let cores = thread::available_parallelism().map(|n| n.get()).unwrap_or(4).max(1);
    let auto = match plan.config.encoder.as_str() {
        "cpu_libx264" => (cores / 2).max(1),
        "mixed_nvidia" | "mixed_intel" | "mixed_amd" => (cores / 2).max(2),
        "nvidia_nvenc" | "intel_qsv" | "amd_amf" => 2.max(cores / 3),
        _ => manual,
    };
    let selected = match plan.config.concurrency_mode.as_str() {
        "auto" => auto.min(manual),
        "safe" => (((auto as f64) * 0.75).floor().max(1.0) as usize).min(manual),
        _ => manual,
    };
    limit_mix_workers_by_memory(selected.min(4).min(output_count), available_memory_bytes())
}

fn limit_mix_workers_by_memory(requested: usize, available: Option<u64>) -> usize {
    const GIB: u64 = 1024 * 1024 * 1024;
    // Leave space for Windows, WebView2, source decoding and other applications.
    let Some(available) = available else { return requested.max(1); };
    let slots = available.saturating_sub(2 * GIB) / (3 * GIB);
    requested.min((slots as usize).max(1))
}

#[cfg(windows)]
fn available_memory_bytes() -> Option<u64> {
    #[repr(C)]
    struct MemoryStatus {
        length: u32,
        load: u32,
        total_phys: u64,
        avail_phys: u64,
        total_page_file: u64,
        avail_page_file: u64,
        total_virtual: u64,
        avail_virtual: u64,
        avail_extended_virtual: u64,
    }
    #[link(name = "kernel32")]
    extern "system" {
        fn GlobalMemoryStatusEx(status: *mut MemoryStatus) -> i32;
    }
    let mut status = MemoryStatus {
        length: std::mem::size_of::<MemoryStatus>() as u32,
        load: 0,
        total_phys: 0,
        avail_phys: 0,
        total_page_file: 0,
        avail_page_file: 0,
        total_virtual: 0,
        avail_virtual: 0,
        avail_extended_virtual: 0,
    };
    // Windows writes the entire repr(C) structure after its length is set.
    (unsafe { GlobalMemoryStatusEx(&mut status) } != 0).then_some(status.avail_phys)
}

#[cfg(not(windows))]
fn available_memory_bytes() -> Option<u64> {
    None
}

fn concurrency_label(mode: &str) -> &'static str {
    match mode {
        "auto" => "自动",
        "safe" => "安全模式",
        _ => "手动",
    }
}

fn conflict_label(strategy: &str) -> &'static str {
    match strategy {
        "overwrite" => "覆盖",
        "suffix" => "自动后缀",
        _ => "跳过已存在",
    }
}

fn pick_combo(files: &[PathBuf], segment_count: usize, allow_repeat: bool, ordinal: u32) -> Vec<PathBuf> {
    if files.is_empty() || segment_count == 0 {
        return Vec::new();
    }
    if allow_repeat {
        let n = files.len();
        let mut value = ordinal as usize;
        return (0..segment_count)
            .map(|_| {
                let path = files[value % n].clone();
                value /= n;
                path
            })
            .collect();
    }

    let n = files.len();
    let mut used = vec![false; n];
    let mut value = ordinal as usize;
    let mut result = Vec::with_capacity(segment_count);
    for step in 0..segment_count {
        let remaining = n - step;
        let mut pick = value % remaining;
        value /= remaining;
        for (index, path) in files.iter().enumerate() {
            if used[index] {
                continue;
            }
            if pick == 0 {
                used[index] = true;
                result.push(path.clone());
                break;
            }
            pick -= 1;
        }
    }
    result
}

fn build_effective_sequence(
    plan: &RenderPlan,
    combo: &[PathBuf],
    index: u32,
) -> (Vec<PathBuf>, Option<PathBuf>, Vec<PathBuf>, Option<PathBuf>) {
    let mut sequence = Vec::new();
    let first_pick = pick_from(&plan.first_videos, index.wrapping_mul(7).wrapping_add(1));
    if let Some(path) = first_pick.as_ref() {
        sequence.push(path.clone());
    }

    let mut top_picks = Vec::new();
    for (part_index, main) in combo.iter().enumerate() {
        sequence.push(main.clone());
        if let Some(top) = pick_from(&plan.top_videos, index.wrapping_mul(11).wrapping_add(part_index as u32)) {
            sequence.push(top.clone());
            top_picks.push(top);
        }
    }

    let tail_pick = pick_from(&plan.tail_videos, index.wrapping_mul(13).wrapping_add(3));
    if let Some(path) = tail_pick.as_ref() {
        sequence.push(path.clone());
    }

    (sequence, first_pick, top_picks, tail_pick)
}

fn pick_from(files: &[PathBuf], seed: u32) -> Option<PathBuf> {
    if files.is_empty() {
        return None;
    }
    Some(files[seed as usize % files.len()].clone())
}

fn output_name(config: &RenderConfig, index: u32) -> String {
    common_output_name(
        config.enable_auto_naming,
        config.naming_use_source_name,
        &config.naming_date,
        &config.naming_part1,
        &config.naming_part2,
        &config.naming_part3,
        &config.naming_part4,
        config.naming_seq_digits,
        index,
        None,
        "mix",
    )
}

fn common_output_name(
    enabled: bool,
    use_source_name: bool,
    date: &str,
    part1: &str,
    part2: &str,
    part3: &str,
    part4: &str,
    seq_digits: u32,
    index: u32,
    source_stem: Option<&str>,
    fallback_stem: &str,
) -> String {
    if !enabled {
        return format!("{fallback_stem}_{index:04}.mp4");
    }
    let mut parts = Vec::new();
    for value in [date, part1] {
        let value = sanitize_filename_part(value);
        if !value.is_empty() {
            parts.push(value);
        }
    }
    if use_source_name {
        if let Some(stem) = source_stem {
            let stem = sanitize_filename_part(stem);
            if !stem.is_empty() {
                parts.push(stem);
            }
        }
    }
    for value in [part2, part3, part4] {
        let value = sanitize_filename_part(value);
        if !value.is_empty() {
            parts.push(value);
        }
    }
    if parts.is_empty() {
        parts.push(fallback_stem.to_string());
    }
    parts.push(format!("{:0width$}", index, width = seq_digits.max(1) as usize));
    format!("{}.mp4", parts.join("-"))
}

fn resolve_output_folder(source: &Path, configured: &str) -> PathBuf {
    let trimmed = configured.trim();
    if trimmed.is_empty() {
        return source.join("output");
    }
    let selected = PathBuf::from(trimmed);
    if same_path(&selected, source) {
        source.join("output")
    } else {
        selected
    }
}

fn resolve_output_path(path: &Path) -> Option<PathBuf> {
    if !path.exists() {
        return Some(path.to_path_buf());
    }

    let stem = path.file_stem().and_then(|name| name.to_str()).unwrap_or("mix");
    let ext = path.extension().and_then(|name| name.to_str()).unwrap_or("mp4");
    let parent = path.parent().unwrap_or_else(|| Path::new(""));

    for index in 1..10_000 {
        let candidate = parent.join(format!("{stem}_{index:03}.{ext}"));
        if !candidate.exists() {
            return Some(candidate);
        }
    }

    Some(parent.join(format!("{stem}_{}.{ext}", unix_millis())))
}

fn resolve_output_path_with_strategy(path: &Path, strategy: &str) -> Option<PathBuf> {
    match strategy {
        "overwrite" => Some(path.to_path_buf()),
        "skip" if path.exists() => None,
        _ => resolve_output_path(path),
    }
}

fn scan_videos(folder: &Path) -> Vec<PathBuf> {
    let Ok(entries) = fs::read_dir(folder) else {
        return Vec::new();
    };
    let mut files = entries
        .filter_map(Result::ok)
        .map(|entry| entry.path())
        .filter(|path| path.is_file())
        .filter(|path| {
            path.extension()
                .and_then(|ext| ext.to_str())
                .map(|ext| VIDEO_EXTS.contains(&ext.to_ascii_lowercase().as_str()))
                .unwrap_or(false)
        })
        .collect::<Vec<_>>();
    files.sort_by_key(|path| path.file_name().map(|name| name.to_string_lossy().to_ascii_lowercase()));
    files
}

fn scan_main_videos(folder: &Path, banner_file: Option<&Path>) -> Vec<PathBuf> {
    scan_videos(folder)
        .into_iter()
        .filter(|path| !is_banner_candidate(path))
        .filter(|path| banner_file.map(|banner| !same_path(path, banner)).unwrap_or(true))
        .collect()
}

fn resolve_banner(source: &Path, config: &RenderConfig) -> Option<PathBuf> {
    if !config.enable_banner_overlay {
        return None;
    }
    if !config.banner_file.trim().is_empty() {
        return Some(PathBuf::from(config.banner_file.trim()));
    }
    scan_videos(source).into_iter().find(|path| is_banner_candidate(path))
}

fn is_banner_candidate(path: &Path) -> bool {
    let Some(stem) = path.file_stem().and_then(|name| name.to_str()) else {
        return false;
    };
    let name = stem.to_ascii_lowercase();
    BANNER_KEYWORDS.iter().any(|keyword| name.contains(&keyword.to_ascii_lowercase()))
}

fn same_path(left: &Path, right: &Path) -> bool {
    let left = left.canonicalize().unwrap_or_else(|_| left.to_path_buf());
    let right = right.canonicalize().unwrap_or_else(|_| right.to_path_buf());
    left == right
}

fn find_binary(app: &tauri::AppHandle, name: &str, _source: &Path) -> Option<PathBuf> {
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

fn should_keep_audio(
    probes: &crate::media::ProbeCache,
    ffprobe: &Option<PathBuf>,
    sequence: &[PathBuf],
    state: &Arc<Mutex<RenderTaskStatus>>,
    index: u32,
    requested: bool,
) -> bool {
    if !requested {
        return false;
    }
    let Some(ffprobe) = ffprobe.as_ref() else {
        log_state(state, format!("[{index}] 找不到 ffprobe，本条自动输出无音频。"));
        return false;
    };
    let missing = sequence
        .iter()
        .filter(|path| !probes.get(ffprobe, path).has_audio)
        .map(|path| file_name(path))
        .collect::<Vec<_>>();
    if missing.is_empty() {
        log_state(state, format!("[{index}] 音频检测：所有有效片段都有音频，输出将保留音频。"));
        true
    } else {
        log_state(state, format!("[{index}] 有素材缺少音频或 ffprobe 检测失败，本条自动输出无音频。"));
        log_state(state, format!("[{index}] 未检测到音频：{}", missing.into_iter().take(8).collect::<Vec<_>>().join("、")));
        false
    }
}

fn which_on_path(name: &str) -> Option<PathBuf> {
    let path_var = std::env::var_os("PATH")?;
    std::env::split_paths(&path_var)
        .map(|folder| folder.join(name))
        .find(|candidate| candidate.exists() && candidate.is_file())
}

fn max_unique_count(n: u128, k: u128, allow_repeat: bool) -> u128 {
    if n == 0 || k == 0 {
        return 0;
    }
    if allow_repeat {
        return n.saturating_pow(k as u32);
    }
    if k > n {
        return 0;
    }
    let mut result = 1_u128;
    for i in 0..k {
        result = result.saturating_mul(n - i);
    }
    result
}

fn escape_concat_path(path: &Path) -> String {
    path.canonicalize()
        .unwrap_or_else(|_| path.to_path_buf())
        .to_string_lossy()
        .replace('\\', "/")
        .replace('\'', "'\\''")
}

fn sanitize_filename_part(value: &str) -> String {
    let invalid = ['<', '>', ':', '"', '/', '\\', '|', '?', '*'];
    value
        .trim()
        .chars()
        .filter(|ch| !invalid.contains(ch) && !ch.is_control())
        .collect::<String>()
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
        .trim_matches(['.', ' '])
        .to_string()
}

fn combo_names(paths: &[PathBuf]) -> String {
    paths
        .iter()
        .map(|path| file_name(path))
        .collect::<Vec<_>>()
        .join(" + ")
}

fn file_name(path: &Path) -> String {
    path.file_name()
        .and_then(|name| name.to_str())
        .unwrap_or("素材")
        .to_string()
}

fn unix_millis() -> u128 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_millis())
        .unwrap_or(0)
}

fn mark_completed(state: &Arc<Mutex<RenderTaskStatus>>, index: u32, output_name: String) {
    if let Ok(mut status) = state.lock() {
        status.in_flight.remove(&index);
        status.completed = status.completed.saturating_add(1);
        push_log(&mut status, format!("完成：{output_name}"));
        update_progress(&mut status);
    }
}

fn mark_failed(state: &Arc<Mutex<RenderTaskStatus>>, index: u32, message: String) {
    if let Ok(mut status) = state.lock() {
        status.in_flight.remove(&index);
        status.failed = status.failed.saturating_add(1);
        if !message.is_empty() {
            push_log(&mut status, message);
        }
        update_progress(&mut status);
    }
}

fn log_state(state: &Arc<Mutex<RenderTaskStatus>>, message: String) {
    if let Ok(mut status) = state.lock() {
        push_log(&mut status, message);
    }
}

fn update_progress(status: &mut RenderTaskStatus) {
    if status.total == 0 {
        status.progress = 0;
        return;
    }
    let done = status.completed.saturating_add(status.failed).min(status.total);
    let partial: f64 = status.in_flight.values().sum();
    let value = (((done as f64 + partial) / status.total as f64) * 100.0).floor() as u8;
    status.progress = if done >= status.total { 100 } else { value.min(99) };
}

fn update_running_progress(state: &Arc<Mutex<RenderTaskStatus>>, index: u32, _total: u32, part: f64) {
    if let Ok(mut status) = state.lock() {
        status.in_flight.entry(index).and_modify(|value| *value = value.max(part.clamp(0.0, 1.0))).or_insert(part.clamp(0.0, 1.0));
        update_progress(&mut status);
    }
}

fn push_log(status: &mut RenderTaskStatus, message: String) {
    status.logs.push(message);
    if status.logs.len() > 500 {
        let overflow = status.logs.len() - 500;
        status.logs.drain(0..overflow);
    }
}
