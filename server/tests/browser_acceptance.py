"""Isolated production-build browser acceptance; never opens a production DB.

Run from server: python tests/browser_acceptance.py
Requires Playwright and Chromium/Edge. Evidence goes into .qa-data-web/evidence.
"""
import functools
import http.server
import json
import os
import secrets
import sys
import tempfile
import threading
import time
from datetime import timedelta
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
TEMP=tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
PASSWORD=secrets.token_urlsafe(24)
os.environ.update(DB_PATH=str(Path(TEMP.name)/'app.db'),ENVIRONMENT='development',ADMIN_USER='qa-admin',ADMIN_PASSWORD=PASSWORD,ADMIN_TOKEN='t'*40,ADMIN_COOKIE_SECURE='false',RATE_LIMIT_ENABLED='false')
import app
from admin_service import AdminService
import uvicorn
from playwright.sync_api import sync_playwright,expect

EVIDENCE=ROOT/'.qa-data-web'/'evidence';EVIDENCE.mkdir(parents=True,exist_ok=True)
app.init_db()
with app.db() as conn:
    for i in range(137):
        username=f'qa-user-{i:03d}' if i!=136 else '长账号用于检查边界与换行_abcdefghijklmnopqrstuv_0123456789'
        conn.execute('''INSERT INTO users(username,password_hash,is_member,plan,member_expires_at,is_banned,device_id,device_name,device_rebind_cooldown_until,created_at,updated_at)
            VALUES(?,?,1,?,?,?,?,?,?,?,?)''',(username,'qa-only', 'permanent' if i==135 else 'month',None if i==135 else (app.now_utc()+timedelta(days=42)).isoformat(),int(i==134),'device-'+str(i)+'x'*70,'工作电脑 '+str(i),(app.now_utc()+timedelta(hours=3)).isoformat() if i%7==0 else None,app.now_iso(),app.now_iso()))
service=AdminService(app)
batch=service.generate({'operation_id':'qa-browser-batch','plan':'month','count':100,'note':'浏览器验收批次'},'127.0.0.1')
server=uvicorn.Server(uvicorn.Config(app.app,host='127.0.0.1',port=18765,log_level='error'))
threading.Thread(target=server.run,daemon=True).start()
deadline=time.time()+20
while not server.started and time.time()<deadline: time.sleep(.05)
assert server.started
BASE='http://127.0.0.1:18765'
report={'checks':[],'viewports':[],'console_errors':[],'accessibility':[]}

def passed(name):
    report['checks'].append(name);print('PASS '+name,flush=True)
    (EVIDENCE/'browser-running.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')

with sync_playwright() as p:
    browser=p.chromium.launch(channel=os.environ.get('PLAYWRIGHT_CHANNEL','msedge'),headless=True)
    context=browser.new_context(viewport={'width':1440,'height':1000},reduced_motion='reduce')
    page=context.new_page();page.on('pageerror',lambda e:report['console_errors'].append(str(e)))
    # Capture the unchanged client frontend, without fake tasks or membership.
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self,*args): pass
    desktop=ROOT.parent/'desktop'/'dist'
    if desktop.is_dir():
        httpd=http.server.ThreadingHTTPServer(('127.0.0.1',18766),functools.partial(Quiet,directory=str(desktop)))
        threading.Thread(target=httpd.serve_forever,daemon=True).start()
        client=context.new_page()
        client.route('https://**/*',lambda route:route.abort())
        client.goto('http://127.0.0.1:18766');client.wait_for_timeout(800)
        (ROOT/'static'/'product').mkdir(exist_ok=True)
        client.screenshot(path=str(EVIDENCE/'client-workspace.png'),full_page=True)
        if not (ROOT/'static'/'product'/'client-workspace.png').exists():
            client.screenshot(path=str(ROOT/'static'/'product'/'client-workspace.png'),full_page=True)
        client.get_by_text('飘动水印',exact=True).first.click();client.wait_for_timeout(200)
        client.screenshot(path=str(ROOT/'static'/'product'/'client-watermark.png'),full_page=True)
        client.close();httpd.shutdown();passed('current-client-screenshot')
    page.goto(BASE+'/admin/users?page=2')
    page.get_by_label('管理员账号').fill('qa-admin');page.get_by_label('管理员密码').fill(PASSWORD)
    page.get_by_role('button',name='安全登录').click();expect(page.get_by_role('heading',name='用户与会员',exact=True)).to_be_visible()
    expect(page.get_by_text('26–50 条，共 137 条')).to_be_visible();passed('login-restores-url-page')
    page.goto(BASE+'/admin/users');expect(page.get_by_text('1–25 条，共 137 条')).to_be_visible()
    page.locator('.ant-table-tbody .ant-checkbox-input').first.check()
    page.locator('.ant-pagination-item-2').click();expect(page.get_by_text('26–50 条，共 137 条')).to_be_visible()
    page.locator('.ant-table-tbody .ant-checkbox-input').first.check()
    expect(page.locator('.selection-bar strong')).to_have_text('2');passed('explicit-cross-page-selection')
    page.get_by_placeholder('搜索账号、用户 ID、设备或备注').fill('qa-user-010')
    expect(page.get_by_text('1–1 条，共 1 条')).to_be_visible();expect(page.locator('.selection-bar')).to_have_count(0)
    page.reload();expect(page.get_by_placeholder('搜索账号、用户 ID、设备或备注')).to_have_value('qa-user-010');passed('query-url-and-selection-reset')
    account=page.get_by_role('button',name='qa-user-010',exact=True);account.click()
    expect(page.get_by_role('heading',name='qa-user-010',exact=True)).to_be_visible();page.screenshot(path=str(EVIDENCE/'user-detail-1440.png'))
    page.get_by_role('button',name='续费 / 开通',exact=True).click();page.get_by_role('button',name='预览变更').click()
    expect(page.get_by_role('button',name='确认执行',exact=True)).to_be_visible();page.screenshot(path=str(EVIDENCE/'renewal-preview-1440.png'))
    page.get_by_role('button',name='确认执行',exact=True).click();expect(page.get_by_text('已完成',exact=True)).to_be_visible();page.get_by_role('button',name='关闭',exact=True).last.click()
    page.keyboard.press('Escape');expect(page.locator('.user-drawer')).not_to_be_visible();expect(account).to_be_focused();passed('detail-renewal-and-focus-restoration')
    with app.db() as conn:batch_count=conn.execute('SELECT COUNT(*) FROM code_batches').fetchone()[0]
    def lost_response(route):
        response=route.fetch();assert response.status==200
        route.fulfill(status=504,content_type='application/json',body='{"detail":"生成响应中断，请重试原请求"}')
    page.route('**/admin/api/create_codes',lost_response,times=1)
    page.goto(BASE+'/admin/codes');page.get_by_role('button',name='生成兑换码',exact=True).click();page.get_by_role('button',name='生成并查看批次').click()
    expect(page.get_by_text('生成响应中断，请重试原请求',exact=True)).to_be_visible()
    page.get_by_role('button',name='重试原生成请求',exact=True).click()
    expect(page.get_by_role('heading',name='兑换批次详情',exact=True)).to_be_visible();assert '/admin/batches/' in page.url
    page.reload();expect(page.get_by_role('heading',name='兑换批次详情',exact=True)).to_be_visible();page.screenshot(path=str(EVIDENCE/'batch-result-1440.png'))
    with app.db() as conn:assert conn.execute('SELECT COUNT(*) FROM code_batches').fetchone()[0]==batch_count+1
    passed('generate-100-response-lost-retry-single-persistent-batch')
    page.goto(BASE+'/admin/releases');page.get_by_label('更新标题',exact=True).fill('浏览器验收草稿')
    page.get_by_role('button',name='刷新发布记录').click();expect(page.get_by_label('更新标题',exact=True)).to_have_value('浏览器验收草稿')
    page.reload();expect(page.get_by_label('更新标题',exact=True)).to_have_value('浏览器验收草稿');passed('release-draft-survives-refresh')
    for width in (1440,1280,390):
        page.set_viewport_size({'width':width,'height':960})
        for route in ('users','codes','batches','overview','releases','site','audit'):
            page.goto(BASE+'/admin/'+route);page.wait_for_timeout(300)
            expect(page.locator('main h1')).to_be_visible()
            overflow=page.evaluate('document.documentElement.scrollWidth > innerWidth+1')
            report['viewports'].append({'width':width,'route':route,'overflow':overflow})
            page.screenshot(path=str(EVIDENCE/f'{route}-{width}.png'),full_page=route in ('overview','site'))
            if width==390:
                page.add_script_tag(path=str(ROOT/'web-admin'/'node_modules'/'axe-core'/'axe.min.js'))
                violations=page.evaluate("async()=> (await axe.run(document, {runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa']}})).violations.map(v=>({id:v.id,impact:v.impact,nodes:v.nodes.map(n=>n.target)}))")
                report['accessibility'].append({'route':route,'width':width,'violations':violations})
            assert not overflow,(width,route)
        page.goto(BASE+'/');page.wait_for_timeout(250);page.screenshot(path=str(EVIDENCE/f'website-{width}.png'),full_page=True)
        assert page.locator('.price-card').count()==4
        expect(page.get_by_role('button',name='联系开通',exact=True)).to_have_count(0)
        assert not page.evaluate('document.documentElement.scrollWidth > innerWidth+1')
    passed('all-routes-1440-1280-390-no-page-overflow')
    page.goto(BASE+'/admin/users?q=qa-user-010');page.get_by_role('button',name='qa-user-010',exact=True).click()
    expect(page.get_by_role('button',name='续费 / 开通',exact=True)).to_be_visible();page.get_by_role('button',name='续费 / 开通',exact=True).click();page.get_by_role('button',name='预览变更').click();expect(page.get_by_role('button',name='确认执行')).to_be_visible();page.screenshot(path=str(EVIDENCE/'renewal-390.png'));passed('mobile-membership-workflow')
    page.goto(BASE+'/admin/users');page.set_viewport_size({'width':1440,'height':960});page.evaluate("document.documentElement.style.zoom='2'");page.screenshot(path=str(EVIDENCE/'users-zoom-200.png'));assert not page.evaluate('document.documentElement.scrollWidth > innerWidth+1');passed('200-percent-zoom-no-page-overflow')
    page.goto(BASE+'/admin/users?q=not-found');expect(page.locator('.ant-empty-description:visible')).to_be_visible();passed('empty-state')
    page.goto(BASE+'/admin/users');held=[]
    def stale_route(route):
        if 'q=slow' in route.request.url:held.append(route)
        else:route.continue_()
    page.route('**/admin/api/users?*',stale_route)
    search=page.get_by_placeholder('搜索账号、用户 ID、设备或备注');search.fill('slow');page.wait_for_timeout(450)
    search.fill('qa-user-010');expect(page.get_by_text('1–1 条，共 1 条')).to_be_visible()
    for pending in held:
        try:pending.fulfill(content_type='application/json',body='{"items":[],"total":0,"page":1,"page_size":25,"pages":1}')
        except Exception:pass  # AbortController may already have cancelled it.
    expect(page.get_by_role('button',name='qa-user-010',exact=True)).to_be_visible();page.unroute('**/admin/api/users?*');passed('stale-search-response-cannot-overwrite')
    page.goto(BASE+'/admin/users?q=qa-user-000');page.get_by_role('button',name='qa-user-000',exact=True).click()
    note=page.locator('.user-drawer textarea');note.fill('正在编辑备注');page.wait_for_timeout(1200);expect(note).to_be_focused();expect(note).to_have_value('正在编辑备注');passed('countdown-preserves-editor-focus')
    page.route('**/admin/api/users?*',lambda route:route.fulfill(status=500,content_type='application/json',body='{"detail":"QA injected failure"}'))
    page.goto(BASE+'/admin/users?q=failure');expect(page.get_by_text('QA injected failure')).to_be_visible();page.unroute('**/admin/api/users?*');page.get_by_role('button',name='重试',exact=True).click();expect(page.locator('.ant-empty-description:visible')).to_be_visible();passed('500-retry-recovery')
    # Contact configuration only in the isolated DB.
    with app.db() as conn:
        conn.execute('INSERT INTO site_settings VALUES(1,?,?)',(json.dumps({'contact_label':'测试联系','contact_value':'qa-contact','contact_url':'','download_notes':'测试安装说明','help_text':''}),app.now_iso()))
    page.goto(BASE+'/');page.get_by_role('button',name='联系开通',exact=True).first.click();expect(page.get_by_role('dialog')).to_be_visible();expect(page.get_by_text('所选套餐：月度会员 · 联系咨询')).to_be_visible();page.keyboard.press('Escape');passed('contact-plan-and-keyboard-close')
    page.route('**/admin/api/users?*',lambda route:route.fulfill(status=401,content_type='application/json',body='{"detail":"session expired"}'))
    page.goto(BASE+'/admin/users?q=session');expect(page.get_by_text('登录已过期',exact=True)).to_be_visible();passed('session-expiry-recovery-path')
    assert not report['console_errors'],report['console_errors']
    browser.close()
(EVIDENCE/'browser-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
server.should_exit=True
TEMP.cleanup()
print(json.dumps({'checks':len(report['checks']),'viewports':len(report['viewports']),'errors':report['console_errors']},ensure_ascii=False))
