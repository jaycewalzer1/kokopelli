"""Everything the tests write goes in one folder, removed when they finish."""
import atexit
import shutil
import tempfile

tempfile.tempdir = tempfile.mkdtemp(prefix="wmloop_tests_")
atexit.register(shutil.rmtree, tempfile.tempdir, ignore_errors=True)
