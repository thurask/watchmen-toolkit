"""File-only skeleton record parser (v14-era knowledge) + node collision volumes.

Each bone record: [u32 namelen][name\0][body]; body starts [u32 f1][u32 parent]
then the mesh-binding counts, one flag byte and the node's COLLISION VOLUMES
(Node::Deserialize 0x545927, volume lists at 0x545c7f..0x545d94):

    [u32 n0] n0 x volume      -> node+0x4c, shapes for PhysX scene 0
    [u32 n1] n1 x volume      -> node+0x58, shapes for PhysX scene 1
    [u32 n2] n2 x surface     -> node+0x64, particle emission meshes: 29
                                 surfaces in 19 of the 738 distinct staged PC
                                 Part 2 models (15 of them on mesh nodes)
    surface = [u32 nT][nT x (f32x3 normal, f32 weight, i32 materialId)]
              [u32 nV][nV x f32x3][u32 nI][nI x u32]
              class MeshParticleData (element ctor 0x560601 installs vtable
              0xa3d538; reader 0x561d1c).  Consumer SurfaceSpawner 0x54fc6b ->
              0x54decc: a triangle is collected when its materialId equals the
              spawner's (materialId < 0 on the spawner: 0x54e23e), its rotated
              normal has world Y >= faceCullLimit and its centroid lies within
              `radius` in XZ; budget = trunc(particleAmount x sum of weights)
              (0x553c41; particleAmount is captioned "Particles/m2").  Data:
              the weight is the triangle's area in m^2 on 27 of the 29 Part 2
              surfaces and exactly 1.0 per triangle, whatever the area, on 2
              Part 2 and 17 Part 1 surfaces (not tied to the node name).

    volume = [u32 type][u32 base][type data][f32x3 pos][f32x4 quat xyzw]
             [u32 blobLen][blob]                     (factory 0x524b23)
      type 2 concave mesh / 4 convex mesh : [u32 mode][u32 nV][nV x f32x3]
                                            [u32 nI][nI x u32]; blob = cooked
                                            PhysX mesh ("NXS\x01CVXM" for 4)
      type 5 box     : [f32x3 full extents]            (reader 0x521396)
      type 6 sphere  : [f32 radius]                    (reader 0x521c3f)
      type 7 capsule : [f32 diameter][f32 height along local Y]  (0x52213d)

These are what earlier notes called "EmbeddedJointNode joints, types 4/5/6/7";
they are collision shapes, not joints.  `entries` (below) is the older
byte-granular scan for [pos][quat] pairs and is kept unchanged: it finds the
volume placements plus the NEXT node's rest transform at the body tail.
Engine quats = conjugate of naive xyzw convention.
"""

import struct, numpy as np

VOLUME_TYPES = {2: "concave_mesh", 4: "convex_mesh", 5: "box", 6: "sphere", 7: "capsule"}
_MAX_VOLUMES = 4096  # sanity bound on a count field, not an engine limit


def _read_bytes(path):
    """The file's bytes; the handle is closed before returning."""
    with open(path, "rb") as fh:
        return fh.read()


def parse_volume_lists(mb, p, order="<", limit=None):
    """Engine-layout read of the two volume lists + the third list, starting at
    `p` (just after the node's flag byte).  -> (lists, surfaces, end_offset).
    Raises ValueError / struct.error when the bytes are not volume lists."""
    limit = len(mb) if limit is None else limit

    def take(fmt):
        nonlocal p
        n = struct.calcsize(fmt)
        if p + n > limit:
            raise ValueError("volume record runs past the node region")
        v = struct.unpack_from(order + fmt, mb, p)
        p += n
        return v

    lists = []
    for _scene in range(2):
        (n,) = take("I")
        if n > _MAX_VOLUMES:
            raise ValueError("implausible volume count %d" % n)
        vols = []
        for _ in range(n):
            t, base = take("2I")
            v = dict(type=t, kind=VOLUME_TYPES.get(t), base=base)
            if t == 5:
                v["size"] = take("3f")  # full extents (AABB method 0x5213c7 = +-0.5*size)
            elif t == 6:
                (v["radius"],) = take("f")
            elif t == 7:
                v["diameter"], v["height"] = take("2f")  # height = total, local Y (0x522164)
            elif t in (2, 4):
                v["mode"], nv = take("2I")  # mode 1 = triangle list, else strip (0x522d17)
                if p + 12 * nv > limit:
                    raise ValueError("mesh vertices run past the node region")
                v["verts"] = np.frombuffer(mb, order + "f4", 3 * nv, p).reshape(nv, 3).copy()
                p += 12 * nv
                (ni,) = take("I")
                if p + 4 * ni > limit:
                    raise ValueError("mesh indices run past the node region")
                v["indices"] = np.frombuffer(mb, order + "u4", ni, p).copy()
                p += 4 * ni
            else:
                raise ValueError("unknown collision volume type %d" % t)  # 0x524b23 returns null
            v["pos"] = take("3f")
            v["quat"] = take("4f")
            (bl,) = take("I")
            if p + bl > limit:
                raise ValueError("volume blob runs past the node region")
            v["blob"] = bytes(mb[p : p + bl])
            p += bl
            vols.append(v)
        lists.append(vols)
    # third list (node+0x64, 0x28-byte MeshParticleData elements, reader
    # 0x561d1c): per-triangle (normal, weight, materialId) records + a mesh
    (n3,) = take("I")
    if n3 > _MAX_VOLUMES:
        raise ValueError("implausible third-list count %d" % n3)
    surfaces = []
    for _ in range(n3):
        (nt,) = take("I")
        if nt > 1 << 20:
            raise ValueError("implausible surface record count %d" % nt)
        tris = []
        for _ in range(nt):
            vx, vy, vz, w, ident = take("4fi")  # vec3 -> +0x00, f32 -> +0x10, u32 -> +0x14
            tris.append(
                dict(
                    normal=(vx, vy, vz),
                    area_weight=w,
                    material_id=ident,
                    # names used before the consumer was read (kept one release)
                    vec=(vx, vy, vz),
                    value=w,
                    id=ident,
                )
            )
        (nv,) = take("I")  # mesh sub-object 0x40b7df
        if p + 12 * nv > limit:
            raise ValueError("surface vertices run past the node region")
        verts = np.frombuffer(mb, order + "f4", 3 * nv, p).reshape(nv, 3).copy()
        p += 12 * nv
        (ni,) = take("I")
        if p + 4 * ni > limit:
            raise ValueError("surface indices run past the node region")
        indices = np.frombuffer(mb, order + "u4", ni, p).copy()
        p += 4 * ni
        s = {"class": "MeshParticleData", "tris": tris, "verts": verts, "indices": indices}
        s["weight_sum"] = float(sum(t["area_weight"] for t in tris))
        s["weight_is_area"] = _weight_is_area(tris, verts, indices)
        # the stored constant 1.0 on every triangle, whatever its area
        s["weight_is_unit"] = bool(tris) and all(t["area_weight"] == 1.0 for t in tris)
        surfaces.append(s)
    return lists, surfaces, p


def _weight_is_area(tris, verts, indices):
    """True when every triangle's weight equals its geometric area (rtol 5e-3,
    atol 1e-5: the console copies of five Part 1 models store areas 0.10-0.16 %
    off; triangle i = indices 3i..3i+2), False when one does not, None when the
    mesh does not hold one index triple per triangle record."""
    nt = len(tris)
    if nt == 0 or len(indices) != 3 * nt or (len(indices) and int(indices.max()) >= len(verts)):
        return None
    v = verts.astype(np.float64)
    i = indices.astype(np.int64).reshape(nt, 3)
    a, b, c = v[i[:, 0]], v[i[:, 1]], v[i[:, 2]]
    area = 0.5 * np.linalg.norm(np.cross(b - a, c - a), axis=1)
    w = np.array([t["area_weight"] for t in tris], dtype=np.float64)
    if not np.isfinite(w).all() or not np.isfinite(area).all():
        return False
    return bool(np.allclose(w, area, rtol=5e-3, atol=1e-5))


#: vertex formats a MeshBuffer may name (watchmen_extract.VERTEX_STRIDES has 11)
_VERTEX_FORMATS = 11


def _skip_node_meshes(mb, p, order="<", limit=None, layout="part2"):
    """Walk a node's mesh section -- the bytes between [f1][parent] and the
    volume lists (Node::Deserialize 0x545927; submesh 0x542541; MeshBuffer
    0x4336ec) -- and return (offset of the first volume list, has_mesh).

        [u32 nLod] nLod x ( [u32 nSub] nSub x submesh )
        [u32 nGroup] nGroup x ( [u32 n] n x { u8, u32, MeshBuffer } )   shadow hulls
        [u8 hasOccluder] ( MeshBuffer )
        submesh    = [str name][u32 n][n x u32 texture index][u8 +0x24][u8 inline]
                     [u32 +0x28][u8][u8] MeshBuffer [u32 blobLen][blob]
        MeshBuffer = [f32 x 6 bbox][u8][u8][u8 hasSide] ( [u8] 5 x counted array of
                     12, 2, 12, 2, 2-byte items ) [u32 x 6]
    layout "part1" (stand-alone Part 1 build, watchmen_extract.MODEL_LAYOUTS):
    the submesh has ONE u8 between [u32 +0x28] and the MeshBuffer, not two.
    Raises ValueError / struct.error when the bytes do not follow it."""
    limit = len(mb) if limit is None else min(limit, len(mb))

    def need(n):
        if n < 0 or p + n > limit:
            raise ValueError("mesh section runs past the node region")

    def u32():
        nonlocal p
        need(4)
        v = struct.unpack_from(order + "I", mb, p)[0]
        p += 4
        return v

    def flag():
        nonlocal p
        need(1)
        v = mb[p]
        p += 1
        if v > 1:
            raise ValueError("bool %d" % v)
        return v

    def skip(n):
        nonlocal p
        need(n)
        p += n

    def count(item=1):
        n = u32()
        if n * item > limit - p:
            raise ValueError("count %d" % n)
        return n

    def meshbuffer():
        skip(24 + 2)
        if flag():
            skip(1)
            for sz in (12, 2, 12, 2, 2):
                skip(count(sz) * sz)
        need(24)
        w = struct.unpack_from(order + "6I", mb, p)
        skip(24)
        if w[2] >= _VERTEX_FORMATS or w[4] % 2:
            raise ValueError("vertex format %d" % w[2])

    has_mesh = False
    for _lod in range(count(4)):
        for _sub in range(count(20)):
            has_mesh = True
            skip(count())  # name
            skip(count(4) * 4)  # texture indices
            flag()  # +0x24
            if flag():
                raise ValueError("inline mesh buffer")  # 0x433ef4: never in shipped data
            skip(4)  # +0x28
            flag()
            if layout != "part1":
                flag()
            meshbuffer()
            skip(count())  # cooked blob
    for _grp in range(count(4)):
        for _ in range(count(30)):
            has_mesh = True
            flag()
            skip(4)
            meshbuffer()
    if flag():  # node+0x30 occluder mesh (0x545bd9)
        has_mesh = True
        meshbuffer()
    return p, has_mesh


def _mesh_section_end(mb, p, order="<", limit=None):
    """_skip_node_meshes in whichever header layout the bytes follow: "part2"
    first, then "part1" (a node without submeshes reads the same in both).  With
    a `limit` the lists behind the section must tile the region as well."""
    err = None
    for layout in ("part2", "part1"):
        try:
            q, has_mesh = _skip_node_meshes(mb, p, order, limit, layout)
            if limit is not None and layout == "part2" and has_mesh:
                if parse_volume_lists(mb, q, order, limit)[2] != limit:
                    raise ValueError("lists do not tile the node region")
            return q, has_mesh
        except (ValueError, struct.error) as e:
            err = err or e
    raise err


def parse_node_tail(mb, start, end=None, order="<", meshes=False):
    """One node's bytes after its name: [f1][parent][mesh section][volume
    lists].  -> dict(f1, parent, volumes=[scene0, scene1], surfaces=[third-list
    elements], has_mesh, end), or None when the bytes do not follow the layout
    or do not tile [start, end) exactly.  end=None accepts wherever the record
    ends (last node of a file).

    meshes=False (default) is the reader as it was before 1.4.0, unchanged:
    None for a node with a non-zero submesh count, a non-zero shadow-GROUP
    count (even when every group is empty) or an occluder.  meshes=True walks
    the mesh section (_skip_node_meshes) and reads the lists behind it."""
    try:
        f1, parent = struct.unpack_from(order + "Ii", mb, start)
        if meshes:
            p, has_mesh = _mesh_section_end(mb, start + 8, order, end)
        else:
            c34 = struct.unpack_from(order + "I", mb, start + 8)[0]
            p, has_mesh = start + 12, False
            if c34 > 64:
                return None
            for _ in range(c34):
                if struct.unpack_from(order + "I", mb, p)[0]:
                    return None  # mesh node
                p += 4
            if struct.unpack_from(order + "I", mb, p)[0]:
                return None  # shadow groups
            p += 4
            if p >= len(mb) or mb[p]:
                return None  # node+0x30 occluder present (0x545bd9)
            p += 1
        lists, surfaces, p = parse_volume_lists(mb, p, order, end)
    except (struct.error, ValueError):
        return None
    if end is not None and p != end:
        return None
    return dict(f1=f1, parent=parent, volumes=lists, surfaces=surfaces, has_mesh=has_mesh, end=p)


def node_volumes(h, order=None):
    """-> [(name, [scene0 volumes, scene1 volumes] or None)] for every named
    node record, in file order (None: mesh node or bytes that do not tile)."""
    return [(r["name"], r["volumes"]) for r in parse(h, order=order)]


def is_node_record(h, lp, order="<"):
    """parse_model_nodes.parse()'s test for a TRUE node record at name offset
    `lp`: the 28 bytes before the name are [finite pos][unit quat] and the
    [f1][parent] pair fits.  (Name tables that precede the node array fail.)"""
    if lp < 28 or lp + 4 > len(h):
        return False
    p = np.frombuffer(h, dtype=order + "f4", count=3, offset=lp - 28).astype(np.float64)
    q = np.frombuffer(h, dtype=order + "f4", count=4, offset=lp - 16).astype(np.float64)
    if not np.isfinite(q).all() or abs(float((q * q).sum()) - 1.0) > 1e-3:
        return False
    if not np.isfinite(p).all() or np.abs(p).max() > 100:
        return False
    nl = struct.unpack_from(order + "I", h, lp)[0]
    return lp + 4 + nl + 8 <= len(h)


def node_records(h, order="<"):
    occ = []
    i = 0
    N = len(h)
    while i + 4 <= N:
        n = struct.unpack_from(order + "I", h, i)[0]
        if 2 <= n <= 40 and i + 4 + n <= N:
            s = h[i + 4 : i + 4 + n]
            if (
                s[-1] == 0
                and all(32 <= b < 127 for b in s[:-1])
                and s[:1].isalpha()
                and all(chr(b).isalnum() or chr(b) in " _" for b in s[:-1])
            ):
                occ.append((i, s[:-1].decode()))
                i += 4 + n
                continue
        i += 1
    return occ


def _detect_order(h):
    """'<' PC / '>' X360+PS3, same idiom as parse_model_nodes: the u32 namelen
    only parses small in the header's real byte order (2026-08-17; this module
    was LE-only, so console models yielded empty/garbage records)."""
    return "<" if len(node_records(h, "<")) >= len(node_records(h, ">")) else ">"


#: what the byte-granular transform scan of parse() met since the process started
#: (or since scan_note() last reported): probe positions whose seven floats are not
#: all finite, and the first of them (node name, header offset).
SCAN_STATS = {"headers": 0, "nonfinite_windows": 0, "first": None}


def _finite7(v):
    return all(x == x and x not in (float("inf"), float("-inf")) for x in v)


def scan_note(reset=True):
    """One line about the non-finite probe positions parse() skipped, or None when
    there were none.  They are not records: parse() tries every byte offset of a
    node's body as [pos f32 x3][quat f32 x4], so most positions read unrelated
    bytes; a window holding inf / NaN is rejected like any other non-unit window
    (the entries found are the same as before -- only numpy's RuntimeWarning is
    gone)."""
    st = SCAN_STATS
    if not st["nonfinite_windows"]:
        return None
    nm, off = st["first"]
    line = (
        "skeleton scan: %d probe positions in %d model header(s) hold non-finite floats "
        "(first: node %s, header offset %d); they are not transforms and were skipped"
        % (st["nonfinite_windows"], st["headers"], nm, off)
    )
    if reset:
        st.update(headers=0, nonfinite_windows=0, first=None)
    return line


def parse(h, maxpos=5.0, order=None):
    if order is None:
        order = _detect_order(h)
    occ = [(i, n) for i, n in node_records(h, order) if "/" not in n and n != "ModelRes"]
    recs = []
    _before = SCAN_STATS["nonfinite_windows"]
    for k, (lp, nm) in enumerate(occ):
        namelen = struct.unpack_from(order + "I", h, lp)[0]
        b0 = lp + 4 + namelen
        b1 = occ[k + 1][0] if k + 1 < len(occ) else len(h)
        body = h[b0:b1]
        par = (
            struct.unpack_from(order + "i", body, 4)[0] - 1 if len(body) >= 8 else -2
        )  # u32@4 = parent+1 (1-based, 0=root)
        # scan body for 28B [pos f32x3][quat f32x4 unit] entries, byte-granular
        ents = []
        j = 0
        while j + 28 <= len(body):
            v = struct.unpack_from(order + "7f", body, j)
            if not _finite7(v):
                # a probe position inside other data (strings, counts, mesh bytes):
                # inf / NaN cannot be a transform.  Skipped here instead of letting
                # numpy warn "invalid value encountered in matmul" on the norm.
                SCAN_STATS["nonfinite_windows"] += 1
                if SCAN_STATS["first"] is None:
                    SCAN_STATS["first"] = (nm, b0 + j)
                j += 1
                continue
            p = np.array(v[:3])
            q = np.array(v[3:])
            n2 = float(q @ q)
            if 0.98 < n2 < 1.02 and np.all(np.isfinite(p)) and np.linalg.norm(p) < maxpos:
                ents.append((j, p, q))
                j += 28
            else:
                j += 1
        # volumes: the tail ends 28 bytes before the next name (that node's own
        # transform); the last node has no successor, so only its start is fixed
        b_end = b1 - 28 if k + 1 < len(occ) else None
        tail = parse_node_tail(h, b0, b_end, order)
        full = tail or parse_node_tail(h, b0, b_end, order, meshes=True)
        recs.append(
            dict(
                name=nm,
                offset=lp,
                parent=par,
                body=body,
                entries=ents,
                # volumes: as before 1.4.0 (None where the pre-1.4.0 reader gave up)
                volumes=tail["volumes"] if tail else None,
                # particle emission surfaces of any node the engine layout tiles
                # (None: this name is not a node record or its bytes do not tile)
                surfaces=full["surfaces"] if full else None,
                has_mesh=full["has_mesh"] if full else None,
            )
        )
    if SCAN_STATS["nonfinite_windows"] != _before:
        SCAN_STATS["headers"] += 1
    return recs


if __name__ == "__main__":
    import sys

    h = _read_bytes(sys.argv[1])
    rs = parse(h)
    print(len(rs), "records")
    for r in rs[:60]:
        print(
            "%-16s par=%3d body=%4dB entries=%d"
            % (r["name"], r["parent"], len(r["body"]), len(r["entries"]))
        )


# ---------------------------------------------------------------------------
# Property records, articulated body (ragdoll) section, pivot books.
#
# One record format serves the model's articulated-body blob and the .pb pivot
# books (engine reader 0x510e5f):
#     [u32 objectId][u32 keyHash][u32 typeId][u32 nWords][nWords x 4 bytes]
# A run of records with one objectId is one object; keyHash is
# kapow_props.name_hash(property name).
RECORD_TYPES = {
    0x144B7B5D: "string",  # [u32 word count][bytes, NUL padded]
    0xFD034A24: "truth",
    0x36604FF4: "integer",
    0xBDA17DE4: "number",
    0x71D8181D: "vector",
    0xD007189C: "quaternion",  # xyzw, engine convention (conj for q v q*)
    0xEDEF427C: "biginteger",
}


#: name -> type of the properties an articulated-body blob holds, for the
#: UNTYPED records of the stand-alone Part 1 build, which do not state a type.
#: Read from the typed blobs of the same objects: each of these 86 keys carries
#: exactly this one type on all 918 models with a blob in PS3 Part 1 + PC Part 2.
_UNTYPED_SRC = {
    "string": "name",
    "truth": "actorCollisionEnabled breakable characterClothMode enableJointMotors "
    "isPressurized isSelfColliding jointProjection open recordInSavepoints runScript "
    "useAnimForCollision useGravity useMinAdhereVelocity useRealtime",
    "integer": "bendConstraintType collisionType dampingType jointType movementMotorType "
    "movementType numSolverIterations solverIterations swing1LimitType swing2LimitType "
    "twistLimitType twistMotorType xLimitType yLimitType zLimitType",
    "vector": "angularVelocity childSpacePos linearVelocity movementMotorTargetPos "
    "movementMotorTargetVelocity",
    "quaternion": "childSpaceOrient orientMotorTargetOrient",
    "number": "angularDamping bendingStiffness clothDensity collisionMapBottom "
    "collisionMapTop collisionResponseCoefficient dampingCoefficient "
    "highTwistMotionLimitDamping highTwistMotionLimitRestitution "
    "highTwistMotionLimitSpring highTwistMotionLimitValue illuminationMapBottom "
    "illuminationMapTop jointProjectionAngle jointProjectionDist linearDamping "
    "linearMotionLimitDamping linearMotionLimitRestitution linearMotionLimitSpring "
    "linearMotionLimitValue lowTwistMotionLimitDamping lowTwistMotionLimitRestitution "
    "lowTwistMotionLimitSpring lowTwistMotionLimitValue mass maxAngularVelocity "
    "maxAnimPenetration maxForceBeforeBreak maxLinearVelocity maxTorqueBeforeBreak "
    "minAdhereVelocity orientMotorPower physicsBlendFactor pressure stretchingStiffness "
    "swing1MotionLimitDamping swing1MotionLimitRestitution swing1MotionLimitSpring "
    "swing1MotionLimitValue swing2MotionLimitDamping swing2MotionLimitRestitution "
    "swing2MotionLimitSpring swing2MotionLimitValue thickness twistMotorPower "
    "twistMotorTargetSpeed xMotorPower yMotorPower zMotorPower",
}
_UNTYPED = {}
_UNTYPED_WORDS = {"truth": 1, "integer": 1, "number": 1, "vector": 3, "quaternion": 4}


def untyped_record_types():
    """{keyHash: type id} for the records of an untyped articulated-body blob."""
    if not _UNTYPED:
        try:
            import kapow_props as _kp
        except ImportError:
            import os, sys

            _d = os.path.dirname(os.path.abspath(__file__))
            if _d not in sys.path:
                sys.path.append(_d)  # append, never insert(0)
            import kapow_props as _kp
        ids = {v: k for k, v in RECORD_TYPES.items()}
        for typ, names in _UNTYPED_SRC.items():
            for nm in names.split():
                _UNTYPED[_kp.name_hash(nm)] = ids[typ]
    return _UNTYPED


def _records_typed(buf, p, end, order):
    out = []
    while p < end:
        if p + 16 > end:
            raise ValueError("truncated property record header")
        oid, key, typ, nw = struct.unpack_from(order + "4I", buf, p)
        p += 16
        if p + 4 * nw > end:
            raise ValueError("property record runs past the blob")
        out.append((oid, key, typ, bytes(buf[p : p + 4 * nw])))
        p += 4 * nw
    return out


def _records_untyped(buf, p, end, order):
    """[u32 objectId][u32 keyHash][u32 nWords][data]; the type comes from the key
    (untyped_record_types).  A key that table does not hold, or whose size does
    not fit its type, gets type id 0 -- record_value then gives its raw bytes."""
    types = untyped_record_types()
    names = {v: k for k, v in RECORD_TYPES.items()}
    out = []
    while p < end:
        if p + 12 > end:
            raise ValueError("truncated property record header")
        oid, key, nw = struct.unpack_from(order + "3I", buf, p)
        p += 12
        if p + 4 * nw > end:
            raise ValueError("property record runs past the blob")
        typ = types.get(key, 0)
        want = _UNTYPED_WORDS.get(RECORD_TYPES.get(typ))
        if want is not None and want != nw:
            typ = 0
        if typ == names["string"] and (
            nw < 1 or struct.unpack_from(order + "I", buf, p)[0] != nw - 1
        ):
            typ = 0  # a string's first word is its dword count
        out.append((oid, key, typ, bytes(buf[p : p + 4 * nw])))
        p += 4 * nw
    return out


def property_record_layout(buf, p, n_words, order="<"):
    """ "typed" / "untyped": which record layout the `n_words` dwords at `p`
    follow, or None for neither.  Typed is accepted only when every record names
    a known type (RECORD_TYPES); untyped when the records tile the blob."""
    end = p + 4 * n_words
    if n_words < 0 or end > len(buf):
        return None
    try:
        if all(r[2] in RECORD_TYPES for r in _records_typed(buf, p, end, order)):
            return "typed"
    except ValueError:
        pass
    try:
        _records_untyped(buf, p, end, order)
        return "untyped"
    except ValueError:
        return None


def read_property_records(buf, p, n_words, order="<", layout=None):
    """`n_words` dwords of property records at `p` -> [(objectId, keyHash, typeId,
    data bytes)].  Raises ValueError when a record runs past the blob.

    Both record layouts are read (property_record_layout): the typed one, and
    the untyped one of the stand-alone Part 1 build, whose type ids are filled in
    from the key (0 = type not known; the key table covers the articulated-body
    properties only).  A blob that fits neither is read typed, as before;
    layout="typed" reads typed only (the pivot-book reader)."""
    end = p + 4 * n_words
    if n_words < 0 or end > len(buf):
        raise ValueError("property blob runs past the data")
    if layout is None and property_record_layout(buf, p, n_words, order) == "untyped":
        return _records_untyped(buf, p, end, order)
    return _records_typed(buf, p, end, order)


def record_value(type_id, data, order="<"):
    """Decode one record's data by its type id (unknown types: by size)."""
    kind = RECORD_TYPES.get(type_id)
    nw = len(data) // 4
    if kind == "string":
        return data[4:].split(b"\0", 1)[0].decode("latin1")
    if kind == "truth" and nw == 1:
        return bool(struct.unpack(order + "I", data)[0])
    if kind == "integer" and nw == 1:
        return struct.unpack(order + "i", data)[0]
    if kind == "number" and nw == 1:
        return struct.unpack(order + "f", data)[0]
    if kind in ("vector", "quaternion"):
        return list(struct.unpack(order + "%df" % nw, data))
    if kind == "biginteger" and nw == 2:
        # two u32 words, LOW word first on every platform (console swaps the bytes of
        # each word, not of the eight): the Ragdoll sheet id reads 0x43b830d445af888d
        # on PC, Xbox 360 and PS3 this way (kapow_fragment reads biginteger the same)
        lo, hi = struct.unpack(order + "II", data)
        return lo | (hi << 32)
    return {"type_id": "0x%08x" % type_id, "hex": data.hex()}


def record_objects(records, names=None, order="<"):
    """Group records into objects (runs of one objectId, reader 0x510e5f) ->
    [{"id": objectId, "props": {name or "key_%08x": value}}].  `names` maps
    keyHash -> property name."""
    out = []
    cur = None
    for oid, key, typ, data in records:
        if not out or oid != cur:
            out.append({"id": oid, "props": {}})
            cur = oid
        nm = (names or {}).get(key) or "key_%08x" % key
        out[-1]["props"][nm] = record_value(typ, data, order)
    return out


def parse_articulated_body(mb, p, order="<"):
    """The model's articulated-body section at `p` (just after the node array;
    reader 0x51e1ad):
        [u32 nDw][nDw dwords property blob]
        [u32 n0][n0 x u16 node]     bodies of PhysX scene 0 ("default collision actors")
        [u32 n1][n1 x u16 node]     cloth-collision bodies, scene 1 (0x51cda2)
        [u32 nC] nC x {u16 node, u16 mesh, [u32 m] m x {u16 vertex, u32 value}}
        [u32 nJ] nJ x {i32 parent body, i32 child body}     D6 joints
    The blob holds one object per scene-0 body, cloth and joint, in that order
    (0x51a435); scene-1 bodies have none.
    -> dict(records, bodies, cloth_bodies, cloths, joints, end)."""

    def take(fmt):
        nonlocal p
        n = struct.calcsize(order + fmt)
        if p + n > len(mb):
            raise ValueError("articulated body section runs past the data")
        v = struct.unpack_from(order + fmt, mb, p)
        p += n
        return v

    (ndw,) = take("I")
    records = read_property_records(mb, p, ndw, order)
    p += 4 * ndw

    def nodes():
        (n,) = take("I")
        if n > 4096:
            raise ValueError("implausible body count %d" % n)
        return [take("H")[0] for _ in range(n)]

    bodies = nodes()
    cloth_bodies = nodes()
    cloths = []
    (nc,) = take("I")
    if nc > 4096:
        raise ValueError("implausible cloth count %d" % nc)
    for _ in range(nc):
        node, mesh = take("2H")
        (m,) = take("I")
        if m > 1 << 20:
            raise ValueError("implausible attachment count %d" % m)
        cloths.append(dict(node=node, mesh=mesh, attachments=[take("HI") for _ in range(m)]))
    (nj,) = take("I")
    if nj > 4096:
        raise ValueError("implausible joint count %d" % nj)
    joints = [take("2i") for _ in range(nj)]
    return dict(
        records=records,
        bodies=bodies,
        cloth_bodies=cloth_bodies,
        cloths=cloths,
        joints=joints,
        end=p,
    )


def parse_pivot_book(pb, names=None, order="<"):
    """.pb pivot book -> [sheet props] (name, uniqueID, friction, restitution,
    collisionMask ...).  Layout (data, 3/3 files of Part 2 PC): 12-byte header
    [u64 book id][u32 sheet count] (Book +0x20, reader 0x528326; the id
    attribute of the Book XML element, 0x528443), then per object [u32 n]["PivotSheet\\0" (n bytes)]
    [u32 nDw][property records]; a trailing "PivotBook" object closes the file."""
    if len(pb) < 12:
        raise ValueError("pivot book shorter than its header")
    count = struct.unpack_from(order + "I", pb, 8)[0]
    p = 12
    sheets = []
    while p + 4 <= len(pb):
        n = struct.unpack_from(order + "I", pb, p)[0]
        p += 4
        if n > 64 or p + n + 4 > len(pb):
            raise ValueError("bad pivot book object header")
        cls = pb[p : p + n].split(b"\0", 1)[0].decode("latin1")
        p += n
        ndw = struct.unpack_from(order + "I", pb, p)[0]
        p += 4
        # typed only: ragdoll_rig.pivot_sheets falls back to kapow_props.pivot_book
        # for the untyped books of stand-alone Part 1, which knows their types
        objs = record_objects(read_property_records(pb, p, ndw, order, "typed"), names, order)
        p += 4 * ndw
        if cls == "PivotSheet" and objs:
            sheets.append(objs[0]["props"])
    if len(sheets) != count:
        raise ValueError("pivot book lists %d sheets, %d read" % (count, len(sheets)))
    return sheets


def pivot_book_id(pb, order="<"):
    """The book id of a .pb pivot book: the u64 of its 12-byte header in the file's byte
    order (Book +0x20, reader 0x528326).  PC stores the low word first, Xbox 360 and PS3
    the high word first: one little- or big-endian u64, unlike a sheet's `uniqueID`, which
    is two words, low word first, on every platform.  default.pb: 0x0000296416269EFA;
    measured on 18 files of six sets, the same id for the same book on every set."""
    if len(pb) < 12:
        raise ValueError("pivot book shorter than its header")
    return struct.unpack_from(order + "Q", pb, 0)[0]
