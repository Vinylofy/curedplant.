import os, tempfile, subprocess, time, uuid
import psycopg
from scripts.workers.album_offer_sources import claim
name='codex-album-claim-'+uuid.uuid4().hex[:10]
with tempfile.TemporaryDirectory() as temp:
 sock=os.path.join(temp,'socket');os.mkdir(sock);os.chmod(sock,0o777)
 subprocess.run(['docker','run','--name',name,'--network','none','-v',sock+':/var/run/postgresql','-e','POSTGRES_HOST_AUTH_METHOD=trust','-d','postgres:16-alpine'],check=True,stdout=subprocess.DEVNULL)
 try:
  for i in range(60):
   if subprocess.run(['docker','exec',name,'pg_isready','-U','postgres'],stdout=subprocess.DEVNULL).returncode==0:break
   time.sleep(.25)
  with psycopg.connect(host=sock,user='postgres',dbname='postgres',autocommit=True) as c:
   c.execute('create table shops(id uuid primary key,domain text)')
   c.execute("""create table album_offer_queue(id uuid primary key,shop_id uuid,status text,reason text,source_input jsonb default '{}'::jsonb,next_attempt_at timestamptz default now(),lease_until timestamptz,updated_at timestamptz default now(),claim_token uuid,source_attempts int default 0)""")
   c.execute("insert into shops values('00000000-0000-0000-0000-000000000001','muziker.nl')")
   for i in range(1,8):
    c.execute("insert into album_offer_queue(id,shop_id,status,reason,source_input) values(%s,'00000000-0000-0000-0000-000000000001','source_review','fresh_listing_or_visible_own_price_required','{\"validator_revision\":5}')",(f'10000000-0000-0000-0000-{i:012d}',))
   rows,_=claim(c,50);assert len(rows)==5, len(rows)
   print('PASS: five targeted open records claimed')
   c.execute('update album_offer_queue set claim_token=null,lease_until=null')
   c.execute("insert into album_offer_queue(id,shop_id,status,reason,next_attempt_at) values('20000000-0000-0000-0000-000000000001','00000000-0000-0000-0000-000000000001','source_retry','HTTP_429',now()+interval '6 hours')")
   rows,_=claim(c,50);assert not rows,len(rows)
   print('PASS: active HTTP 429 cooldown prevents review retries')
 finally:
  subprocess.run(['docker','exec','-u','0',name,'sh','-c','rm -f /var/run/postgresql/.s.PGSQL.*; chmod 0777 /var/run/postgresql'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
  subprocess.run(['docker','rm','-f',name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
