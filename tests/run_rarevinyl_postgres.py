"""Run integration tests in a network-isolated, disposable PostgreSQL container."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from uuid import uuid4

def main():
    docker = ['docker', '--host=unix:///var/run/docker.sock']
    env = {k:v for k,v in os.environ.items() if k not in {'DOCKER_HOST','DOCKER_CONTEXT','DOCKER_TLS','DOCKER_TLS_VERIFY','DOCKER_CERT_PATH','DATABASE_URL'}}
    name = 'rarevinyl-test-' + uuid4().hex[:10]
    with tempfile.TemporaryDirectory(prefix='rarevinyl-test-') as tmp:
        socket = Path(tmp)/'socket'
        socket.mkdir(); socket.chmod(0o777)
        subprocess.run(docker+['run','--name',name,'--network','none','-v',str(socket)+':/var/run/postgresql','-e','POSTGRES_HOST_AUTH_METHOD=trust','-d','postgres:16-alpine'],env=env,check=True,stdout=subprocess.DEVNULL)
        try:
            for _ in range(80):
                if subprocess.run(docker+['exec',name,'pg_isready','-h','127.0.0.1','-U','postgres'],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode == 0: break
                time.sleep(.25)
            else: raise RuntimeError('Test database did not start')
            env['RAREVINYL_TEST_DATABASE_URL'] = f'host={socket} user=postgres dbname=postgres'
            return subprocess.run([sys.executable,'-m','unittest','tests.test_rarevinyl_staging_postgres','-v'],env=env).returncode
        finally:
            subprocess.run(docker+['exec','-u','0',name,'sh','-c','rm -f /var/run/postgresql/.s.PGSQL.*; chmod 0777 /var/run/postgresql'],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            subprocess.run(docker+['rm','-f',name],env=env,stdout=subprocess.DEVNULL)

if __name__ == '__main__': raise SystemExit(main())
