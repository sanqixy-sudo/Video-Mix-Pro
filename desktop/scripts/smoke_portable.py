"""Exercise an isolated fresh portable build through its real native WebView."""
from pathlib import Path
import argparse, json, os, socket, subprocess, time, urllib.request
from playwright.sync_api import sync_playwright

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('directory', type=Path)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--expected-version', default='0.2.3')
    parser.add_argument('--extended', action='store_true')
    args = parser.parse_args()
    directory = args.directory.resolve()
    exe = directory / 'Video Mix Pro.exe'
    assert exe.is_file() and (directory / 'portable.flag').is_file()
    assert not (directory / 'data').exists(), 'Use a fresh isolated staging folder'
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    env = os.environ.copy()
    env.pop('WEBVIEW2_USER_DATA_FOLDER', None)
    env.pop('WEBVIEW2_BROWSER_EXECUTABLE_FOLDER', None)
    env['WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS'] = f'--remote-debugging-address=127.0.0.1 --remote-debugging-port={port}'
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = 0
    proc = subprocess.Popen([str(exe)], cwd=directory, env=env, startupinfo=startup)
    report = {'errors': []}
    try:
        for _ in range(90):
            if proc.poll() is not None:
                raise RuntimeError('Application exited with ' + str(proc.returncode))
            try:
                version = json.load(urllib.request.urlopen(f'http://127.0.0.1:{port}/json/version', timeout=1))
                break
            except (OSError, ValueError):
                time.sleep(1)
        else:
            raise RuntimeError('Native WebView2 did not expose test endpoint')
        report['webview_version'] = version['Browser']
        with sync_playwright() as pw:
            browser = pw.chromium.connect_over_cdp(f'http://127.0.0.1:{port}')
            context = browser.contexts[0]
            for _ in range(60):
                pages = [p for p in context.pages if p.url.startswith(('http://tauri.localhost', 'https://tauri.localhost'))]
                if pages:
                    break
                time.sleep(.5)
            page = pages[0]
            page.on('pageerror', lambda error: report['errors'].append(str(error)))
            page.wait_for_function("document.querySelector('#root')?.children.length > 0", timeout=30000)
            report['app_version'] = page.evaluate("window.__TAURI_INTERNALS__.invoke('plugin:app|version')")
            assert report['app_version'] == args.expected_version
            diagnostics = page.evaluate("window.__TAURI_INTERNALS__.invoke('get_diagnostics')")
            assert diagnostics['hasFfmpeg'] and diagnostics['hasFfprobe']
            report['diagnostics'] = diagnostics
            samples=[]
            for _ in range(3):
                start=time.perf_counter()
                page.evaluate("window.__TAURI_INTERNALS__.invoke('get_diagnostics')")
                samples.append(round((time.perf_counter()-start)*1000,2))
            report['repeated_diagnostics_ms']=samples
            initial = page.evaluate("window.__TAURI_INTERNALS__.invoke('load_auth_state')")
            assert not initial['token'], 'Fresh portable profile unexpectedly contains a session'
            state = {'serverUrl': 'https://videomix.7cloudvps.com', 'username': 'portable-storage-probe', 'token': '', 'active': False, 'plan': '', 'planLabel': '', 'expiresAt': '', 'sessionExpiresAt': '', 'deviceId': ''}
            page.evaluate("auth => window.__TAURI_INTERNALS__.invoke('save_auth_state', {auth})", state)
            assert json.loads((directory / 'data/account/session.json').read_text())['username'] == state['username']
            report['isolated_portable_state'] = True
            report['public_service'] = page.evaluate("async()=>{const r=await fetch('https://videomix.7cloudvps.com/api/health');return {status:r.status,data:await r.json()}}")
            assert report['public_service']['status'] == 200 and report['public_service']['data']['server_version'] == '0.3.0'
            report['updates'] = page.evaluate("async version=>{const r=await fetch('https://videomix.7cloudvps.com/api/update/check?current_version='+version);return {status:r.status,data:await r.json()}}", args.expected_version)
            assert report['updates']['status'] == 200
            if args.extended:
                extended_checks(page, directory, state, report)
            args.report.parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(args.report.with_suffix('.png')))
            assert not report['errors'], report['errors']
            try:
                page.evaluate("window.__TAURI_INTERNALS__.invoke('plugin:window|close')")
            except Exception:
                pass
        report['native_startup'] = True
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(report, ensure_ascii=False, indent=2))
    except Exception as error:
        report['test_failure']=str(error)
        try:
            report['debug']=page.evaluate("""() => ({
              scanStarted:window.__scanStarted,
              scanText:document.querySelector('.scan-feedback')?.textContent,
              savedSource:JSON.parse(localStorage.getItem('video_mix_last_materials_v2')||'{}').sourceFolder,
              invoke:String(window.__TAURI_INTERNALS__.invoke).slice(0,160),
              invokeWritable:Object.getOwnPropertyDescriptor(window.__TAURI_INTERNALS__,'invoke')?.writable,
              invokeConfigurable:Object.getOwnPropertyDescriptor(window.__TAURI_INTERNALS__,'invoke')?.configurable
            })""")
        except Exception:
            pass
        args.report.parent.mkdir(parents=True,exist_ok=True)
        args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        raise
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()

def extended_checks(page, directory, state, report):
    # Direct IPC calls must be denied even when the UI or saved active flag is forged.
    page.wait_for_function("localStorage.getItem('video_mix_last_materials_v2') !== null")
    checks = page.evaluate("""async () => {
      const invoke=window.__TAURI_INTERNALS__.invoke;
      const result=[];
      for (const [command,key] of [
        ['start_render_task','video_mix_last_materials_v2'],
        ['start_overlay_task','video_mix_last_overlay_v2'],
        ['start_watermark_task','video_mix_last_watermark_v1'],
        ['start_dedup_task','video_mix_last_dedup_v1'],
      ]) {
        try { await invoke(command,{config:JSON.parse(localStorage.getItem(key))}); result.push({command,denied:false}); }
        catch(error) { result.push({command,denied:true,error:String(error)}); }
      }
      try { await invoke('retry_queue_task',{taskId:'missing'});result.push({command:'retry',denied:false}); }
      catch(error) {result.push({command:'retry',denied:true,error:String(error)});}
      return result;
    }""")
    assert all(item['denied'] and '登录' in item['error'] for item in checks), checks
    report['native_unauthenticated_gates'] = checks
    forged = {**state, 'active': True, 'token':'synthetic-invalid-token', 'deviceId':'test-device',
              'serverUrl':'http://127.0.0.1:1', 'plan':'permanent'}
    page.evaluate("auth => window.__TAURI_INTERNALS__.invoke('save_auth_state',{auth})", forged)
    result=page.evaluate("""async () => {
      try {await window.__TAURI_INTERNALS__.invoke('start_render_task',{config:JSON.parse(localStorage.getItem('video_mix_last_materials_v2'))});return '';}
      catch(error) {return String(error);}
    }""")
    assert '不受信任' in result,result
    report['forged_local_membership_denied']=True
    forged['serverUrl']='https://videomix.7cloudvps.com'
    page.evaluate("auth => window.__TAURI_INTERNALS__.invoke('save_auth_state',{auth})", forged)
    result=page.evaluate("""async () => {
      try {await window.__TAURI_INTERNALS__.invoke('start_render_task',{config:JSON.parse(localStorage.getItem('video_mix_last_materials_v2'))});return '';}
      catch(error) {return String(error);}
    }""")
    assert '登录已失效' in result,result
    report['native_https_invalid_token_denied']=True
    page.evaluate("auth => window.__TAURI_INTERNALS__.invoke('save_auth_state',{auth})", state)
    # Cached hardware diagnostics must not rerun PowerShell/encoding on each request.
    samples=[]
    for _ in range(3):
        start=time.perf_counter()
        page.evaluate("window.__TAURI_INTERNALS__.invoke('get_diagnostics')")
        samples.append(round((time.perf_counter()-start)*1000,2))
    report['cached_diagnostics_ms']=samples
    pages=[]
    for label in ['套外框','飘动水印','视频去重','编码性能','任务中心','授权中心','设置','批量混剪']:
        page.locator('.sidebar-nav').get_by_role('button',name=label,exact=True).click()
        page.wait_for_function("!document.querySelector('[role=status]')?.textContent?.includes('正在加载页面')")
        page.wait_for_timeout(150)
        assert page.locator('.content-inner').inner_text().strip()
        pages.append(label)
    report['lazy_pages_loaded']=pages

if __name__ == '__main__':
    main()
