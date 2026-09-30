"""Tests run the fake worker (fast, placeholder boxes) against a throwaway data dir."""

import os
import tempfile

_TMP = tempfile.mkdtemp(prefix="gen3d-test-")
os.environ.update(GEN3D_FAKE_WORKER="1", GEN3D_FAKE_SAMPLES="0", GEN3D_FAKE_SPEED="200", GEN3D_DATA=_TMP,
                  GEN3D_IDLE_UNLOAD_S="600", GEN3D_BLENDER="")
