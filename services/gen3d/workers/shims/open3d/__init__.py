"""Import-only stand-in for open3d (no cp313 wheel). Used by SAM 3D Objects' layout post-optimisation
(plane estimation), which the geometry-only path never calls; any real use raises."""
def __getattr__(name):
    raise AttributeError(f"open3d.{name} is not available on this machine (stand-in module)")
