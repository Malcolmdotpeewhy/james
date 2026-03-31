import subprocess
import sys
import shutil

mypy_path = shutil.which("mypy") or sys.executable + " -m mypy"
bandit_path = shutil.which("bandit") or sys.executable + " -m bandit"
print("mypy_path:", mypy_path)
print("bandit_path:", bandit_path)

res_mypy = subprocess.run([mypy_path, "--version"], capture_output=True, text=True)
print("mypy:", res_mypy.returncode, res_mypy.stdout, res_mypy.stderr)

res_bandit = subprocess.run([bandit_path, "--version"], capture_output=True, text=True)
print("bandit:", res_bandit.returncode, res_bandit.stdout, res_bandit.stderr)
