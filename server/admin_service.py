"""Console queries and transactions, shared by modern and legacy endpoints.

FastAPI sync handlers run this blocking SQLite work in its thread pool.
"""
from __future__ import annotations

import csv
import io
import json
import re
import secrets
from datetime import timedelta, timezone

from fastapi import HTTPException

USER_FIELDS = ('id', 'username', 'is_member', 'plan', 'member_expires_at', 'is_banned',
               'device_id', 'device_name', 'device_bound_at', 'device_rebind_cooldown_until',
               'note', 'member_version', 'created_at', 'updated_at')
USER_SELECT = ','.join('u.' + field for field in USER_FIELDS)
SITE_DEFAULTS = {'contact_label': '', 'contact_value': '', 'contact_url': '',
                 'download_notes': '', 'help_text': ''}


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def integer(value, default, low, high):
    try:
        parsed = int(default if value is None or value == '' else value)
    except (TypeError, ValueError):
        raise HTTPException(400, '请输入有效的整数')
    if parsed < low or parsed > high:
        raise HTTPException(400, f'数值应在 {low} 至 {high} 之间')
    return parsed


def like(value):
    return '%' + str(value).strip().replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'


class AdminService:
    def __init__(self, core):
        self.c = core

    def user(self, row):
        u = {key: row[key] for key in USER_FIELDS}
        expiry = self.c.parse_dt(u['member_expires_at'])
        u['membership_status'] = ('none' if not u['is_member'] else 'permanent' if u['plan'] == 'permanent'
                                  else 'active' if expiry and expiry > self.c.now_utc() else 'expired')
        u['account_status'] = 'banned' if u['is_banned'] else 'normal'
        u['active'] = self.c.is_active_member(u)
        u['device_rebind_remaining_seconds'] = self.c.seconds_until(u['device_rebind_cooldown_until'])
        return u

    def dates(self, p, clauses, args, field, prefix):
        for suffix, op in [('from', '>='), ('to', '<=')]:
            value = p.get(prefix + '_' + suffix)
            if value:
                dt = self.c.parse_dt(value)
                if not dt:
                    raise HTTPException(400, '日期格式错误')
                clauses.append(field + op + '?')
                args.append(dt.isoformat())

    def user_query(self, p):
        clauses, args = ['1=1'], []
        current = self.c.now_iso()
        q = p.get('q', '').strip()
        if q:
            clauses.append("(u.username LIKE ? ESCAPE '\\' OR u.device_id LIKE ? ESCAPE '\\' OR u.device_name LIKE ? ESCAPE '\\' OR u.note LIKE ? ESCAPE '\\' OR CAST(u.id AS TEXT)=?)")
            args.extend([like(q)] * 4 + [q])
        active = "(u.is_member=1 AND (u.plan='permanent' OR u.member_expires_at>?))"
        status = p.get('status')
        if status in ('active', 'inactive'):
            clauses.append(('NOT ' if status == 'inactive' else '') + active)
            args.append(current)
            if status == 'active':
                clauses.append('u.is_banned=0')
        elif status == 'banned':
            clauses.append('u.is_banned=1')
        elif status == 'expired':
            clauses.append("u.is_member=1 AND u.plan!='permanent' AND (u.member_expires_at IS NULL OR u.member_expires_at<=?)")
            args.append(current)
        elif status == 'expiring':
            clauses.append("u.is_member=1 AND u.plan!='permanent' AND u.member_expires_at>? AND u.member_expires_at<=?")
            args.extend([current, (self.c.now_utc() + timedelta(days=7)).isoformat()])
        if p.get('account') in ('normal', 'banned'):
            clauses.append('u.is_banned=?')
            args.append(int(p['account'] == 'banned'))
        if p.get('plan') in self.c.PLAN_DAYS:
            clauses.append('u.plan=?')
            args.append(p['plan'])
        device = p.get('device')
        if device == 'cooldown':
            clauses.append('u.device_rebind_cooldown_until>?')
            args.append(current)
        elif device == 'bound':
            clauses.append("COALESCE(u.device_id,'')!=''")
        elif device == 'unbound':
            clauses.append("COALESCE(u.device_id,'')=''")
        self.dates(p, clauses, args, 'u.member_expires_at', 'expires')
        self.dates(p, clauses, args, 'u.created_at', 'created')
        orders = {'id_desc': 'u.id DESC', 'id_asc': 'u.id ASC', 'expiry_asc': 'u.member_expires_at ASC,u.id ASC',
                  'expiry_desc': 'u.member_expires_at DESC,u.id DESC', 'name_asc': 'u.username ASC,u.id ASC'}
        return ' AND '.join(clauses), args, orders.get(p.get('sort'), orders['id_desc'])

    def paginate(self, conn, source, fields, clauses, args, order, p):
        size = integer(p.get('page_size'), 25, 1, 100)
        total = conn.execute(f'SELECT COUNT(*) FROM {source} WHERE {clauses}', args).fetchone()[0]
        pages = max(1, (total + size - 1) // size)
        page = min(integer(p.get('page'), 1, 1, 10**9), pages)
        rows = conn.execute(f'SELECT {fields} FROM {source} WHERE {clauses} ORDER BY {order} LIMIT ? OFFSET ?',
                            [*args, size, (page - 1) * size]).fetchall()
        return {'items': [dict(row) for row in rows], 'total': total, 'page': page, 'page_size': size, 'pages': pages}

    def users(self, p):
        with self.c.db() as conn:
            result = self.paginate(conn, 'users u', USER_SELECT, *self.user_query(p), p)
            result['items'] = [self.user(u) for u in result['items']]
            return result

    def detail(self, user_id):
        with self.c.db() as conn:
            row = conn.execute(f'SELECT {USER_SELECT} FROM users u WHERE id=?', (user_id,)).fetchone()
            if not row:
                raise HTTPException(404, '用户不存在或已删除')
            u = self.user(row)
            return {'user': u,
                    'redemptions': [dict(r) for r in conn.execute('SELECT code,plan,custom_days,used_at,batch_id FROM redeem_codes WHERE used_by=? ORDER BY used_at DESC,code DESC LIMIT 25', (user_id,))],
                    'timeline': [dict(r) for r in conn.execute('SELECT * FROM audit_logs WHERE target=? OR actor=? OR target=? ORDER BY id DESC LIMIT 25', (u['username'], u['username'], f'user:{user_id}'))],
                    'active_sessions': conn.execute('SELECT COUNT(*) FROM sessions WHERE user_id=? AND expires_at>?', (user_id, self.c.now_iso())).fetchone()[0]}

    def code_query(self, p):
        clauses, args = ['1=1'], []
        q = p.get('q', '').strip()
        if q:
            # A pasted full code is an exact lookup; partial strings still search
            # code, redeemer and note. Export uses this same query builder.
            with self.c.db() as conn:
                exact = conn.execute('SELECT code FROM redeem_codes WHERE code=?', (q.upper(),)).fetchone()
            if exact:
                clauses.append('c.code=?')
                args.append(exact['code'])
            else:
                clauses.append("(c.code LIKE ? ESCAPE '\\' OR c.used_by_username_snapshot LIKE ? ESCAPE '\\' OR c.note LIKE ? ESCAPE '\\')")
                args.extend([like(q)] * 3)
        status = p.get('status')
        if status == 'used':
            clauses.append('c.used_by IS NOT NULL')
        elif status == 'disabled':
            clauses.append('c.used_by IS NULL AND c.is_disabled=1')
        elif status == 'expired':
            clauses.append('c.used_by IS NULL AND c.is_disabled=0 AND c.expires_at<=?')
            args.append(self.c.now_iso())
        elif status == 'available':
            clauses.append('c.used_by IS NULL AND c.is_disabled=0 AND (c.expires_at IS NULL OR c.expires_at>?)')
            args.append(self.c.now_iso())
        if p.get('used_by'):
            clauses.append('c.used_by=?')
            args.append(integer(p['used_by'], 1, 1, 10**12))
        for key in ('batch_id', 'plan'):
            if p.get(key) and p[key] != 'all':
                clauses.append(f'c.{key}=?')
                args.append(p[key])
        self.dates(p, clauses, args, 'c.created_at', 'created')
        self.dates(p, clauses, args, 'c.expires_at', 'expires')
        if p.get('scope') == 'selected':
            codes = list(dict.fromkeys(p.get('codes', '').split(',')))
            if not codes or not codes[0] or len(codes) > 500:
                raise HTTPException(400, '请选择 1 至 500 个兑换码')
            # A selected export intentionally ignores the current page and filters.
            clauses, args = ['c.code IN (' + ','.join('?' for _ in codes) + ')'], codes
        elif p.get('scope') == 'batch':
            if not p.get('batch_id'):
                raise HTTPException(400, '请选择一个批次')
            clauses, args = ['c.batch_id=?'], [p['batch_id']]
        order = 'c.created_at ASC,c.code ASC' if p.get('sort') == 'created_asc' else 'c.created_at DESC,c.code DESC'
        return ' AND '.join(clauses), args, order

    def code(self, row):
        c = dict(row)
        c['status'] = ('used' if c['used_by'] is not None else 'disabled' if c['is_disabled'] else
                       'expired' if c['expires_at'] and self.c.parse_dt(c['expires_at']) <= self.c.now_utc() else 'available')
        c['used_by_username'] = c.get('used_by_username_snapshot')
        return c

    def codes(self, p):
        with self.c.db() as conn:
            result = self.paginate(conn, 'redeem_codes c', 'c.*', *self.code_query(p), p)
            result['items'] = [self.code(row) for row in result['items']]
            return result

    def export(self, p):
        clauses, args, order = self.code_query(p)
        def stream():
            yield '\ufeff'
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(['兑换码', '套餐', '天数', '状态', '兑换截止时间', '兑换账号', '兑换时间', '批次', '备注'])
            yield output.getvalue()
            with self.c.db() as conn:
                cursor = conn.execute(f'SELECT c.* FROM redeem_codes c WHERE {clauses} ORDER BY {order}', args)
                while True:
                    rows = cursor.fetchmany(500)
                    if not rows:
                        break
                    output.seek(0)
                    output.truncate(0)
                    for row in rows:
                        c = self.code(row)
                        values = [c[k] for k in ('code', 'plan', 'custom_days', 'status', 'expires_at', 'used_by_username_snapshot', 'used_at', 'batch_id', 'note')]
                        writer.writerow(["'" + v if isinstance(v, str) and v.lstrip().startswith(('=', '+', '-', '@', '\t', '\r')) else v for v in values])
                    yield output.getvalue()
        return stream()

    def ids(self, data):
        values = data.get('user_ids') if 'user_ids' in data else [data.get('user_id')]
        if not isinstance(values, list) or not values or len(values) > 100:
            raise HTTPException(400, '请选择 1 至 100 个用户')
        try:
            ids = sorted({int(x) for x in values})
        except (ValueError, TypeError):
            raise HTTPException(400, '用户 ID 格式错误')
        if not ids or len(ids) > 100 or ids[0] < 1:
            raise HTTPException(400, '请选择 1 至 100 个用户')
        return ids

    def operation_id(self, data, required=True):
        value = str(data.get('operation_id') or ('' if required else secrets.token_urlsafe(24)))
        if not re.fullmatch(r'[A-Za-z0-9_-]{8,100}', value):
            raise HTTPException(400, '需要有效的 operation_id')
        return value

    def prior(self, conn, op_id, kind, payload):
        row = conn.execute('SELECT * FROM admin_operations WHERE operation_id=?', (op_id,)).fetchone()
        if row and (row['kind'] != kind or row['payload'] != encoded(payload)):
            raise HTTPException(409, '该操作编号已用于其他请求，请重新开始')
        return dict(row) if row else None

    def put_operation(self, conn, op_id, kind, status, payload, result):
        conn.execute('INSERT INTO admin_operations VALUES(?,?,?,?,?,?)', (op_id, kind, status, encoded(payload), encoded(result), self.c.now_iso()))

    def change(self, u, data):
        action = data.get('action', 'grant')
        after, warning = {}, ''
        if action in ('grant', 'set_membership'):
            plan = data.get('plan', 'month')
            if plan not in self.c.PLAN_DAYS:
                raise HTTPException(400, '会员类型错误')
            if u['is_member'] and u['plan'] == 'permanent':
                return {}, '永久会员无需续费，已跳过'
            expires = None
            if plan != 'permanent':
                days = integer(data.get('custom_days'), 1, 1, 36500) if plan == 'custom' else self.c.PLAN_DAYS[plan]
                current = self.c.parse_dt(u['member_expires_at']) if u['is_member'] else None
                expires = (max(self.c.now_utc(), current or self.c.now_utc()) + timedelta(days=days)).isoformat()
            after = {'is_member': 1, 'plan': plan, 'member_expires_at': expires}
            if u['is_banned']:
                warning = '账号仍保持封禁，续费不会解除封禁'
        elif action == 'adjust_expiry':
            expires = self.c.parse_dt(str(data.get('expires_at') or ''))
            if not expires:
                raise HTTPException(400, '请填写新的到期时间')
            after = {'is_member': 1, 'plan': 'custom', 'member_expires_at': expires.isoformat()}
            if u['plan'] == 'permanent':
                warning = '此次明确调整会把永久会员改为定期会员'
        elif action == 'revoke':
            after = {'is_member': 0, 'plan': None, 'member_expires_at': None}
        elif action in ('ban', 'unban'):
            after = {'is_banned': int(action == 'ban')}
        elif action == 'reset_device':
            after = dict.fromkeys(('device_id', 'device_name', 'device_bound_at', 'device_rebind_cooldown_until'))
        elif action == 'reset_device_cooldown':
            after = {'device_rebind_cooldown_until': None}
        elif action == 'note':
            after = {'note': str(data.get('note') or '')[:1000]}
        else:
            raise HTTPException(400, '未知会员或账号操作')
        return after, warning

    def build_preview(self, conn, data, op_id):
        items = []
        for user_id in self.ids(data):
            row = conn.execute(f'SELECT {USER_SELECT} FROM users u WHERE id=?', (user_id,)).fetchone()
            if not row:
                items.append({'id': user_id, 'status': 'skipped', 'reason': '用户不存在'})
                continue
            u = self.user(row)
            after, warning = self.change(u, data)
            before = {key: u[key] for key in after}
            items.append({'id': user_id, 'username': u['username'], 'version': u['member_version'], 'before': before,
                          'after': after, 'is_banned': u['is_banned'], 'warning': warning,
                          'status': 'ready' if after else 'skipped', 'reason': warning if not after else ''})
        return {'operation_id': op_id, 'action': data.get('action', 'grant'), 'status': 'preview', 'items': items}

    def preview(self, data):
        op_id = self.operation_id(data)
        with self.c.db() as conn:
            conn.execute('BEGIN IMMEDIATE')
            prior = self.prior(conn, op_id, 'users', data)
            if prior:
                return json.loads(prior['result'])
            result = self.build_preview(conn, data, op_id)
            self.put_operation(conn, op_id, 'users', 'preview', data, result)
            return result

    def apply(self, conn, result, ip):
        action = result['action']
        for item in result['items']:
            if item['status'] != 'ready':
                continue
            fields = item['after']
            conn.execute('UPDATE users SET ' + ','.join(key + '=?' for key in fields) + ',updated_at=? WHERE id=?',
                         [*fields.values(), self.c.now_iso(), item['id']])
            if action in ('ban', 'revoke', 'reset_device'):
                conn.execute('DELETE FROM sessions WHERE user_id=?', (item['id'],))
            detail = {'operation_id': result['operation_id'], 'before': item['before'], 'after': fields}
            conn.execute('INSERT INTO audit_logs(actor,action,target,detail,ip,created_at) VALUES(?,?,?,?,?,?)',
                         (self.c.ADMIN_USER, 'user_' + action, item['username'], encoded(detail), ip, self.c.now_iso()))
            item['status'] = 'success'
        result.update(status='completed', ok=True, affected=sum(i['status'] == 'success' for i in result['items']))
        return result

    def commit(self, op_id, ip):
        with self.c.db() as conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute("SELECT * FROM admin_operations WHERE operation_id=? AND kind='users'", (op_id,)).fetchone()
            if not row:
                raise HTTPException(404, '预览不存在，请重新预览')
            result = json.loads(row['result'])
            if row['status'] != 'preview':
                return result
            conflicts = []
            for item in result['items']:
                if item['status'] != 'ready':
                    continue
                u = conn.execute('SELECT member_version FROM users WHERE id=?', (item['id'],)).fetchone()
                if not u or u['member_version'] != item['version']:
                    conflicts.append(item['id'])
            expired = self.c.parse_dt(row['created_at']) + timedelta(minutes=30) < self.c.now_utc()
            if conflicts or expired:
                result.update(status='conflict', conflicts=conflicts, message='会员或账号已变更，或预览已超过 30 分钟。请重新预览。')
            else:
                result = self.apply(conn, result, ip)
            conn.execute('UPDATE admin_operations SET status=?,result=? WHERE operation_id=?', (result['status'], encoded(result), op_id))
            return result

    def legacy_users(self, data, ip, batch=False):
        op_id = self.operation_id(data, False)
        with self.c.db() as conn:
            conn.execute('BEGIN IMMEDIATE')
            prior = self.prior(conn, op_id, 'legacy_users', data)
            if prior:
                return json.loads(prior['result'])
            normalized = dict(data)
            if normalized.get('expires_at') and normalized.get('plan') != 'permanent' and normalized.get('action') in ('grant', 'set_membership'):
                normalized['action'] = 'adjust_expiry'
            result = self.apply(conn, self.build_preview(conn, normalized, op_id), ip)
            if batch:
                self.c.audit(conn, self.c.ADMIN_USER, 'user_batch_' + data['action'], '', encoded({'ids': self.ids(data)}), ip)
            self.put_operation(conn, op_id, 'legacy_users', 'completed', data, result)
            return result

    def generate(self, data, ip):
        op_id = self.operation_id(data, False)
        plan = data.get('plan', 'month')
        if plan not in self.c.PLAN_DAYS:
            raise HTTPException(400, '会员类型错误')
        count = integer(data.get('count'), 1, 1, 500)
        days = integer(data.get('custom_days'), 1, 1, 36500) if plan == 'custom' else None
        expires = self.c.parse_dt(data.get('expires_at')) if data.get('expires_at') else None
        if data.get('expires_at') and not expires:
            raise HTTPException(400, '兑换截止时间格式错误')
        with self.c.db() as conn:
            conn.execute('BEGIN IMMEDIATE')
            prior = self.prior(conn, op_id, 'generate', data)
            if prior:
                return json.loads(prior['result'])
            if expires and expires <= self.c.now_utc():
                raise HTTPException(400, '兑换截止时间必须晚于当前时间')
            batch_id, current = 'B' + secrets.token_hex(10).upper(), self.c.now_iso()
            note, expiry = str(data.get('note') or '')[:1000], expires.isoformat() if expires else None
            codes = [secrets.token_hex(10).upper() for _ in range(count)]
            conn.execute('INSERT INTO code_batches VALUES(?,?,?,?,?,?,?)', (batch_id, plan, days, count, expiry, note, current))
            conn.executemany('INSERT INTO redeem_codes(code,plan,custom_days,batch_id,expires_at,created_at,note) VALUES(?,?,?,?,?,?,?)',
                             [(code, plan, days, batch_id, expiry, current, note) for code in codes])
            result = {'ok': True, 'status': 'completed', 'operation_id': op_id, 'batch_id': batch_id, 'created': codes, 'expires_at': expiry}
            self.put_operation(conn, op_id, 'generate', 'completed', data, result)
            self.c.audit(conn, self.c.ADMIN_USER, 'codes_generate', batch_id, encoded({'count': count, 'plan': plan, 'days': days}), ip)
            return result

    def code_action(self, data, ip):
        action = data.get('action')
        if action not in ('disable', 'enable', 'delete_unused'):
            raise HTTPException(400, '未知兑换码操作')
        supplied = data.get('codes', [])
        if not isinstance(supplied, list) or any(not isinstance(code, str) for code in supplied):
            raise HTTPException(400, '兑换码必须为字符串列表')
        op_id = self.operation_id(data, False)
        with self.c.db() as conn:
            conn.execute('BEGIN IMMEDIATE')
            prior = self.prior(conn, op_id, 'codes', data)
            if prior:
                return json.loads(prior['result'])
            codes = list(dict.fromkeys(data.get('codes') or []))
            if not codes and data.get('batch_id'):
                codes = [r[0] for r in conn.execute('SELECT code FROM redeem_codes WHERE batch_id=? ORDER BY code LIMIT 501', (data['batch_id'],))]
            if not codes or len(codes) > 500:
                raise HTTPException(400, '请选择 1 至 500 个兑换码；大批次请分批选择')
            items = []
            for code in codes:
                row = conn.execute('SELECT * FROM redeem_codes WHERE code=?', (code,)).fetchone()
                reason = ''
                if not row:
                    reason = '不存在'
                elif row['used_by'] is not None:
                    reason = '已使用'
                elif action != 'delete_unused' and row['expires_at'] and self.c.parse_dt(row['expires_at']) <= self.c.now_utc():
                    reason = '已过期'
                elif action != 'delete_unused' and bool(row['is_disabled']) == (action == 'disable'):
                    reason = '状态无需变更'
                if reason:
                    items.append({'code': code, 'status': 'skipped', 'reason': reason})
                    continue
                if action == 'delete_unused':
                    conn.execute('DELETE FROM redeem_codes WHERE code=?', (code,))
                else:
                    conn.execute('UPDATE redeem_codes SET is_disabled=?,disabled_at=? WHERE code=?', (int(action == 'disable'), self.c.now_iso() if action == 'disable' else None, code))
                items.append({'code': code, 'status': 'success', 'reason': ''})
            result = {'ok': True, 'status': 'completed', 'operation_id': op_id, 'matched': len(codes), 'affected': sum(i['status'] == 'success' for i in items), 'items': items}
            self.put_operation(conn, op_id, 'codes', 'completed', data, result)
            self.c.audit(conn, self.c.ADMIN_USER, 'codes_' + action, data.get('batch_id', ''), encoded({'operation_id': op_id, 'affected': result['affected']}), ip)
            return result

    def batches(self, p, batch_id=None):
        clauses, args = ['1=1'], []
        if batch_id:
            clauses.append('b.id=?')
            args.append(batch_id)
        elif p.get('q'):
            clauses.append("(b.id LIKE ? ESCAPE '\\' OR b.note LIKE ? ESCAPE '\\')")
            args.extend([like(p['q'])] * 2)
        with self.c.db() as conn:
            result = self.paginate(conn, 'code_batches b', 'b.*', ' AND '.join(clauses), args, 'b.created_at DESC,b.id DESC', p)
            for row in result['items']:
                counts = conn.execute('''SELECT COUNT(*) total,SUM(used_by IS NOT NULL) used,
                    SUM(used_by IS NULL AND is_disabled=0 AND (expires_at IS NULL OR expires_at>?)) available,
                    SUM(used_by IS NULL AND is_disabled=1) disabled FROM redeem_codes WHERE batch_id=?''', (self.c.now_iso(), row['id'])).fetchone()
                row.update({key: counts[key] or 0 for key in counts.keys()})
            if batch_id:
                if not result['items']:
                    raise HTTPException(404, '批次不存在')
                return result['items'][0]
            return result

    def audit_list(self, p):
        clauses, args = ['1=1'], []
        if p.get('q'):
            clauses.append("(actor LIKE ? ESCAPE '\\' OR target LIKE ? ESCAPE '\\' OR detail LIKE ? ESCAPE '\\')")
            args.extend([like(p['q'])] * 3)
        for key in ('action', 'target'):
            if p.get(key) and p[key] != 'all':
                clauses.append(key + '=?')
                args.append(p[key])
        self.dates(p, clauses, args, 'created_at', 'created')
        with self.c.db() as conn:
            return self.paginate(conn, 'audit_logs', '*', ' AND '.join(clauses), args, 'id DESC', p)

    def settings(self, conn):
        row = conn.execute('SELECT content FROM site_settings WHERE id=1').fetchone()
        return {**SITE_DEFAULTS, **(json.loads(row[0]) if row else {})}

    def summary(self):
        current = self.c.now_iso()
        start = self.c.now_utc().astimezone(timezone(timedelta(hours=8))).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
        with self.c.db() as conn:
            metrics = {
                'users_total': conn.execute('SELECT COUNT(*) FROM users').fetchone()[0],
                'members_active': conn.execute("SELECT COUNT(*) FROM users WHERE is_member=1 AND is_banned=0 AND (plan='permanent' OR member_expires_at>?)", (current,)).fetchone()[0],
                'members_expiring_7d': conn.execute("SELECT COUNT(*) FROM users WHERE is_member=1 AND plan!='permanent' AND member_expires_at>? AND member_expires_at<=?", (current, (self.c.now_utc()+timedelta(days=7)).isoformat())).fetchone()[0],
                'devices_cooling_down': conn.execute('SELECT COUNT(*) FROM users WHERE device_rebind_cooldown_until>?', (current,)).fetchone()[0],
                'codes_available': conn.execute('SELECT COUNT(*) FROM redeem_codes WHERE used_by IS NULL AND is_disabled=0 AND (expires_at IS NULL OR expires_at>?)', (current,)).fetchone()[0],
                'codes_disabled': conn.execute('SELECT COUNT(*) FROM redeem_codes WHERE used_by IS NULL AND is_disabled=1').fetchone()[0],
                'codes_expired': conn.execute('SELECT COUNT(*) FROM redeem_codes WHERE used_by IS NULL AND is_disabled=0 AND expires_at<=?', (current,)).fetchone()[0],
                'registrations_today': conn.execute('SELECT COUNT(*) FROM users WHERE created_at>=? AND created_at<?', (start.isoformat(), (start+timedelta(days=1)).isoformat())).fetchone()[0],
                'redeemed_today': conn.execute('SELECT COUNT(*) FROM redeem_codes WHERE used_at>=? AND used_at<?', (start.isoformat(), (start+timedelta(days=1)).isoformat())).fetchone()[0],
            }
            return {'metrics': metrics, 'plans': self.c.PLAN_LABELS, 'release': self.c.release_payload(self.c.get_release(conn)),
                    'pricing': self.c.pricing_payload(conn), 'server_version': self.c.SERVER_VERSION,
                    'release_history': [dict(r) for r in conn.execute('SELECT * FROM app_release_history ORDER BY id DESC LIMIT 20')],
                    'code_batches': [dict(r) for r in conn.execute('SELECT id batch_id,quantity total,note,created_at,(SELECT COUNT(*) FROM redeem_codes c WHERE c.batch_id=b.id AND c.used_by IS NULL) unused FROM code_batches b ORDER BY created_at DESC LIMIT 100')],
                    'device_rebind_cooldown_hours': self.c.DEVICE_REBIND_COOLDOWN_HOURS}
