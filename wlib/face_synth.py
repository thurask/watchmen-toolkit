#!/usr/bin/env python3
"""face_synth.py -- synthesized face animation from the game's static pose
library (tier-3: blink cycles + talk loops + body-clip category pairing).

The game ships FACE poses only (all clips 100% constant tracks) and blends
them procedurally at runtime (audio-driven talk, blinks).  We synthesize the
equivalent offline, using ONLY shipped poses (file-only): blink = slerp
neutral<->MouthClosed_EyesClosed (BS2 family only -- males/NTO ship no
closed-eyes pose); talk = jaw envelope between neutral and MouthTalk/Talk.

Palettes here are the (NF,3,4) face-rig palettes bake_v4 produces for pose
clips; blending is per-bone quat slerp + translation lerp.
"""

import numpy as np


def _m2q(M):
    """(N,3,3) -> (N,4) xyzw (Shepperd, minimal)."""
    N = len(M)
    q = np.empty((N, 4))
    for i in range(N):
        m = M[i]
        t = m[0, 0] + m[1, 1] + m[2, 2]
        if t > 0:
            s = np.sqrt(t + 1) * 2
            q[i] = [
                (m[2, 1] - m[1, 2]) / s,
                (m[0, 2] - m[2, 0]) / s,
                (m[1, 0] - m[0, 1]) / s,
                0.25 * s,
            ]
        else:
            a = np.argmax([m[0, 0], m[1, 1], m[2, 2]])
            b, c = (a + 1) % 3, (a + 2) % 3
            s = np.sqrt(max(1e-12, 1 + m[a, a] - m[b, b] - m[c, c])) * 2
            v = np.empty(4)
            v[a] = 0.25 * s
            v[b] = (m[b, a] + m[a, b]) / s
            v[c] = (m[a, c] + m[c, a]) / s
            v[3] = (m[c, b] - m[b, c]) / s
            q[i] = v
    return q / np.linalg.norm(q, axis=1, keepdims=True)


def _q2m(q):
    x, y, z, w = q
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ]
    )


def blend_pal(A, B, w):
    """slerp/lerp two static pose palettes (NF,3,4) -> (NF,3,4)."""
    NF = len(A)
    out = np.empty_like(A)
    qa = _m2q(A[:, :, :3])
    qb = _m2q(B[:, :, :3])
    dot = (qa * qb).sum(1)
    qb[dot < 0] *= -1
    dot = np.abs(dot)
    for k in range(NF):
        d = min(1.0, dot[k])
        th = np.arccos(d)
        if th < 1e-6:
            q = qa[k]
        else:
            q = (np.sin((1 - w) * th) * qa[k] + np.sin(w * th) * qb[k]) / np.sin(th)
        q /= np.linalg.norm(q)
        out[k, :, :3] = _q2m(q)
        out[k, :, 3] = (1 - w) * A[k, :, 3] + w * B[k, :, 3]
    return out


def blink_anim(neutral, closed, fps=15.0, dur=4.0, blink_at=3.0):
    """One blink cycle: open hold, close 0.07s, hold 0.07s, open 0.10s, loopable."""
    F = int(round(dur * fps)) + 1
    t = np.arange(F) / fps
    w = np.zeros(F)
    c0, c1, c2, c3 = blink_at, blink_at + 0.07, blink_at + 0.14, blink_at + 0.24
    w = np.where((t >= c0) & (t < c1), (t - c0) / 0.07, w)
    w = np.where((t >= c1) & (t < c2), 1.0, w)
    w = np.where((t >= c2) & (t < c3), 1 - (t - c2) / 0.10, w)
    w = np.clip(w, 0, 1)
    return np.stack([blend_pal(neutral, closed, wi) for wi in w])


def talk_anim(neutral, talk, fps=15.0, dur=4.0, seed=0):
    """Speech-like jaw loop: syllable bursts (4Hz) gated by a slower phrase
    envelope, with a seeded wobble so loops don't look metronomic."""
    rng = np.random.default_rng(seed)
    F = int(round(dur * fps)) + 1
    t = np.arange(F) / fps
    syll = 0.5 - 0.5 * np.cos(2 * np.pi * 4.0 * t + rng.uniform(0, 6.28))
    phrase = (np.sin(2 * np.pi * t / dur * 2 + rng.uniform(0, 6.28)) * 0.5 + 0.55).clip(0, 1)
    w = (syll * phrase * rng.uniform(0.85, 1.0, F)).clip(0, 1) * 0.9
    w[0] = w[-1] = 0.0  # loop-clean
    return np.stack([blend_pal(neutral, talk, wi) for wi in w])


# body-clip name -> face pose name, per family pose inventory.
# (BS2: 9 poses; EN1: 11; NTO: 4 -- only shipped names are referenced.)
def category_pose(clipname, have):
    n = clipname.lower()

    def pick(*cands):
        for c in cands:
            if c in have:
                return c
        return None

    if "dead" in n or "death" in n or "_die" in n:
        return pick("Dead1", "Dead2", "NiteOwl_MouthClosed")
    if "_dmg_" in n or "stun" in n:
        if "left" in n or "_l" in n.split("dmg")[-1][:12]:
            p = pick("DamageL")
            if p:
                return p
        if "right" in n:
            p = pick("DamageR")
            if p:
                return p
        return pick("DamageStomach", "DamageL", "NiteOwl_Biting")
    if "_att_" in n or "_wpn_" in n or "attack" in n or "counter" in n:
        return pick("Attack1", "MouthShout_EyesAnger", "NiteOwl_Biting")
    if "dance" in n or "flirt" in n or "taunt" in n:
        return pick("Provocatively", "NiteOwl_Smile")
    return None  # neutral
