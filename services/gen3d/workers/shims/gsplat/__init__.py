"""Import-only stand-in for gsplat (no ROCm build here). SAM 3D Objects imports it for Gaussian-splat
rendering, which the geometry-only path never calls; any real use raises."""
def __getattr__(name):
    def _missing(*a, **k):
        raise NotImplementedError(f"gsplat.{name} is not available on this machine (stand-in module)")
    return _missing
