"""The pure-PyTorch spconv stand-in (workers/shims) matches dense Conv3d at the active sites.

Needs torch: it is skipped in the server venv and runs in the worker image, for example
`podman run … python -m pytest tests/test_spconv_shim.py` (plan 17.1)."""

import sys
from pathlib import Path

import pytest

torch = pytest.importorskip("torch")
F = pytest.importorskip("torch.nn.functional")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "workers" / "shims"))


@pytest.mark.parametrize("B,R,N,cin,cout,ks,dil", [(2, 16, 600, 8, 5, 3, 1), (1, 20, 900, 4, 6, 3, 2), (1, 12, 300, 3, 3, 1, 1)])
def test_submanifold_conv_matches_dense(B, R, N, cin, cout, ks, dil):
    from spconv.pytorch import SparseConvTensor, SubMConv3d

    torch.manual_seed(0)
    c = torch.unique(torch.cat([torch.randint(0, B, (N, 1)), torch.randint(0, R, (N, 3))], 1), dim=0).int()
    f = torch.randn(c.shape[0], cin)
    conv = SubMConv3d(cin, cout, ks, dilation=dil, indice_key="k")
    with torch.no_grad():
        conv.bias.normal_()
    y = conv(SparseConvTensor(f, c, [R, R, R], B)).features
    dense = SparseConvTensor(f, c, [R, R, R], B).dense()
    ref = F.conv3d(dense, conv.weight.permute(0, 4, 1, 2, 3), conv.bias, padding=dil * (ks // 2), dilation=dil)
    cl = c.long()
    assert (y - ref[cl[:, 0], :, cl[:, 1], cl[:, 2], cl[:, 3]]).abs().max().item() < 1e-4
