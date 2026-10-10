//! Bounded subprocess output and cancellation independent of stdout activity.
use std::collections::VecDeque;
use std::io::Read;
use std::process::{Command, ExitStatus, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc::{sync_channel, SyncSender};
use std::thread;
use std::time::{Duration, Instant};

const OUTPUT_LIMIT: usize = 256 * 1024;
const ERROR_LIMIT: usize = 64 * 1024;

pub struct Output {
    pub status: ExitStatus,
    pub stdout: String,
    pub stderr: String,
}

fn capture(mut input: impl Read, limit: usize, lines: Option<SyncSender<String>>) -> String {
    let mut tail = VecDeque::with_capacity(limit);
    let mut pending = Vec::new();
    let mut bytes = [0u8; 4096];
    while let Ok(count) = input.read(&mut bytes) {
        if count == 0 { break; }
        for &byte in &bytes[..count] {
            if tail.len() == limit { tail.pop_front(); }
            tail.push_back(byte);
            if let Some(sender) = &lines {
                if byte == b'\n' {
                    let _ = sender.try_send(String::from_utf8_lossy(&pending).trim().to_owned());
                    pending.clear();
                } else if pending.len() < 4096 {
                    pending.push(byte);
                }
            }
        }
    }
    String::from_utf8_lossy(&tail.into_iter().collect::<Vec<_>>()).into_owned()
}

pub fn run(
    mut command: Command,
    cancel: &AtomicBool,
    timeout: Option<Duration>,
    mut progress: impl FnMut(&str),
) -> Result<Output, String> {
    if cancel.load(Ordering::SeqCst) { return Err("任务已取消。".into()); }
    #[cfg(windows)] {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x08000000);
    }
    let mut child = command.stdin(Stdio::null()).stdout(Stdio::piped()).stderr(Stdio::piped())
        .spawn().map_err(|err| format!("无法启动处理程序：{err}"))?;
    let (sender, receiver) = sync_channel(64);
    let stdout = child.stdout.take().expect("piped stdout");
    let stderr = child.stderr.take().expect("piped stderr");
    let out_reader = thread::spawn(move || capture(stdout, OUTPUT_LIMIT, Some(sender)));
    let err_reader = thread::spawn(move || capture(stderr, ERROR_LIMIT, None));
    let started = Instant::now();
    let mut failure = None;
    let status = loop {
        // Bound work each tick so a noisy child cannot starve cancellation.
        for line in receiver.try_iter().take(64) { progress(&line); }
        if cancel.load(Ordering::SeqCst) {
            failure = Some("任务已取消。".to_owned());
        } else if timeout.is_some_and(|limit| started.elapsed() >= limit) {
            failure = Some("处理程序响应超时。".to_owned());
        }
        if failure.is_some() {
            let _ = child.kill();
            break child.wait().map_err(|err| err.to_string());
        }
        match child.try_wait() {
            Ok(Some(status)) => break Ok(status),
            Ok(None) => thread::sleep(Duration::from_millis(50)),
            Err(err) => {
                let _ = child.kill();
                let _ = child.wait();
                break Err(err.to_string());
            }
        }
    };
    let stdout = out_reader.join().unwrap_or_default();
    let stderr = err_reader.join().unwrap_or_default();
    for line in receiver.try_iter() { progress(&line); }
    if let Some(error) = failure { return Err(error); }
    Ok(Output { status: status?, stdout, stderr })
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn output_is_bounded_even_without_newlines() {
        let input = vec![b'x'; ERROR_LIMIT * 4];
        assert_eq!(capture(input.as_slice(), ERROR_LIMIT, None).len(), ERROR_LIMIT);
    }
    #[test]
    #[cfg(windows)]
    fn silent_process_can_be_cancelled() {
        let cancel = std::sync::Arc::new(AtomicBool::new(false));
        let trigger = cancel.clone();
        let mut command = Command::new("powershell.exe");
        command.args(["-NoProfile", "-NonInteractive", "-Command", "Start-Sleep -Seconds 20"]);
        let handle = thread::spawn(move || {
            thread::sleep(Duration::from_millis(250));
            trigger.store(true, Ordering::SeqCst);
        });
        let start = Instant::now();
        assert!(run(command, &cancel, None, |_| {}).err().unwrap().contains("取消"));
        assert!(start.elapsed() < Duration::from_secs(3));
        handle.join().unwrap();
    }
    #[test]
    #[cfg(windows)]
    fn silent_process_has_a_deadline() {
        let mut command = Command::new("powershell.exe");
        command.args(["-NoProfile", "-NonInteractive", "-Command", "Start-Sleep -Seconds 20"]);
        let start = Instant::now();
        assert!(run(command, &AtomicBool::new(false), Some(Duration::from_millis(250)), |_| {}).err().unwrap().contains("超时"));
        assert!(start.elapsed() < Duration::from_secs(3));
    }
}
