use std::fs;
use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};

const VIDEO_EXTS: &[&str] = &["mp4", "mov", "mkv", "avi", "webm", "m4v", "flv", "wmv", "ts"];
const BANNER_KEYWORDS: &[&str] = &[
    "banner", "overlay", "adbar", "ad_bar", "install_banner", "hengfu", "横幅", "安装条",
    "底部条", "bottom", "bottom_bar", "bottombar", "footer", "footer_bar", "底栏", "底部", "广告条",
];

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct MaterialConfig {
    pub source_folder: String,
    pub segment_count: u32,
    pub enable_first_video: bool,
    pub first_video_folder: String,
    pub enable_top_insert: bool,
    pub enable_tail_video: bool,
    pub tail_video_folder: String,
    pub enable_banner_overlay: bool,
    pub banner_file: String,
    pub allow_repeat_inside_one_video: bool,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ScanSummary {
    pub main_count: usize,
    pub first_count: usize,
    pub top_count: usize,
    pub tail_count: usize,
    pub banner_detected: String,
    pub max_unique_combos: u128,
}

#[tauri::command]
pub fn scan_materials(config: MaterialConfig) -> Result<ScanSummary, String> {
    let source = PathBuf::from(config.source_folder.trim());
    if !source.exists() || !source.is_dir() {
        return Ok(ScanSummary {
            main_count: 0,
            first_count: 0,
            top_count: 0,
            tail_count: 0,
            banner_detected: String::new(),
            max_unique_combos: 0,
        });
    }

    let selected_banner = if config.enable_banner_overlay && !config.banner_file.trim().is_empty() {
        Some(PathBuf::from(config.banner_file.trim()))
    } else {
        None
    };
    let banner = selected_banner.or_else(|| auto_find_banner(&source));
    let main_count = scan_videos(&source)
        .into_iter()
        .filter(|path| !is_banner_candidate(path))
        .filter(|path| banner.as_ref().map(|b| !same_path(b, path)).unwrap_or(true))
        .count();

    let first_count = if config.enable_first_video {
        scan_videos(Path::new(config.first_video_folder.trim())).len()
    } else {
        0
    };

    let top_count = if config.enable_top_insert {
        scan_videos(&source.join("top")).len()
    } else {
        0
    };

    let tail_count = if config.enable_tail_video {
        scan_videos(Path::new(config.tail_video_folder.trim())).len()
    } else {
        0
    };

    let max_unique_combos = max_unique_count(
        main_count as u128,
        config.segment_count as u128,
        config.allow_repeat_inside_one_video,
    );

    Ok(ScanSummary {
        main_count,
        first_count,
        top_count,
        tail_count,
        banner_detected: banner.map(|p| p.to_string_lossy().to_string()).unwrap_or_default(),
        max_unique_combos,
    })
}

fn scan_videos(folder: &Path) -> Vec<PathBuf> {
    if !folder.exists() || !folder.is_dir() {
        return Vec::new();
    }

    let Ok(entries) = fs::read_dir(folder) else {
        return Vec::new();
    };

    entries
        .filter_map(Result::ok)
        .map(|entry| entry.path())
        .filter(|path| path.is_file())
        .filter(|path| {
            path.extension()
                .and_then(|ext| ext.to_str())
                .map(|ext| VIDEO_EXTS.contains(&ext.to_ascii_lowercase().as_str()))
                .unwrap_or(false)
        })
        .collect()
}

fn is_banner_candidate(path: &Path) -> bool {
    let Some(stem) = path.file_stem().and_then(|name| name.to_str()) else {
        return false;
    };
    let name = stem.to_ascii_lowercase();
    BANNER_KEYWORDS.iter().any(|keyword| name.contains(&keyword.to_ascii_lowercase()))
}

fn auto_find_banner(folder: &Path) -> Option<PathBuf> {
    scan_videos(folder).into_iter().find(|path| is_banner_candidate(path))
}

fn same_path(left: &Path, right: &Path) -> bool {
    let left = left.canonicalize().unwrap_or_else(|_| left.to_path_buf());
    let right = right.canonicalize().unwrap_or_else(|_| right.to_path_buf());
    left == right
}

fn max_unique_count(n: u128, k: u128, allow_repeat_inside_one_video: bool) -> u128 {
    if k == 0 || n == 0 {
        return 0;
    }
    if allow_repeat_inside_one_video {
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
