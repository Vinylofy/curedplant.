"""Run disposable PostgreSQL without any network interface or production secrets."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import time
from uuid import uuid4

def main():
    root=Path(__file__).resolve().parents[1]
    name='velvet-test-'+uuid4().hex[:12]
    env={k:v for k,v in os.environ.items() if k not in {'DOCKER_HOST','DOCKER_CONTEXT','DOCKER_TLS','DOCKER_TLS_VERIFY','DOCKER_CERT_PATH','DATABASE_URL'}}
    docker=['docker','--host=unix:///var/run/docker.sock']
    with tempfile.TemporaryDirectory(prefix='velvet-postgres-') as tmp:
        socket=Path(tmp)/'socket';socket.mkdir();socket.chmod(0o777)
        subprocess.run(docker+['run','--name',name,'--network','none','-v',f'{socket}:/var/run/postgresql','-e','POSTGRES_HOST_AUTH_METHOD=trust','-d','postgres:17-alpine'],env=env,check=True,stdout=subprocess.DEVNULL)
        try:
            for _ in range(80):
                if subprocess.run(docker+['exec',name,'pg_isready','-h','127.0.0.1','-U','postgres'],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode==0:break
                time.sleep(.25)
            else:raise RuntimeError('Disposable PostgreSQL did not become ready')
            env['VELVET_TEST_DATABASE_URL']=f'host={socket} user=postgres dbname=postgres'
            return subprocess.run([sys.executable,'-m','unittest','tests.test_velvetdelft_postgres','-v'],cwd=root,env=env).returncode
        finally:
            subprocess.run(docker+['exec','--user','root',name,'chmod','0777','/var/run/postgresql'],env=env,stdout=subprocess.DEVNULL)
            subprocess.run(docker+['rm','-f',name],env=env,stdout=subprocess.DEVNULL)

if __name__=='__main__':raise SystemExit(main())
