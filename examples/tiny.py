from copy import deepcopy
from math import sqrt

import torch
from torch import nn


class Attention(nn.Module):
    def __init__(self, width=128, heads=4):
        super().__init__()
        self.heads = heads
        self.head_width = width // heads
        self.q = nn.Linear(width, width)
        self.k = nn.Linear(width, width)
        self.v = nn.Linear(width, width)
        self.out = nn.Linear(width, width)
        self.qkv = None

    def forward(self, x):
        if self.qkv is None:
            q, k, v = self.q(x), self.k(x), self.v(x)
        else:
            q, k, v = self.qkv(x).chunk(3, dim=-1)
        b, t, _ = x.shape
        q, k, v = [value.reshape(b, t, self.heads, self.head_width).transpose(1, 2) for value in (q, k, v)]
        a = torch.softmax((q @ k.transpose(-1, -2)) / sqrt(self.head_width), dim=-1)
        return self.out((a @ v).transpose(1, 2).reshape(b, t, -1))


class Residual(nn.Module):
    def forward(self, x, branch):
        return x + branch


class TinyTransformer(nn.Module):
    def __init__(self):
        super().__init__()
        self.input_projection = nn.Linear(64, 128)
        self.attention = Attention()
        self.mlp = nn.Sequential(nn.Linear(128, 256), nn.GELU(), nn.Linear(256, 128))
        self.residual_attn = Residual()
        self.residual_mlp = Residual()
        self.output_projection = nn.Linear(128, 64)

    def forward(self, x):
        x = self.input_projection(x)
        x = self.residual_attn(x, self.attention(x))
        x = self.residual_mlp(x, self.mlp(x))
        return self.output_projection(x)


def create_example():
    torch.set_num_threads(1)
    torch.manual_seed(7)
    return TinyTransformer().eval(), torch.randn(1, 12, 64)


def pack_qkv(baseline):
    candidate = deepcopy(baseline)
    attention = candidate.attention
    width = attention.q.in_features
    # Concatenate in the same order used by Attention.forward.
    projections = (attention.q, attention.k, attention.v)
    attention.qkv = nn.Linear(width, 3 * width)
    with torch.no_grad():
        attention.qkv.weight.copy_(torch.cat([layer.weight for layer in projections], dim=0))
        attention.qkv.bias.copy_(torch.cat([layer.bias for layer in projections], dim=0))
    del attention.q, attention.k, attention.v
    return candidate.eval()


def export(model, x, path):
    torch.onnx.export(model, (x,), str(path), input_names=["hidden"], output_names=["logits"],
                      opset_version=17, do_constant_folding=True, dynamo=False)
