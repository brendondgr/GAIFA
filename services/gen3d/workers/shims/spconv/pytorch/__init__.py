"""Pure-PyTorch subset of spconv.pytorch: SparseConvTensor and SubMConv3d (submanifold, stride 1).

Weights keep spconv 2.x's layout [out, kD, kH, kW, in] so checkpoints load unchanged. The math is
the dense Conv3d cross-correlation evaluated at the active sites only (what spconv's SubMConv3d
computes): out[p] = b + sum_k W[k] @ in[p + (k - c) * dilation], missing neighbours count as zero.
Neighbour maps are built with a sorted int64 key + searchsorted and cached per indice_key.
"""
import enum
import torch
import torch.nn as nn


class ConvAlgo(enum.Enum):
    Native = 0
    MaskImplicitGemm = 1
    MaskSplitImplicitGemm = 2


class SparseConvTensor:
    def __init__(self, features, indices, spatial_shape, batch_size, grid=None, voxel_num=None,
                 indice_dict=None, benchmark=False, **_):
        self._features = features
        self.indices = indices
        self.spatial_shape = [int(s) for s in spatial_shape]
        self.batch_size = int(batch_size)
        self.grid, self.voxel_num = grid, voxel_num
        self.indice_dict = {} if indice_dict is None else indice_dict
        self.benchmark, self.benchmark_record = benchmark, {}
        self.thrust_allocator = self._timer = self.force_algo = self.int8_scale = None

    @property
    def features(self):
        return self._features

    @features.setter
    def features(self, v):
        self._features = v

    def replace_feature(self, feats):
        new = SparseConvTensor(feats, self.indices, self.spatial_shape, self.batch_size, self.grid,
                               self.voxel_num, self.indice_dict)
        return new

    def dense(self, channels_first=True):
        f = self._features.reshape(self._features.shape[0], -1)
        D, H, W = self.spatial_shape
        out = f.new_zeros((self.batch_size, D, H, W, f.shape[1]))
        c = self.indices.long()
        out[c[:, 0], c[:, 1], c[:, 2], c[:, 3]] = f
        return out.permute(0, 4, 1, 2, 3).contiguous() if channels_first else out


def _keys(c, shape):
    D, H, W = shape
    return ((c[:, 0] * D + c[:, 1]) * H + c[:, 2]) * W + c[:, 3]


def neighbour_map(indices, spatial_shape, kernel_size, dilation):
    """[K, N] index of the input voxel at offset k from each voxel, or -1."""
    c = indices.long()
    shape = [int(s) for s in spatial_shape]
    keys = _keys(c, shape)
    sk, order = torch.sort(keys)
    kd, kh, kw = kernel_size
    offs = torch.stack(torch.meshgrid(torch.arange(kd) - kd // 2, torch.arange(kh) - kh // 2,
                                      torch.arange(kw) - kw // 2, indexing="ij"), -1).reshape(-1, 3)
    offs = (offs * torch.tensor(dilation)).to(c.device)
    lim = torch.tensor(shape, device=c.device)
    out = torch.full((offs.shape[0], c.shape[0]), -1, dtype=torch.long, device=c.device)
    for k, o in enumerate(offs):
        q = c[:, 1:] + o
        ok = ((q >= 0) & (q < lim)).all(1)
        qk = _keys(torch.cat([c[:, :1], q], 1), shape)
        pos = torch.searchsorted(sk, qk).clamp_(max=sk.numel() - 1)
        hit = ok & (sk[pos] == qk)
        out[k] = torch.where(hit, order[pos], torch.full_like(pos, -1))
    return out


class SubMConv3d(nn.Module):
    def __init__(self, in_channels, out_channels, kernel_size, stride=1, padding=0, dilation=1,
                 groups=1, bias=True, indice_key=None, algo=None, **_):
        super().__init__()
        ks = (kernel_size,) * 3 if isinstance(kernel_size, int) else tuple(kernel_size)
        self.in_channels, self.out_channels, self.kernel_size = in_channels, out_channels, ks
        self.dilation = (dilation,) * 3 if isinstance(dilation, int) else tuple(dilation)
        self.indice_key = indice_key
        self.weight = nn.Parameter(torch.empty(out_channels, *ks, in_channels))
        self.bias = nn.Parameter(torch.zeros(out_channels)) if bias else None
        nn.init.kaiming_uniform_(self.weight.view(out_channels, -1), a=5 ** 0.5)

    def forward(self, x: SparseConvTensor) -> SparseConvTensor:
        n = x.indices.shape[0]
        key = (self.indice_key, self.kernel_size, self.dilation)
        nb = x.indice_dict.get(key) if self.indice_key is not None else None
        if nb is None or nb.shape[1] != n:
            nb = neighbour_map(x.indices, x.spatial_shape, self.kernel_size, self.dilation)
            if self.indice_key is not None:
                x.indice_dict[key] = nb
        f = x.features.reshape(n, -1)
        w = self.weight.reshape(self.out_channels, -1, self.in_channels).to(f.dtype)
        out = f.new_zeros((n, self.out_channels))
        for k in range(nb.shape[0]):
            idx = nb[k]
            m = idx >= 0
            if not bool(m.any()):
                continue
            if bool(m.all()):
                out += f[idx] @ w[:, k].T
            else:
                rows = m.nonzero(as_tuple=True)[0]
                out.index_add_(0, rows, f[idx[rows]] @ w[:, k].T)
        if self.bias is not None:
            out = out + self.bias.to(out.dtype)
        return x.replace_feature(out)


class SparseConv3d(nn.Module):
    def __init__(self, *a, **kw):
        raise NotImplementedError("spconv shim: strided SparseConv3d is not implemented (SAM 3D Objects doesn't build one)")


class SparseInverseConv3d(SparseConv3d):
    pass
