mod commands;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
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
            commands::render::get_render_status,
            commands::render::cancel_render_task,
            commands::render::remove_queued_task,
            commands::render::clear_pending_tasks,
            commands::render::clear_finished_tasks,
            commands::render::retry_queue_task,
        ])
        .run(tauri::generate_context!())
        .expect("failed to run Video Mix Pro");
}
