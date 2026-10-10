"""10k users / 100k codes: same machine, same queries before/after indexes."""
import json
import os
import platform
import statistics
import sys
import tempfile
import time
import tracemalloc
from datetime import timedelta
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
temporary=tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ.update(DB_PATH=str(Path(temporary.name)/'bench.db'),ENVIRONMENT='development')
import app
from admin_service import AdminService

INDEXES={
    'idx_codes_order': 'CREATE INDEX IF NOT EXISTS idx_codes_order ON redeem_codes(created_at DESC,code DESC)',
    'idx_codes_state_order': 'CREATE INDEX IF NOT EXISTS idx_codes_state_order ON redeem_codes(used_by,is_disabled,created_at DESC,code DESC,expires_at)',
    'idx_codes_batch_order': 'CREATE INDEX IF NOT EXISTS idx_codes_batch_order ON redeem_codes(batch_id,created_at DESC,code DESC)',
    'idx_users_member_expiry': "CREATE INDEX IF NOT EXISTS idx_users_member_expiry ON users(member_expires_at,id) WHERE is_member=1 AND plan!='permanent'",
}
app.init_db();keeper=app.db();service=AdminService(app);current=app.now_iso()
with app.db() as conn:
    conn.executemany('INSERT INTO users(username,password_hash,is_member,plan,member_expires_at,created_at,updated_at) VALUES(?,?,1,?,?,?,?)',
        [(f'bench-{i:05d}','test','month',(app.now_utc()+timedelta(days=i%90)).isoformat(),current,current) for i in range(10000)])
    conn.executemany('INSERT INTO redeem_codes(code,plan,batch_id,is_disabled,used_by,created_at,note) VALUES(?,?,?,?,?,?,?)',
        [(f'BENCH{i:015d}','month',f'B{i//1000:03d}',int(i%7==0),1 if i%3==0 else None,(app.now_utc()-timedelta(seconds=i)).isoformat(),'synthetic') for i in range(100000)])
    conn.executemany('INSERT INTO code_batches(id,plan,quantity,created_at) VALUES(?,?,?,?)',[(f'B{i:03d}','month',1000,current) for i in range(100)])
    for name in INDEXES: conn.execute('DROP INDEX IF EXISTS '+name)

cases={'users_first':lambda:service.users({}), 'users_expiring':lambda:service.users({'status':'expiring'}),
       'codes_first':lambda:service.codes({}), 'codes_available':lambda:service.codes({'status':'available'}),
       'codes_search_one':lambda:service.codes({'q':'BENCH000000000050000'}),
       'codes_batch':lambda:service.codes({'batch_id':'B050'}),'batches_first':lambda:service.batches({})}
def measure():
    result={}
    for name,fn in cases.items():
        fn();times=[]
        for _ in range(12):
            start=time.perf_counter();value=fn();times.append((time.perf_counter()-start)*1000)
        result[name]={'median_ms':round(statistics.median(times),3),'p95_ms':round(sorted(times)[-1],3),'total':value['total']}
    return result
report={'environment':{'platform':platform.platform(),'python':platform.python_version(),'sqlite':app.sqlite3.sqlite_version,'users':10000,'codes':100000,'samples':12,'scope':'sync service queries, warm cache; not a production SLA'},'before_indexes':measure()}
with app.db() as conn:
    clause,args,order=service.code_query({'batch_id':'B050'})
    sql=f'SELECT * FROM redeem_codes c WHERE {clause} ORDER BY {order} LIMIT 25'
    report['batch_plan_before']=[r[3] for r in conn.execute('EXPLAIN QUERY PLAN '+sql,args)]
    for statement in INDEXES.values():conn.execute(statement)
    report['batch_plan_after']=[r[3] for r in conn.execute('EXPLAIN QUERY PLAN '+sql,args)]
report['after_indexes']=measure()
tracemalloc.start();start=time.perf_counter();chunks=0;size=0
for chunk in service.export({}):chunks+=1;size+=len(chunk.encode('utf-8'))
_,peak=tracemalloc.get_traced_memory();tracemalloc.stop()
report['export']={'codes':100000,'chunks':chunks,'bytes':size,'peak_python_bytes':peak,'seconds_with_tracemalloc':round(time.perf_counter()-start,3)}
out=ROOT.parent/'docs'/'verification';out.mkdir(exist_ok=True,parents=True)
(out/'performance.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False,indent=2))
keeper.close()
temporary.cleanup()
