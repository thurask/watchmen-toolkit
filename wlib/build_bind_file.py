#!/usr/bin/env python3
"""build_bind_file.py — ENGINE-EXACT file-only bind from a skeleton ModelRes header.

TWO conventions, both engine-verified (2026-07-08):
  POSITIONS (tb): Wp(child)=Wp(par)+rot(Wq(par),p_local), Wq=qmul(Wq(par),q_local)
      with q_local AS-STORED -> matches live-dump scenegraph Wt BIT-EXACT
      (KapowMulti.DMP char49/ref65).
  PALETTE-GAUGE ROTATIONS (Rb, the skinning bind): FK with q_local CONJUGATED,
      R = R_par @ R_child.  Verified on captured female palettes (femctl
      protocol): p5 1.39deg, 527 frames <2deg (v14b: 524) -- same gauge as the
      capture-solved v14b but exact for ALL bones (v14b arms/fingers were
      approximate).  File quats store the bind conjugate -- same conjugate
      convention as the clips (--conj in bake_v4).

Output npz schema == existing binds (Rb,tb,tloc,names,par,mask), slot order taken
from a template bind (palette order is a per-skeleton empirical convention).
"""

import sys, numpy as np

import os as _os

_D = _os.path.dirname(_os.path.abspath(__file__))
if _D not in sys.path:
    sys.path.append(_D)  # append, never insert(0): flat module names must not shadow the stdlib
from parse_model_nodes import parse


def qmul(a, b):
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return np.array(
        [
            aw * bx + ax * bw + ay * bz - az * by,
            aw * by + ay * bw + az * bx - ax * bz,
            aw * bz + az * bw + ax * by - ay * bx,
            aw * bw - ax * bx - ay * by - az * bz,
        ]
    )


def qrot(q, v):
    x, y, z, w = q
    u = np.array([x, y, z])
    return v + 2 * np.cross(u, np.cross(u, v) + w * v)


def q2m(q):
    x, y, z, w = q / np.linalg.norm(q)
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ]
    )


def fk(names, pos, quat, parent):
    N = len(names)
    Wq = np.zeros((N, 4))
    Wp = np.zeros((N, 3))
    for i in range(N):
        p = parent[i]
        if p < 0:
            Wq[i] = quat[i] / np.linalg.norm(quat[i])
            Wp[i] = pos[i]
        else:
            Wq[i] = qmul(Wq[p], quat[i])
            Wq[i] /= np.linalg.norm(Wq[i])
            Wp[i] = Wp[p] + qrot(Wq[p], pos[i])
    return Wq, Wp


def fk_conj(names, pos, quat, parent):
    """palette-gauge rotation FK: conjugated locals, parent-then-child."""
    N = len(names)
    Wq = np.zeros((N, 4))
    for i in range(N):
        q = quat[i].copy()
        q[:3] *= -1
        p = parent[i]
        if p < 0:
            Wq[i] = q / np.linalg.norm(q)
        else:
            Wq[i] = qmul(Wq[p], q)
            Wq[i] /= np.linalg.norm(Wq[i])
    return Wq


def build(header_path, template_npz, out_npz):
    """template_npz=None -> engine palette order = file bone list rotated by one
    (palette[k] = bones[(k-1) % N]; verified female/gimp)."""
    mb = open(header_path, "rb").read()
    names, pos, quat, parent = parse(mb)
    pos[0] = 0
    quat[0] = np.array([0, 0, 0, 1.0])
    parent[0] = -1
    Wq, Wp = fk(names, pos, quat, parent)
    Wqr = fk_conj(names, pos, quat, parent)
    if template_npz:
        t = np.load(template_npz, allow_pickle=True)
        tn = [str(n) for n in t["names"]]
        mask = t["mask"]
    else:
        bones = names[1:]  # drop unnamed root
        tn = [bones[(k - 1) % len(bones)] for k in range(len(bones))]
        mask = np.ones(len(tn), bool)
    idx = []
    for nm in tn:
        if nm in names:
            idx.append(names.index(nm))
        else:
            raise SystemExit("template bone %r not in file skeleton %s" % (nm, sorted(names)))
    NS = len(tn)
    Rb = np.array([q2m(Wqr[i]) for i in idx])
    tloc = np.array([pos[i] for i in idx])
    par = np.full(NS, -1, int)
    for k, i in enumerate(idx):
        p = parent[i]
        while p >= 0 and names[p] not in tn:
            p = parent[p]  # skip unnamed root
        par[k] = tn.index(names[p]) if p >= 0 else -1
    # tb = FK in the PALETTE gauge: tb_k = tb_p + Rb_p @ tloc_k (engine palette
    # joints; verified == v14b tb / fixed points).  Roots at their tloc.
    tb = np.zeros((NS, 3))
    order = []
    seen = set()

    def add(k):
        if k in seen:
            return
        if par[k] >= 0:
            add(par[k])
        order.append(k)
        seen.add(k)

    for k in range(NS):
        add(k)
    for k in order:
        p = par[k]
        tb[k] = tloc[k] if p < 0 else tb[p] + Rb[p] @ tloc[k]
    np.savez(out_npz, Rb=Rb, tb=tb, tloc=tloc, names=np.array(tn), par=par, mask=mask)
    print("wrote", out_npz, NS, "slots; roots:", [tn[k] for k in range(NS) if par[k] < 0])
    return Rb, tb, tloc, par, tn


if __name__ == "__main__":
    tmpl = sys.argv[2] if sys.argv[2] != "-" else None
    build(sys.argv[1], tmpl, sys.argv[3])
