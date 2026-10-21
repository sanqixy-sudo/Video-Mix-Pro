#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    if let Some(exit_code) = video_mix_pro_lib::run_cleanup_helper_if_requested() {
        std::process::exit(exit_code);
    }
    video_mix_pro_lib::run();
}
