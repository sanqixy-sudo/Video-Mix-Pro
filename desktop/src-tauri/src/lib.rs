mod commands;
mod portable;
mod process;
mod media;
mod diagnostic_log;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    portable::prepare();
    diagnostic_log::init(
        portable::data_dir().map(|data| data.join("logs"))
            .or_else(|| dirs::data_local_dir().map(|data| data.join("VideoMixPro").join("logs"))),
    );
    tauri::Builder::default()
        .on_window_event(|_, event| match event {
            tauri::WindowEvent::CloseRequested { .. } => diagnostic_log::event("window close requested"),
            tauri::WindowEvent::Destroyed => diagnostic_log::event("window destroyed"),
            _ => {}
        })
        .manage(commands::render::RenderState::default())
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_fs::init())
        .plugin(tauri_plugin_dialog::init())
        .invoke_handler(tauri::generate_handler![
            commands::diagnostics::get_diagnostics,
            commands::scan::scan_materials,
            commands::auth::load_auth_state,
            commands::auth::save_auth_state,
            commands::file_dialog::pick_directory,
            commands::file_dialog::pick_file,
            commands::file_dialog::pick_files,
            commands::file_dialog::open_directory,
            commands::render::start_render_task,
            commands::render::start_overlay_task,
            commands::render::start_watermark_task,
            commands::render::start_dedup_task,
            commands::render::get_render_status,
            commands::render::cancel_render_task,
            commands::render::remove_queued_task,
            commands::render::clear_pending_tasks,
            commands::render::clear_finished_tasks,
            commands::render::retry_queue_task,
        ])
        .run(tauri::generate_context!())
        .expect("failed to run Video Mix Pro");
    diagnostic_log::event("application exited normally");
}
