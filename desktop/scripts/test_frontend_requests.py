"""Test built UI request races with simulated IPC in an isolated Edge profile."""
from pathlib import Path
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
import json
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[2]
class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self,*args): pass

def main():
    server=ThreadingHTTPServer(('127.0.0.1',0),partial(QuietHandler,directory=str(ROOT/'desktop/dist')))
    Thread(target=server.serve_forever,daemon=True).start()
    report={'errors':[],'runtime':'isolated Edge with simulated IPC'}
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch(channel='msedge',headless=True)
            page=browser.new_page(viewport={'width':1280,'height':820})
            page.on('pageerror',lambda error:report['errors'].append(str(error)))
            page.route('https://videomix.7cloudvps.com/**',lambda route:route.fulfill(json={'ok':True,'current_version':'0.2.3','latest_version':'0.2.3','update_available':False,'required':False}))
            page.add_init_script("""(() => {
              const status={running:false,cancelled:false,status:'就绪',progress:0,completed:0,failed:0,total:0,outputFolder:'',taskKind:'',logs:[],currentTaskId:'',pendingCount:0,queue:[]};
              window.__scans=[];
              window.__poll={active:0,max:0,calls:0,slow:false};
              window.__TAURI_INTERNALS__={
                metadata:{currentWindow:{label:'main'},currentWebview:{label:'main'}},
                transformCallback:()=>1,
                unregisterCallback:()=>{},
                convertFileSrc:path=>path,
                invoke:async(command,args)=>{
                  if(command==='get_diagnostics')return {hasFfmpeg:true,hasFfprobe:true,hasQsv:false,hasScaleQsv:false,hasVppQsv:false,hasNvenc:false,hasAmf:false,recommendedWorkers:1,ffmpegPath:'test',ffprobePath:'test'};
                  if(command==='load_auth_state')return {};
                  if(command==='plugin:app|version')return '0.2.3';
                  if(command==='scan_materials')return new Promise(resolve=>window.__scans.push({path:args.config.sourceFolder,resolve}));
                  if(command==='get_render_status') {
                    const meter=window.__poll;meter.calls++;meter.active++;meter.max=Math.max(meter.max,meter.active);
                    try {if(meter.slow)await new Promise(resolve=>setTimeout(resolve,1500));return structuredClone(status);}
                    finally {meter.active--;}
                  }
                  if(command==='plugin:window|is_maximized')return false;
                  return 1;
                }
              };
            })();""")
            page.goto(f'http://127.0.0.1:{server.server_port}')
            source=page.get_by_placeholder('选择包含主素材视频的文件夹')
            source.fill('C:/test/old')
            page.wait_for_function('window.__scans.length===1')
            source.fill('')
            page.evaluate("window.__scans[0].resolve({mainCount:999,firstCount:0,topCount:0,tailCount:0,bannerDetected:'',maxUniqueCombos:999})")
            page.wait_for_timeout(100)
            assert '选择素材文件夹后自动扫描' in page.locator('.scan-feedback').inner_text()
            report['stale_scan_after_clear_ignored']=True
            source.fill('C:/test/first')
            page.wait_for_function('window.__scans.length===2')
            source.fill('C:/test/second')
            page.wait_for_function('window.__scans.length===3')
            page.evaluate("window.__scans[2].resolve({mainCount:2,firstCount:0,topCount:0,tailCount:0,bannerDetected:'',maxUniqueCombos:2})")
            page.wait_for_timeout(50)
            page.evaluate("window.__scans[1].resolve({mainCount:999,firstCount:0,topCount:0,tailCount:0,bannerDetected:'',maxUniqueCombos:999})")
            page.wait_for_timeout(100)
            assert '主素材 2 个' in page.locator('.scan-feedback').inner_text()
            report['out_of_order_scan_ignored']=True
            page.evaluate('window.__poll={active:0,max:0,calls:0,slow:true}')
            page.locator('.sidebar-nav').get_by_role('button',name='任务中心',exact=True).click()
            page.wait_for_timeout(1100)
            page.get_by_role('button',name='刷新状态',exact=True).click()
            page.wait_for_timeout(2500)
            report['slow_poll_with_manual_refresh']=page.evaluate('window.__poll')
            assert report['slow_poll_with_manual_refresh']['calls']==1
            assert report['slow_poll_with_manual_refresh']['max']==1
            assert not report['errors'],report['errors']
            page.screenshot(path=str(ROOT/'docs/verification/desktop-0.2.3-request-tests.png'))
            browser.close()
        (ROOT/'docs/verification/desktop-0.2.3-request-tests.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(report,ensure_ascii=False))
    finally:
        server.shutdown()

if __name__=='__main__': main()
