use super::*;
use std::time::{Duration, Instant};

fn workdir() -> PathBuf {
    let path = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("target").join(format!("desktop-smoke-{}", next_task_id()));
    fs::create_dir_all(&path).unwrap();
    path
}

#[test]
fn mix_concurrency_keeps_memory_for_the_app() {
    const GIB: u64 = 1024 * 1024 * 1024;
    assert_eq!(limit_mix_workers_by_memory(4, Some(4 * GIB)), 1);
    assert_eq!(limit_mix_workers_by_memory(4, Some(8 * GIB)), 2);
    assert_eq!(limit_mix_workers_by_memory(4, Some(16 * GIB)), 4);
    assert_eq!(limit_mix_workers_by_memory(2, None), 2);
    #[cfg(windows)]
    assert!(available_memory_bytes().is_some_and(|bytes| bytes > 0));
}

#[test]
fn concurrent_progress_counts_work_not_video_ordinal() {
    let state = Arc::new(Mutex::new(RenderTaskStatus { total: 4, running: true, ..Default::default() }));
    update_running_progress(&state, 4, 4, 0.5);
    assert_eq!(state.lock().unwrap().progress, 12);
    update_running_progress(&state, 1, 4, 0.5);
    assert_eq!(state.lock().unwrap().progress, 25);
    mark_completed(&state, 4, "four".into());
    assert_eq!(state.lock().unwrap().progress, 37);
    update_running_progress(&state, 1, 4, 0.2);
    assert_eq!(state.lock().unwrap().progress, 37);
    mark_failed(&state, 1, "failed".into());
    assert_eq!(state.lock().unwrap().progress, 50);
    mark_completed(&state, 2, "two".into());
    mark_completed(&state, 3, "three".into());
    assert_eq!(state.lock().unwrap().progress, 100);
}

#[test]
fn cancelled_publish_preserves_existing_output() {
    let dir=workdir();let output=dir.join("video.mp4");let temp=staging_path(&output);
    fs::write(&output,b"previous-good-output").unwrap();fs::write(&temp,b"new-output").unwrap();
    assert!(publish_output(&temp,&output,&AtomicBool::new(true)).is_err());
    assert_eq!(fs::read(&output).unwrap(),b"previous-good-output");
    publish_output(&temp,&output,&AtomicBool::new(false)).unwrap();
    assert_eq!(fs::read(&output).unwrap(),b"new-output");
}

fn dedup_plan(source: &Path, output: &Path, video: &Path, ffmpeg: &Path, ffprobe: &Path) -> DedupPlan {
    fs::create_dir_all(output).unwrap();
    DedupPlan {
        config: DedupConfig { source_folder: source.to_string_lossy().into(), output_folder:output.to_string_lossy().into(), random_bitrate:true,drop_frames:true,micro_speed:true,subtle_filter:true,keep_audio:true,encoder:"cpu_libx264".into(),workers:2,concurrency_mode:"manual".into(),conflict_strategy:"overwrite".into() },
        source:source.into(),output:output.into(),videos:vec![video.into()],ffmpeg:ffmpeg.into(),ffprobe:Some(ffprobe.into()),probes:Arc::default(),
    }
}

#[test]
fn retired_history_releases_archived_plans() {
    let mut items=Vec::new();let mut archive=HashMap::new();
    let mut removed=Vec::new();
    for index in 0..100 {
        let plan=dedup_plan(&workdir(),&workdir(),Path::new("video.mp4"),Path::new("ffmpeg"),Path::new("ffprobe"));
        let mut task=queued_dedup_task(plan);
        task.item.status="completed".into();
        for id in prune_queue_history(&mut items) { archive.remove(&id); removed.push(id); }
        archive.insert(task.id.clone(),task.plan);items.push(task.item);
        assert!(archive.len()<=50,"iteration {index}");
    }
    assert_eq!(items.len(),50);assert_eq!(archive.len(),50);assert_eq!(removed.len(),50);
}

fn assert_completed(state: &Arc<Mutex<RenderTaskStatus>>) {
    let state=state.lock().unwrap();
    assert_eq!(state.failed,0,"{:?}",state.logs);
    assert_eq!(state.completed,state.total,"{:?}",state.logs);
    assert_eq!(state.progress,100);
}

fn assert_video_size(ffprobe: &Path, folder: &Path, width: u64, height: u64) {
    let video = fs::read_dir(folder).unwrap().map(|entry| entry.unwrap().path())
        .find(|path| path.extension().and_then(|ext| ext.to_str()) == Some("mp4")).unwrap();
    let output = Command::new(ffprobe).args(["-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "json"])
        .arg(&video).output().unwrap();
    assert!(output.status.success(), "{}", String::from_utf8_lossy(&output.stderr));
    let value: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(value["streams"][0]["width"].as_u64(), Some(width), "{}", video.display());
    assert_eq!(value["streams"][0]["height"].as_u64(), Some(height), "{}", video.display());
}

#[test]
fn real_media_workflows_cache_failure_and_cancel() {
    let dir=workdir();
    let ffmpeg=PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("bin/ffmpeg.exe");
    let ffprobe=ffmpeg.with_file_name("ffprobe.exe");
    assert!(ffmpeg.is_file() && ffprobe.is_file(),"Bundled media tools required");
    let video=dir.join("素材 sample.mp4");
    let frame=dir.join("frame.png");
    let mut command=Command::new(&ffmpeg);
    command.args(["-hide_banner","-loglevel","error","-y","-f","lavfi","-i","testsrc2=size=160x90:rate=12:duration=1","-f","lavfi","-i","sine=frequency=440:duration=1","-c:v","libx264","-pix_fmt","yuv420p","-c:a","aac","-shortest"]).arg(&video);
    run_cmd(command,&AtomicBool::new(false)).unwrap();
    let mut command=Command::new(&ffmpeg);
    command.args(["-hide_banner","-loglevel","error","-y","-f","lavfi","-i","color=blue:size=108x192","-frames:v","1"]).arg(&frame);
    run_cmd(command,&AtomicBool::new(false)).unwrap();
    let cancel=Arc::new(AtomicBool::new(false));
    let plan=dedup_plan(&dir,&dir.join("dedup"),&video,&ffmpeg,&ffprobe);
    let state=Arc::new(Mutex::new(initial_dedup_status(&plan,"dedup")));
    run_dedup_task(plan,state.clone(),cancel.clone());assert_completed(&state);

    let out=dir.join("watermark");fs::create_dir_all(&out).unwrap();
    let plan=WatermarkPlan { config:WatermarkConfig { source_folder:String::new(),logo_file:String::new(),output_folder:String::new(),width_percent:20.0,speed:100.0,opacity:0.5,keep_audio:true,encoder:"cpu_libx264".into(),workers:2,concurrency_mode:"manual".into(),conflict_strategy:"overwrite".into() },source:dir.clone(),logo:frame.clone(),videos:vec![video.clone()],output:out,ffmpeg:ffmpeg.clone(),ffprobe:Some(ffprobe.clone()),probes:Arc::default() };
    let state=Arc::new(Mutex::new(initial_watermark_status(&plan,"watermark")));
    run_watermark_task(plan,state.clone(),cancel.clone());assert_completed(&state);

    let naming=serde_json::json!({"frameFile":"","videoFiles":[],"outputFolder":"","x":0,"y":0,"width":540,"height":960,"mode":"contain","fps":12,"crf":28,"preset":"ultrafast","keepAudio":true,"encoder":"cpu_libx264","workers":1,"concurrencyMode":"manual","enableAutoNaming":false,"namingUseSourceName":true,"namingDate":"","namingPart1":"","namingPart2":"","namingPart3":"","namingPart4":"","namingSeqDigits":4,"conflictStrategy":"overwrite"});
    let out=dir.join("overlay");fs::create_dir_all(&out).unwrap();
    let plan=OverlayPlan { config:serde_json::from_value(naming).unwrap(),frame:frame.clone(),videos:vec![video.clone()],output:out,ffmpeg:ffmpeg.clone(),ffprobe:Some(ffprobe.clone()),probes:Arc::default() };
    let state=Arc::new(Mutex::new(initial_overlay_status(&plan,"overlay")));
    let mut landscape_overlay=plan.clone();landscape_overlay.config.orientation=OutputOrientation::Landscape;
    landscape_overlay.output=dir.join("overlay-landscape");fs::create_dir_all(&landscape_overlay.output).unwrap();
    run_overlay_task(plan,state.clone(),cancel.clone());assert_completed(&state);
    let landscape_state=Arc::new(Mutex::new(initial_overlay_status(&landscape_overlay,"overlay-landscape")));
    run_overlay_task(landscape_overlay,landscape_state.clone(),cancel.clone());assert_completed(&landscape_state);

    // Exercise multiple sequential outputs and repeated FFmpeg launches; the reported crash happened after the first output.
    let config=serde_json::json!({"sourceFolder":"","outputFolder":"","segmentCount":3,"outputCount":6,"trimStartSeconds":0.0,"enableFirstVideo":false,"firstVideoFolder":"","enableTopInsert":false,"enableTailVideo":false,"tailVideoFolder":"","enableBannerOverlay":false,"bannerFile":"","allowRepeatInsideOneVideo":true,"enableDedupWhenComboRepeated":false,"keepAudio":true,"cleanupTemp":true,"encoder":"cpu_libx264","workers":1,"concurrencyMode":"manual","enableAutoNaming":false,"namingUseSourceName":false,"namingDate":"","namingPart1":"","namingPart2":"","namingPart3":"","namingPart4":"","namingSeqDigits":4,"conflictStrategy":"overwrite"});
    let out=dir.join("mix");fs::create_dir_all(&out).unwrap();
    let plan=RenderPlan { config:serde_json::from_value(config).unwrap(),source:dir.clone(),output:out,ffmpeg:ffmpeg.clone(),ffprobe:Some(ffprobe.clone()),videos:vec![video.clone()],first_videos:vec![],top_videos:vec![],tail_videos:vec![],banner:None,probes:Arc::default() };
    let probes=plan.probes.clone();
    let state=Arc::new(Mutex::new(initial_render_status(&plan,"mix")));
    let mut landscape_mix=plan.clone();landscape_mix.config.orientation=OutputOrientation::Landscape;
    landscape_mix.config.output_count=1;landscape_mix.output=dir.join("mix-landscape");fs::create_dir_all(&landscape_mix.output).unwrap();
    run_render_task(plan,state.clone(),cancel.clone());assert_completed(&state);
    let landscape_state=Arc::new(Mutex::new(initial_render_status(&landscape_mix,"mix-landscape")));
    run_render_task(landscape_mix,landscape_state.clone(),cancel.clone());assert_completed(&landscape_state);
    assert_eq!(probes.calls.load(Ordering::SeqCst),1,"same clip is probed once across workers");

    // Old output survives a corrupt input; no partial final file blocks a retry.
    let broken=dir.join("broken.mp4");fs::write(&broken,b"invalid video").unwrap();
    let plan=dedup_plan(&dir,&dir.join("failure"),&broken,&ffmpeg,&ffprobe);
    let old=plan.output.join("broken.mp4");fs::write(&old,b"existing good file").unwrap();
    let state=Arc::new(Mutex::new(initial_dedup_status(&plan,"failure")));
    run_dedup_task(plan,state.clone(),cancel.clone());
    assert_eq!(state.lock().unwrap().failed,1);assert_eq!(fs::read(&old).unwrap(),b"existing good file");
    assert_eq!(fs::read_dir(old.parent().unwrap()).unwrap().count(),1);

    // Cancel a real, long FFmpeg process independently of its stdout.
    let mut command=Command::new(&ffmpeg);
    command.args(["-hide_banner","-loglevel","error","-re","-f","lavfi","-i","testsrc2=size=160x90:rate=12:duration=20","-f","null","-"]);
    let stop=cancel.clone();let trigger=thread::spawn(move || { thread::sleep(Duration::from_millis(300));stop.store(true,Ordering::SeqCst); });
    let start=Instant::now();assert!(run_cmd(command,&cancel).is_err());let cancel_ms=start.elapsed().as_millis();
    trigger.join().unwrap();assert!(cancel_ms<2000);

    let mut outputs=Vec::new();
    assert_video_size(&ffprobe,&dir.join("overlay"),1080,1920);
    assert_video_size(&ffprobe,&dir.join("overlay-landscape"),1920,1080);
    assert_video_size(&ffprobe,&dir.join("mix"),1080,1920);
    assert_video_size(&ffprobe,&dir.join("mix-landscape"),1920,1080);
    for folder in ["dedup","watermark","overlay","overlay-landscape","mix","mix-landscape"] {
        for entry in fs::read_dir(dir.join(folder)).unwrap() {
            let path=entry.unwrap().path();if path.extension().and_then(|e|e.to_str())!=Some("mp4") { continue; }
            let info=crate::media::ProbeCache::default().get(&ffprobe,&path);
            assert!(info.duration>0.5 && info.has_audio,"{}",path.display());
            outputs.push(serde_json::json!({"file":path,"duration":info.duration,"has_audio":info.has_audio}));
        }
    }
    assert_eq!(outputs.len(),11);
    let report=serde_json::json!({"version":env!("CARGO_PKG_VERSION"),"outputs":outputs,"ffmpeg_cancel_ms":cancel_ms,"shared_clip_probe_calls":probes.calls.load(Ordering::SeqCst),"failed_overwrite_preserved":true});
    fs::write(dir.join("report.json"),serde_json::to_vec_pretty(&report).unwrap()).unwrap();
    println!("MEDIA_REPORT={}",dir.join("report.json").display());
}
