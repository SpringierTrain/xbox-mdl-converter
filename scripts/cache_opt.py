#!/usr/bin/env python3
"""
cache_opt.py - port of Valve's ComputeVertexPermutation (mstristrip.cpp).

Reorders a mesh's vertices by FIRST USE in the strip-index stream (locality),
and remaps the strip indices to match. This is the source of the PC<->Xbox VVD
vertex permutation: it is a vertex-cache optimization, not a correctness rule.

Here it is applied at the VVD-pool level for the collapsed rootLOD model:
  - build the origMeshVertID stream the GPU walks (strip index -> sg vert ->
    origMeshVertID)
  - sort the kept VVD verts [0,keep) by first appearance (unused -> front, as in
    the original where iFirstUsed = -1)
  - emit (a) VVD vertex/tangent reorder, (b) new origMeshVertID for each sg vert
The result is self-consistent and cache-optimal.
"""

def compute_permutation(num_verts, index_stream):
    """Faithful port: returns (perm, inverse) where
       perm[new] = old (new order -> original index),
       inverse[old] = new."""
    first_used = [-1]*num_verts
    for pos, idx in enumerate(index_stream):
        if first_used[idx] == -1:
            first_used[idx] = pos
    order = sorted(range(num_verts), key=lambda i: first_used[i])  # stable; -1 first
    perm = order                              # perm[new] = old
    inverse = [0]*num_verts
    for new, old in enumerate(perm):
        inverse[old] = new
    return perm, inverse

def acmr(index_stream, cache_size=16):
    """Average cache-miss ratio over triangles, FIFO cache (vertex-cache proxy)."""
    from collections import deque
    cache = deque(maxlen=cache_size); inset=set(); misses=0
    for idx in index_stream:
        if idx not in inset:
            misses += 1
            if len(cache)==cache.maxlen:
                inset.discard(cache[0])
            cache.append(idx); inset.add(idx)
    tris = max(1, len(index_stream)//3)
    return misses/tris
