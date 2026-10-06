"""Point LocalTTS at temporary folders before it is imported (its settings are read once)."""

import os
import sys
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="localtts-test-"))
os.environ.update({
    "LOCALTTS_DATA": str(_TMP / "data"),
    "LOCALTTS_OUTPUTS_DIR": str(_TMP / "outputs"),
    "LOCALTTS_VOICES_DIR": str(_TMP / "voices"),
    "LOCALTTS_BREEZE_PYTHON": str(_TMP / "no-breeze" / "python"),
    "LOCALTTS_KOKORO_PYTHON": sys.executable,   # "installed"; generate() is stubbed in the tests
    "XDG_CONFIG_HOME": str(_TMP / "config"),    # no engines.json
})
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
