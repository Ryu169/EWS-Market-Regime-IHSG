"""Mulai PostgreSQL khusus proyek dan dashboard lokal. Ctrl+C untuk berhenti."""
import argparse
import os
from pathlib import Path
import shlex
import shutil
import socket
import subprocess
import sys
import threading
import webbrowser

HERE = Path(__file__).resolve().parent
LOCAL = HERE / '.local'
PG_DATA = LOCAL / 'postgres'


def pg_binary(name):
    found = shutil.which(name)
    if found:
        return found
    for prefix in ['/opt/homebrew/opt/postgresql@16/bin', '/usr/local/opt/postgresql@16/bin']:
        candidate = Path(prefix) / name
        if candidate.exists():
            return str(candidate)
    raise RuntimeError('PostgreSQL belum tersedia. Pasang PostgreSQL 16 atau atur DATABASE_URL ke server sendiri.')


def ensure_postgres():
    if os.environ.get('DATABASE_URL'):
        return False
    LOCAL.mkdir(exist_ok=True)
    socket_dir = LOCAL / 'socket'
    socket_dir.mkdir(exist_ok=True)
    if not (PG_DATA / 'PG_VERSION').exists():
        subprocess.run([pg_binary('initdb'), '-D', str(PG_DATA), '--auth=trust', '--encoding=UTF8', '--locale=C'], check=True)
    running = subprocess.run([pg_binary('pg_ctl'), '-D', str(PG_DATA), 'status'], capture_output=True).returncode == 0
    if not running:
        # Instance ini hanya untuk proyek dan hanya mendengarkan loopback lokal.
        flags = shlex.join(['-h', '127.0.0.1', '-p', '55432', '-k', str(socket_dir),
                            '-c', 'shared_buffers=32MB', '-c', 'max_connections=20'])
        subprocess.run([pg_binary('pg_ctl'), '-D', str(PG_DATA), '-l', str(LOCAL / 'postgres.log'),
                        '-o', flags, '-w', '-t', '20', 'start'], check=True)
    exists = subprocess.run([pg_binary('psql'), '-h', '127.0.0.1', '-p', '55432', '-d', 'postgres',
                             '-Atc', "SELECT 1 FROM pg_database WHERE datname='ihsg_ews'"],
                            capture_output=True, text=True, check=True).stdout.strip()
    if exists != '1':
        subprocess.run([pg_binary('createdb'), '-h', '127.0.0.1', '-p', '55432', 'ihsg_ews'], check=True)
    return not running


def stop_postgres():
    if (PG_DATA / 'PG_VERSION').exists():
        subprocess.run([pg_binary('pg_ctl'), '-D', str(PG_DATA), '-m', 'fast', '-w', 'stop'], check=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=9000)
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--prepare-only', action='store_true')
    parser.add_argument('--stop-db', action='store_true')
    args = parser.parse_args()
    executable = HERE / '.venv/bin/python'
    if not executable.exists():
        raise SystemExit('Jalankan python3 setup.py dahulu untuk memasang dependency proyek.')
    if Path(sys.prefix).resolve() != (HERE / '.venv').resolve():
        os.execv(str(executable), [str(executable), str(Path(__file__)), *sys.argv[1:]])
    os.chdir(HERE)
    if args.stop_db:
        stop_postgres()
        return
    if not args.prepare_only:
        with socket.socket() as probe:
            if probe.connect_ex(('127.0.0.1', args.port)) == 0:
                raise SystemExit(f'Port {args.port} sedang dipakai. Gunakan --port 9001 atau hentikan server sebelumnya.')
        if not (HERE / 'frontend/dist/index.html').exists():
            subprocess.run(['npm', 'run', 'build'], cwd=HERE / 'frontend', check=True)
        if not (HERE / 'compoundly/dist/index.html').exists():
            subprocess.run(['npm', 'run', 'build'], cwd=HERE / 'compoundly', check=True)
    owned_pg = ensure_postgres()
    try:
        if args.prepare_only:
            from backend.db import database
            from backend.service import Service
            engine, sessions = database()
            try:
                print(Service(sessions).refresh())
            finally:
                engine.dispose()
            return
        if not args.no_browser:
            def open_when_ready():
                import time
                import urllib.request
                for _ in range(60):
                    try:
                        with urllib.request.urlopen(f'http://127.0.0.1:{args.port}/api/v1/health', timeout=1):
                            webbrowser.open(f'http://127.0.0.1:{args.port}')
                            return
                    except OSError:
                        time.sleep(.5)
            threading.Thread(target=open_when_ready, daemon=True).start()
        import uvicorn
        print(f'\nEWS IHSG: http://127.0.0.1:{args.port}\nTekan Ctrl+C untuk berhenti.\n', flush=True)
        uvicorn.run('backend.app:app', host='127.0.0.1', port=args.port, log_level='info')
    finally:
        if owned_pg:
            stop_postgres()


if __name__ == '__main__':
    main()
