"""Pasang dependency dashboard tanpa mengubah environment training."""
from pathlib import Path
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
python = HERE / '.venv/bin/python'
if not python.exists():
    training_python = HERE.parent / 'Training/.venv/bin/python'
    subprocess.run([str(training_python) if training_python.exists() else sys.executable,
                    '-m', 'venv', str(HERE / '.venv')], check=True)
requirements = HERE / 'requirements.lock.txt'
subprocess.run([str(python), '-m', 'pip', 'install', '-r', str(requirements if requirements.exists() else HERE / 'requirements.txt')], check=True)
if not shutil.which('npm'):
    raise SystemExit('Node.js/npm diperlukan untuk membangun frontend.')
subprocess.run(['npm', 'ci' if (HERE / 'frontend/package-lock.json').exists() else 'install',
                '--no-fund', '--no-audit'], cwd=HERE / 'frontend', check=True)
subprocess.run(['npm', 'run', 'build'], cwd=HERE / 'frontend', check=True)
subprocess.run(['npm', 'ci' if (HERE / 'compoundly/package-lock.json').exists() else 'install',
                '--no-fund', '--no-audit'], cwd=HERE / 'compoundly', check=True)
subprocess.run(['npm', 'run', 'build'], cwd=HERE / 'compoundly', check=True)
print('\nSelesai. Jalankan: .venv/bin/python run.py')
