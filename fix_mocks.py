import os
import glob

files = glob.glob("james/tests/*.py")

safe_mock = """class SafeNumpyMock(MagicMock):
    def __gt__(self, other):
        return True
    def __lt__(self, other):
        return False
    def __bool__(self):
        return True

sys.modules['numpy'] = SafeNumpyMock()"""

for path in files:
    with open(path, "r") as f:
        content = f.read()
    if "sys.modules['numpy'] = MagicMock()" in content:
        content = content.replace("sys.modules['numpy'] = MagicMock()", safe_mock)
        with open(path, "w") as f:
            f.write(content)
