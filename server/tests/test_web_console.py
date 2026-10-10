import concurrent.futures
import csv
import io
import json
import re
import sqlite3
import threading
import time
import uuid
from datetime import timedelta
from unittest.mock import patch

import test_security


class WebConsoleTests(test_security.SecurityFlowTests):
    # Reuse the authenticated test fixture but do not inherit/re-run its test cases.
    def make_user(self, **overrides):
        values = {'username': 'web-' + uuid.uuid4().hex[:14], 'password_hash': self.server.hash_password('UserPass123!'),
                  'is_member': 1, 'plan': 'month', 'member_expires_at': (self.server.now_utc()+timedelta(days=42)).isoformat(),
                  'created_at': self.server.now_iso(), 'updated_at': self.server.now_iso(), **overrides}
        with self.server.db() as conn:
            cur = conn.execute('INSERT INTO users(' + ','.join(values) + ') VALUES(' + ','.join('?' for _ in values) + ')', list(values.values()))
            return cur.lastrowid

    def test_web_pagination_137_and_detail_whitelist(self):
        prefix = 'page-' + uuid.uuid4().hex[:10]
        with self.server.db() as conn:
            conn.executemany('INSERT INTO users(username,password_hash,created_at,updated_at) VALUES(?,?,?,?)',
                             [(prefix+str(i), 'unused-hash', self.server.now_iso(), self.server.now_iso()) for i in range(137)])
        admin, headers = self.login_admin()
        with admin:
            first = admin.get('/admin/api/users', params={'q': prefix}).json()
            self.assertEqual((first['total'], first['pages'], len(first['items'])), (137, 6, 25))
            last = admin.get('/admin/api/users', params={'q': prefix, 'page': 6}).json()
            self.assertEqual(len(last['items']), 12)
            self.assertTrue(set(u['id'] for u in first['items']).isdisjoint(u['id'] for u in last['items']))
            detail = admin.get('/admin/api/users/'+str(first['items'][0]['id'])).json()
            self.assertNotIn('password_hash', detail['user'])
            self.assertNotIn('session_token', detail['user'])
            ids = [first['items'][0]['id'],last['items'][0]['id']]
            preview = admin.post('/admin/api/membership/preview', headers=headers, json={'operation_id':uuid.uuid4().hex,'user_ids':ids,'action':'grant','plan':'month'}).json()
            result = admin.post('/admin/api/membership/commit', headers=headers,json={'operation_id':preview['operation_id']})
            self.assertEqual(result.status_code,200,result.text)
            with self.server.db() as conn:
                self.assertEqual(conn.execute('SELECT COUNT(*) FROM users WHERE username LIKE ? AND is_member=1',(prefix+'%',)).fetchone()[0],2)

    def test_web_renewal_permanent_banned_expired_and_replay(self):
        ids = [self.make_user(),self.make_user(plan='permanent',member_expires_at=None),self.make_user(is_banned=1),self.make_user(member_expires_at=(self.server.now_utc()-timedelta(days=5)).isoformat())]
        admin, headers = self.login_admin()
        with admin:
            payload={'operation_id':uuid.uuid4().hex,'user_ids':ids,'action':'grant','plan':'month'}
            p=admin.post('/admin/api/membership/preview',json=payload,headers=headers)
            self.assertEqual(p.status_code,200,p.text)
            self.assertEqual(p.json(),admin.post('/admin/api/membership/preview',json=payload,headers=headers).json())
            result=admin.post('/admin/api/membership/commit',json={'operation_id':payload['operation_id']},headers=headers)
            self.assertEqual(result.json()['affected'],3)
            self.assertEqual(result.json(),admin.post('/admin/api/membership/commit',json={'operation_id':payload['operation_id']},headers=headers).json())
            with self.server.db() as conn:
                users=[dict(conn.execute('SELECT * FROM users WHERE id=?',(i,)).fetchone()) for i in ids]
            self.assertAlmostEqual((self.server.parse_dt(users[0]['member_expires_at'])-self.server.now_utc()).total_seconds()/86400,73,places=3)
            self.assertEqual(users[1]['plan'],'permanent')
            self.assertEqual(users[2]['is_banned'],1)
            self.assertAlmostEqual((self.server.parse_dt(users[3]['member_expires_at'])-self.server.now_utc()).total_seconds()/86400,31,places=3)
            self.assertEqual(admin.post('/admin/api/membership/preview',json={**payload,'plan':'year'},headers=headers).status_code,409)

    def test_web_preview_detects_redemption_and_legacy_change(self):
        user_id=self.make_user()
        admin,headers=self.login_admin()
        with admin:
            p=admin.post('/admin/api/membership/preview',json={'operation_id':uuid.uuid4().hex,'user_ids':[user_id],'action':'grant','plan':'month'},headers=headers).json()
            admin.post('/admin/api/user_action',json={'user_id':user_id,'action':'grant','plan':'quarter'},headers=headers)
            result=admin.post('/admin/api/membership/commit',json={'operation_id':p['operation_id']},headers=headers)
            self.assertEqual(result.status_code,409,result.text)
            self.assertEqual(result.json()['status'],'conflict')
            status=admin.get('/admin/api/operations/'+p['operation_id']).json()
            self.assertEqual(status['status'],'conflict')

    def test_web_generate_100_retry_and_filtered_export(self):
        admin,headers=self.login_admin()
        with admin:
            payload={'operation_id':uuid.uuid4().hex,'plan':'month','count':100,'note':'csv scope'}
            first=admin.post('/admin/api/create_codes',json=payload,headers=headers)
            self.assertEqual(first.status_code,200,first.text)
            retry=admin.post('/admin/api/create_codes',json=payload,headers=headers)
            self.assertEqual(first.json(),retry.json())
            result=first.json()
            with self.server.db() as conn:
                self.assertEqual(conn.execute('SELECT COUNT(*) FROM redeem_codes WHERE batch_id=?',(result['batch_id'],)).fetchone()[0],100)
            csv_response=admin.get('/admin/api/codes/export',params={'q':result['created'][0]})
            rows=list(csv.reader(io.StringIO(csv_response.text.lstrip('\ufeff'))))
            self.assertEqual(len(rows),2)
            self.assertEqual(rows[1][0],result['created'][0])
            self.assertEqual(admin.get('/admin/api/batches/'+result['batch_id']).json()['available'],100)
            self.assertEqual(admin.get('/admin/api/operations/'+payload['operation_id']).json(),result)
            selected=admin.get('/admin/api/codes/export',params={'scope':'selected','codes':','.join(result['created'][:2]),'q':'no-match'})
            self.assertEqual(len(list(csv.reader(io.StringIO(selected.text.lstrip('\ufeff'))))),3)

    def test_web_enable_does_not_revive_expired_or_used(self):
        admin,headers=self.login_admin()
        with admin:
            codes=admin.post('/admin/api/create_codes',json={'plan':'month','count':3},headers=headers).json()['created']
            with self.server.db() as conn:
                conn.execute('UPDATE redeem_codes SET is_disabled=1 WHERE code IN (?,?,?)',codes)
                conn.execute('UPDATE redeem_codes SET expires_at=? WHERE code=?',((self.server.now_utc()-timedelta(days=1)).isoformat(),codes[0]))
                conn.execute('UPDATE redeem_codes SET used_by=999 WHERE code=?',(codes[1],))
            result=admin.post('/admin/api/code_action',json={'operation_id':uuid.uuid4().hex,'codes':codes,'action':'enable'},headers=headers).json()
            self.assertEqual(result['affected'],1)
            self.assertEqual([r['reason'] for r in result['items'][:2]],['已过期','已使用'])

    def test_web_stored_digest_cannot_authenticate(self):
        username=self.unique_user('digest-bearer')
        login=self.register_and_login(username,'digest-device')
        with self.server.db() as conn:
            conn.execute("UPDATE users SET is_member=1,plan='permanent' WHERE username=?",(username,))
        raw=login['token']
        good=self.client.post('/api/auth/verify',json={'token':raw,'device_id':'digest-device'})
        bad=self.client.post('/api/auth/verify',json={'token':self.server.token_digest(raw),'device_id':'digest-device'})
        self.assertEqual(good.status_code,200,good.text)
        self.assertEqual(bad.status_code,401,bad.text)

    def test_web_backup_includes_uncheckpointed_wal(self):
        conn=sqlite3.connect(self.server.DB_PATH)
        try:
            conn.execute('PRAGMA wal_autocheckpoint=0')
            name='wal-'+uuid.uuid4().hex
            conn.execute('INSERT INTO users(username,password_hash,created_at,updated_at) VALUES(?,?,?,?)',(name,'test',self.server.now_iso(),self.server.now_iso()))
            conn.commit()
            backup=self.server.backup_database('test_web')
            restored=sqlite3.connect(backup)
            try:
                self.assertEqual(restored.execute('PRAGMA integrity_check').fetchone()[0],'ok')
                self.assertEqual(restored.execute('SELECT COUNT(*) FROM users WHERE username=?',(name,)).fetchone()[0],1)
            finally:
                restored.close()
        finally:
            conn.close()

    def test_web_concurrent_rebind_only_one_wins(self):
        username=self.unique_user('race')
        self.register_and_login(username,'original-device')
        barrier=threading.Barrier(2)
        original=self.server.verify_password
        def verify(*args):
            result=original(*args)
            barrier.wait(timeout=10)
            return result
        def login(device):
            return self.client.post('/api/auth/login',json={'username':username,'password':'UserPass123!','device_id':device}).status_code
        with patch.object(self.server,'verify_password',verify),concurrent.futures.ThreadPoolExecutor(2) as pool:
            results=list(pool.map(login,['race-a','race-b']))
        self.assertEqual(sorted(results),[200,423])

    def test_web_all_write_endpoints_require_csrf(self):
        admin,headers=self.login_admin()
        with admin:
            for path in ('membership/preview','membership/commit','site','create_codes','code_action','release'):
                self.assertEqual(admin.post('/admin/api/'+path,json={}).status_code,403,path)

    def test_web_redemption_conflicts_with_membership_preview(self):
        username=self.unique_user('preview-redeem')
        login=self.register_and_login(username,'preview-device')
        with self.server.db() as conn:
            user_id=conn.execute('SELECT id FROM users WHERE username=?',(username,)).fetchone()[0]
        admin,headers=self.login_admin()
        with admin:
            preview=admin.post('/admin/api/membership/preview',json={'operation_id':uuid.uuid4().hex,'user_ids':[user_id],'action':'grant','plan':'month'},headers=headers).json()
            code=admin.post('/admin/api/create_codes',json={'plan':'month','count':1},headers=headers).json()['created'][0]
            redeemed=self.client.post('/api/redeem',json={'token':login['token'],'device_id':'preview-device','code':code})
            self.assertEqual(redeemed.status_code,200,redeemed.text)
            committed=admin.post('/admin/api/membership/commit',json={'operation_id':preview['operation_id']},headers=headers)
            self.assertEqual(committed.status_code,409,committed.text)
            with self.server.db() as conn:
                detail=json.loads(conn.execute("SELECT detail FROM audit_logs WHERE action='redeem' AND target=?",(code,)).fetchone()[0])
            self.assertEqual(detail['before']['is_member'],0)
            self.assertEqual(detail['after']['is_member'],1)

    def test_web_locked_write_does_not_block_health(self):
        user_id=self.make_user()
        admin,headers=self.login_admin()
        lock=sqlite3.connect(self.server.DB_PATH,check_same_thread=False)
        lock.execute('BEGIN IMMEDIATE')
        release=threading.Timer(1.0,lock.rollback)
        release.start()
        try:
            with concurrent.futures.ThreadPoolExecutor(1) as pool:
                future=pool.submit(admin.post,'/admin/api/user_action',json={'user_id':user_id,'action':'grant','plan':'month'},headers=headers)
                time.sleep(.1)
                start=time.perf_counter();health=self.client.get('/api/health');elapsed=time.perf_counter()-start
                self.assertEqual(health.status_code,200)
                self.assertLess(elapsed,.7,'Health request was blocked behind a SQLite writer')
                self.assertEqual(future.result(timeout=5).status_code,200)
        finally:
            release.join();lock.close();admin.close()

    def test_web_batch_limits_and_empty_explicit_selection(self):
        admin,headers=self.login_admin()
        with admin:
            for ids in ([],list(range(1,102)),[None]):
                result=admin.post('/admin/api/membership/preview',json={'operation_id':uuid.uuid4().hex,'user_ids':ids,'user_id':1,'action':'grant','plan':'month'},headers=headers)
                self.assertEqual(result.status_code,400,result.text)
            result=admin.post('/admin/api/code_action',json={'action':'disable','codes':[str(i) for i in range(501)]},headers=headers)
            self.assertEqual(result.status_code,400,result.text)


# unittest would otherwise also collect inherited compatibility tests twice.
for _name in list(vars(test_security.SecurityFlowTests)):
    if _name.startswith('test_'):
        setattr(WebConsoleTests, _name, None)
