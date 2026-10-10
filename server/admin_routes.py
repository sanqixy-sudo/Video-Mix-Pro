from __future__ import annotations

import html
import json
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from admin_service import AdminService, SITE_DEFAULTS, encoded


def install(app, core):
    service = AdminService(core)
    router = APIRouter()
    # Both console UIs share these adapters. Client auth, redemption and updates
    # remain in app.py, unchanged in URL and response contract.

    @router.get('/admin/api/session')
    def session(request: Request):
        session = core.require_admin(request)
        return {'username': core.ADMIN_USER, 'csrf_token': session.csrf_token, 'expires_at': session.expires_at.isoformat()}

    @router.get('/admin/api/users')
    def users(request: Request):
        core.require_admin(request)
        return service.users(dict(request.query_params))

    @router.get('/admin/api/users/{user_id}')
    def user_detail(user_id: int, request: Request):
        core.require_admin(request)
        return service.detail(user_id)

    @router.post('/admin/api/membership/preview')
    def preview(request: Request, data: dict):
        core.require_admin(request, require_csrf=True)
        return service.preview(data)

    @router.post('/admin/api/membership/commit')
    def commit(request: Request, data: dict):
        core.require_admin(request, require_csrf=True)
        result = service.commit(service.operation_id(data), core.client_ip(request))
        return JSONResponse(result, status_code=409 if result['status'] == 'conflict' else 200)

    @router.get('/admin/api/operations/{operation_id}')
    def operation(operation_id: str, request: Request):
        core.require_admin(request)
        with core.db() as conn:
            row = conn.execute('SELECT result FROM admin_operations WHERE operation_id=?', (operation_id,)).fetchone()
        if not row:
            raise HTTPException(404, '操作尚未找到，可用原请求重试')
        return json.loads(row[0])

    @router.post('/admin/api/user_action')
    def user_action(request: Request, data: dict):
        core.require_admin(request, require_csrf=True)
        if data.get('action') in ('change_password', 'delete_user'):
            return core.user_action(request, data)
        return service.legacy_users(data, core.client_ip(request))

    @router.post('/admin/api/user_batch_action')
    def user_batch(request: Request, data: dict):
        core.require_admin(request, require_csrf=True)
        return service.legacy_users(data, core.client_ip(request), batch=True)

    @router.get('/admin/api/codes')
    def codes(request: Request):
        core.require_admin(request)
        return service.codes(dict(request.query_params))

    @router.get('/admin/api/codes/export')
    def export(request: Request):
        core.require_admin(request)
        return StreamingResponse(service.export(dict(request.query_params)), media_type='text/csv; charset=utf-8',
                                 headers={'Content-Disposition': 'attachment; filename="redeem-codes.csv"', **core.NO_STORE_HEADERS})

    @router.post('/admin/api/create_codes')
    def generate(request: Request, data: dict):
        core.require_admin(request, require_csrf=True)
        return service.generate(data, core.client_ip(request))

    @router.post('/admin/api/code_action')
    def code_action(request: Request, data: dict):
        core.require_admin(request, require_csrf=True)
        return service.code_action(data, core.client_ip(request))

    @router.get('/admin/api/batches')
    def batches(request: Request):
        core.require_admin(request)
        return service.batches(dict(request.query_params))

    @router.get('/admin/api/batches/{batch_id}')
    def batch(batch_id: str, request: Request):
        core.require_admin(request)
        return service.batches({}, batch_id)

    @router.get('/admin/api/audit')
    def audit(request: Request):
        core.require_admin(request)
        result = service.audit_list(dict(request.query_params))
        with core.db() as conn:
            result['actions'] = [r[0] for r in conn.execute('SELECT DISTINCT action FROM audit_logs ORDER BY action')]
        return result

    @router.get('/admin/api/summary')
    def summary(request: Request):
        core.require_admin(request)
        return service.summary()

    @router.get('/admin/api/site')
    def settings(request: Request):
        core.require_admin(request)
        with core.db() as conn:
            return {'settings': service.settings(conn), 'pricing': core.pricing_payload(conn)}

    @router.post('/admin/api/site')
    def update_settings(request: Request, data: dict):
        core.require_admin(request, require_csrf=True)
        values = {key: str(data.get(key) or '').strip() for key in SITE_DEFAULTS}
        if any(len(value) > 4000 for value in values.values()):
            raise HTTPException(400, '单项内容不能超过 4000 字')
        url = values['contact_url']
        if url and (urlparse(url).scheme != 'https' or not urlparse(url).hostname or urlparse(url).username):
            raise HTTPException(400, '联系地址必须为有效的 HTTPS 地址')
        with core.db() as conn:
            before = service.settings(conn)
            conn.execute('INSERT INTO site_settings VALUES(1,?,?) ON CONFLICT(id) DO UPDATE SET content=excluded.content,updated_at=excluded.updated_at', (encoded(values), core.now_iso()))
            core.audit(conn, core.ADMIN_USER, 'site_update', 'site', encoded({'before': before, 'after': values}), core.client_ip(request))
        return {'ok': True, 'settings': values}

    @router.get('/admin/api/releases')
    def releases(request: Request):
        core.require_admin(request)
        with core.db() as conn:
            return {'release': dict(conn.execute("SELECT * FROM app_releases WHERE channel='stable'").fetchone()),
                    'history': service.paginate(conn, 'app_release_history', '*', '1=1', [], 'id DESC', dict(request.query_params))}

    @router.post('/admin/api/release')
    def publish(request: Request, data: dict):
        core.require_admin(request, require_csrf=True)
        release = core.normalize_release_data(data)
        portable = core.normalize_release_data({**data, 'download_url': data.get('portable_url', ''), 'sha256': data.get('portable_sha256', '')})
        release.update(portable_url=portable['download_url'], portable_sha256=portable['sha256'])
        with core.db() as conn:
            conn.execute('BEGIN IMMEDIATE')
            before = dict(conn.execute("SELECT * FROM app_releases WHERE channel='stable'").fetchone())
            for key in ('portable_url', 'portable_sha256'):
                if key not in data:
                    release[key] = before[key]
            if data.get('expected_updated_at') and data['expected_updated_at'] != before['updated_at']:
                raise HTTPException(409, '版本信息已经变更，请重新加载后核对草稿')
            current = core.now_iso()
            conn.execute('UPDATE app_releases SET ' + ','.join(key + '=?' for key in release) + ",updated_at=? WHERE channel='stable'", [*release.values(), current])
            keys = ','.join(release)
            conn.execute(f'INSERT INTO app_release_history(channel,{keys},published_at,published_by) VALUES(' + ','.join('?' for _ in range(len(release)+3)) + ')', ['stable', *release.values(), current, core.ADMIN_USER])
            core.audit(conn, core.ADMIN_USER, 'release_update', release['latest_version'], encoded({'before': before['latest_version'], 'after': release['latest_version']}), core.client_ip(request))
            return {'ok': True, 'release': core.release_payload(core.get_release(conn))}

    @router.get('/', response_class=HTMLResponse)
    def website():
        with core.db() as conn:
            release = dict(conn.execute("SELECT * FROM app_releases WHERE channel='stable'").fetchone())
            settings = service.settings(conn)
            pricing = core.pricing_payload(conn)
        payload = {'release': release, 'settings': settings, 'pricing': pricing}
        # JSON is data, never inserted as executable script or interpreted HTML.
        data = encoded(payload).replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
        return HTMLResponse(core.render_template('site-v3.html', {'APP_VERSION': html.escape(release['latest_version']), 'SITE_DATA': data}), headers={'Cache-Control': 'no-cache'})

    @router.get('/admin/legacy', response_class=HTMLResponse)
    def legacy(request: Request):
        return core.admin_page(request)

    app.include_router(router)
    dist = core.BASE_DIR / 'web-admin' / 'dist'
    if (dist / 'assets').is_dir():
        app.mount('/admin/assets', StaticFiles(directory=dist / 'assets'), name='admin-assets')

    @app.get('/admin', response_class=HTMLResponse)
    def entry(request: Request):
        return shell(request)

    @app.get('/admin/{path:path}', response_class=HTMLResponse)
    def shell(request: Request, path: str = ''):
        if path.startswith(('api/', 'assets/')):
            raise HTTPException(404, '地址不存在')
        current = core.admin_session_from_request(request)
        if not current:
            return HTMLResponse(core.render_template('admin-login.html', {'BUILD_ID': core.ADMIN_FRONTEND_BUILD}), headers=core.NO_STORE_HEADERS)
        if not (dist / 'index.html').is_file() or core.env_bool('ADMIN_USE_LEGACY', False):
            return core.admin_page(request)
        if not path:
            return RedirectResponse('/admin/users', status_code=307)
        content = (dist / 'index.html').read_text(encoding='utf-8')
        content = content.replace('__CSRF_TOKEN__', html.escape(current[1].csrf_token))
        return HTMLResponse(content, headers=core.NO_STORE_HEADERS)
