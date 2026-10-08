# WP7 - Effects, camera, HUD and feedback (Kapow / Watchmen Part 2 PC)

Target `KapowMultiDEDRM.exe`. Evidence marks: **[R]** read from code (handler / address given),
**[D]** read from game data with the toolkit parsers (binary fragments, `.particle`, `.sequence`),
**[I]** inferred (reason given), **[N]** not established. Machine-readable tables:
`findings/wp7_tables.json` (keys named in the text). Scratch tools: `work/wp7/` (section 9).

## 0. The picture in one page

- **Everything a hit shows is data-driven and small.** A gameplay moment calls
  `EffectCtrl.command_fire_effect(effect, root, pos, orient, node, weight)`; an *effect* is an
  `EffectBase` node whose children are `EffectParticle` (a `ParticleSystemSlot` + placement),
  `EffectSound` (a `SoundDef`) and `EffectSpeak` (a speak id). There are no lights, decals, camera
  shakes or rumble inside an effect definition - those are fired by separate code paths.
- **Which effect** is chosen by `CharacterEffectDef.command_play_damage_effect` 0x6673d0 from the
  **victim's** definition (three exist: enemies, Rorschach, Nite Owl): head/body x
  uber / kill / weapon (wood, steel, sharp, taser) / fast / heavy, plus Knockdown or Stun.
- **Particles**: one native system (`kernel/assets/particles`, 104 kB). A `.particle` file is a
  `ParticleSystemAsset` + N `ParticleType`s, each with affectors, spawners, initializers; 27 module
  classes exist, 20 are used by the 89 shipped files. Particles are 128-byte records in a ring pool
  per type (`maxParticles`), simulated with explicit Euler, drawn as hardware-instanced quads with
  12 vertex / 6 pixel shader variants (alignment, bloom, occlusion box, soft particle, refraction).
- **No decals, no gameplay-driven colour grading, no FXLightning in Part 2 data.** `DecalManager`,
  `GFXDecalEffectType`, `FXLighting*`, `GfxBlender`, `GeometryEffect`, `ParticleOcclusionBox`,
  `FXParticleSysRain` have **zero** instances in the 604 non-sound fragments [D]. The cattle prod's
  electricity is a looping particle emitter on the Twilight Lady's visual; blood is particle-only
  (the ten `_uk` particle files are the localised - blood - variants).
- **Screen feedback** is: a full-screen HUD sprite (`HitOverlay.bmp`) whose opacity follows lost
  health; a point-light flash (`LightFlash` "ImpactLight", 0.3 s) at the impact; camera shake, recoil
  tilt + FOV kick, health roll; slow motion on knock-downs and kills (0.4 s real time, off in co-op);
  rumble. The level grade (`FXGfxEffectCtrl(GFXEffect)` nodes "RS GFX" / "NO GFX" in each level's
  `Art.fragment`) is static apart from user brightness/contrast/gamma/saturation and a DOF fade.
- **Camera**: per player a `CameraCtrl(Camera)` with seven camera objects (character, cinematic,
  cinematic-to-character, set-pos, combat special cuts, PvP) and three modifiers (shake, health
  roll, recoil). Finishers / counters carry their shots as `CAMERA_CUT` **animation events** (259 in
  the data) that parameterise a procedural camera (`CameraCombatSpecialCuts`): look-at bone,
  distance, height, angle, FOV, time multiplier, shake. There are no animated camera tracks for
  pairs. Cutscenes are `.sequence` files keyed on `Camera` nodes, run by `TriggerActionCamera`.
  Co-op is a vertical split screen (left / right); a combat cut temporarily takes the full screen.
- **HUD**: script classes on native `Sprite` / `TextBox`; text comes from `TextSlot` -> `TextRes`
  assets (`/Localize/*_uk*.txt`, UTF-16 key/value tables, format in 4.3); button glyphs are
  characters of the font. No enemy health bar (except `BossHUD`), no lock-on reticle.

---

## 1. Effect dispatch

### 1.1 Classes and data model [R + D]

| Class (native base) | Role | Members that matter | Instances [D] |
|---|---|---|---|
| `EffectCtrl` (Node) 0x72c262 | singleton `EffectsLib.g_eeffectctrl`; registry by `EFFECTS` id; delayed sound queue | `_eeffectslist` (index = effect id), `_esoundinstancelist`, `_iuniqueid` | 1, `GameEssentials/EffectDb.fragment` |
| `EffectBase` (Node) 0x72b770 | an effect = container; fires all children | `_ieffectid` (`EFFECTS`, -1 = none), `_echildeffectlist` | 78 named effects |
| `EffectParticle` : EffectBase 0x72d075 | one emitter | `_iplacement` (`PLACEMENT` 0 ENTITY / 1 POS_AND_ORIENT), `_eparticle` (-> `ParticleSystemSlot`), `_vlocalposition`, `_qlocalorient`, `_tlocaltransform` | 113 |
| `EffectSound` : EffectBase | one `SoundDef`, placement as above | wp6_audio.md 2.4 | 72 |
| `EffectSpeak` : EffectBase | `SpeakCtrl.add_speak_event(_ispeakid, type, character)` | | 57 |
| `CharacterEffectDef` (Node) 0x66f617 | per character family: which effect for which hit | 16 entity refs (table 1.3) + derived lists | 3 (`EnemyDamageEffectDef`, `RSH_`, `NTO_DamageEffectDef`) |
| `ParticleSystemSlot` (native) | a loaded `.particle`; creates emitters | `definition` | 39 in `ParticleDb.fragment`, + 3 `GFXParticleEffectType` |
| `EmitterNode` (native) | a placed, auto-starting emitter in a scene / on a bone | `particleSystemAsset`, `autoStart` | 500 in 102 fragments |
| `CollisionEffectCtrl` 0x6f9c74, `SoundPackageCtrl` / `SoundEffectType`, `GFXPackageCtrl` / `GFXEffectType` / `GFXParticleEffectType` / `GFXDecalEffectType` | the **effect type x surface** matrix (`COLLISION_EFFECT_TYPES`, 95 ids), one sound DB and one GFX DB | `m_ieffecttypes`, `m_eeffectsoundreference`, `m_eeffectparticlereference`, `m_eeffectdecalreference` | sound DB 96 x 2752 (wp6); **GFX DB: 55 packages, 8 entries, 3 particles, 0 decals** |
| `DynamicObjectsEffectCtrl` 0x729c20 | physics contacts of props -> sound (+ GFX matrix) | | 1 |

Struct `effectinstance` = `{eEffectList: list(entity), iEffectInstanceIdList: list(integer)}`: the
handle returned by `command_start_effect*`; each `EffectParticle` appends itself and its emitter id
so that `command_stop_effect` can call `ParticleSystemSlot.StopEmitter(id)` (0x71ce96, 0x71cc57,
0x71cfa9) [R]. Struct `soundinstance` = `{iEffectId, vPos, ePivotNode, eEffectSound, nCountDown,
iSoundId}` (delayed sounds, `EffectCtrl.StateActive` 0x715eed) [R].

Flow [R]: `EffectCtrl.command_fire_effect` 0x71c9c4 (or `_by_id` 0x71ca0c via `GetEffectById`
0x7161c3) -> `EffectBase.command_fire_effect` 0x71bfb8 -> `FireChildEffect` 0x715d73 sends
`command_fire_effect` to every child -> `EffectParticle.command_fire_effect` 0x71cdee -> `Fire`
0x7162f0:

- placement 1 `POS_AND_ORIENT`: `CreateEmitter(vPos + _vlocalposition, qOrient x _qlocalorient,
  node = null, true)`;
- placement 0 `ENTITY`: `CreateEmitter(_vlocalposition, _qlocalorient, eNode, true)` (attached);
- then `StartEmitter(id)`.

`nWeigth` is passed down but not used by `EffectParticle.Fire`. Registration: every effect with
`_ieffectid >= 0` registers in `EffectCtrl._eeffectslist` at `initialize_local` 0x71c096; effects
without id are reached only through entity references.

**Pooling and limits** [R]: `EffectCtrl` has none. The limit is in the particle system: one
`ParticleSystemSlot` owns one system instance whose `ParticleType` pools are ring buffers of
`maxParticles` shared by **all** emitters of the slot (`FUN_0055e17b`: when the ring is full the
spawn is dropped, nothing is stolen). `CreateEmitter` 0x55d059 allocates a 0x74-byte emitter record
(`FUN_0055c0c1`); the fourth argument is stored at emitter+0x14 ([I] auto-delete when finished; the
scripts never call `DeleteEmitter` for fired effects). `EffectsLib.generic_particle_systems_max_num`
/ `FireGenericParticle` 0x7167a4 is a second, pooled path with **no caller** in the 441 classes and
an enum (`GENERIC_PARTICLE_SYSTEMS`) with only `NONE` [R] - dead.

### 1.2 Who triggers effects [R]

(caller list produced with `work/wp7/who.py` over the lifted corpus, then read)

| Trigger | Code | What is fired |
|---|---|---|
| Close-combat hit (animation event `IMPACT`, id 4) | `CharacterRootLogic.SetCloseCombatDamageToTarget` 0x6ae57f -> `CharacterRoot.command_give_damage` 0x691b10 | victim def `m_echaractereffectdef.command_play_damage_effect(victim, pose, impactPos + offset, impactDir, uber, dead, weapon)`; attacker's `LightFlash.command_flash(0.3, pos)`; weapon durability; kill / knock-down camera + slow motion (3.2); `DecreaseHealth` -> player damage feedback (1.5) |
| Scripted hit inside a paired animation (event `IMPACT_EFFECTS`, id 56, 317 events) | case at 0x6aae6f | rumble by pose, `play_damage_effect` on the **partner's** def at `m_vvalue1` (local -> world), `ElectricArmor.command_electric_armor_hit`, partner `command_when_attacked`, `CharacterRoot.command_do_recoil(pose)`, partner `PlayerCtrl.command_do_damage_effect` |
| Blocked hit | `CharacterRoot.command_give_block_damage` 0x692c3f | `command_play_block_effect` (`_eblock`); Nite Owl with charged armour: effect ids by id (`ELECTRIC_ARMOR_STOP` / `FIZZLE`) |
| Attack start | `CharacterSoundDef.command_play_attack_start_pos` 0x679525 | `Attack_start_light / heavy / weapon` (speak + sound only) |
| Footsteps (events 6, 40, 76, 77) | 0x6a533a | surface from `EffectsLib.GetEffectPackageBasedOnModel` 0x71693c / `...OnTexture` 0x71d254; sound from the matrix; the "advanced effect" of a row (water) fires an `EffectBase` (`WaterWalk10CM`: `WaterWalk.particle` + sound). Table: wp6_audio.md 2.2 |
| Ragdoll / prop contacts | `CharacterVisual.ModelCollisionContactAdded` 0x69d00a, `DynamicObjectsEffectCtrl.StateActive` 0x7185e3, `command_object_collision` 0x72707d | sound matrix; GFX matrix via `command_get_particle_in_package_based_on_enum` 0x6e10c9 -> `GFXParticleEffectType.command_apply_effect` 0x75c441 (dust on TRASHCAN only [D]) |
| Animation events 29 / 30 / 31 / 60 / 69 | 0x6a62d8, 0x6a8865, 0x6a7de3, 0x6ac1bf | `command_fire_effect_by_id` (`STUN_GRENADE` 8, `ELECTRIC_ARMOR_*` 0-3, `UBER_RAGE_INITIALIZE` 12 / `ACTIVE` 13) |
| Weapons | `WeaponBase.command_take_durability_damage` 0x8b33e0, `StateDetachAtPos` 0x8b5028 | `_ebreakeffect` (`BottleBreaking`, `WoodSplinter`: sound only) |
| Gadgets / bosses | `GrapplingGun` 0x75c663.., `FlameThrower` 0x7414e7.., `ElectricArmor` 0x71e287, `UnderbossPhase1` 0x890013, `FireVolumeGeneral` 0x737257 | effects by id 4-9, 14-18 |
| Level script | `TriggerActionParticle` (34 nodes: `DO_PARTICLE_EFFECT` / `START_PARTICLE` / `STOP_PARTICLE`), `TriggerUniqueEffect`, `TriggerFireBarrelEffect`, `TriggerOscillateBox` | emitters / effects |
| Always on | `EmitterNode autoStart` in scene and character-visual fragments | fog, fire, breath, rain drips, hand motion trail, cattle-prod sparks |

Per-pose **modification before the effect**: `SetCloseCombatDamageToTarget` passes the animation's
damage pose through `ComboManipulateDamage`, `ProjectAnimationLib.DirectionManipulateDamage`,
`SizeManipulateDamagePose`, `HeightManipulateDamagePose` (lines 64-87 of the lifted handler) before
`give_damage`, so the pose that selects the effect can differ from the authored one (e.g. `_BACK`
poses when hit from behind) [R that they are called; their bodies not read].

### 1.3 The choice rule - `CharacterEffectDef.command_play_damage_effect` 0x6673d0 [R]

`initialize_local` 0x66766c builds four 2-element lists `[head, body]` (fast, heavy, uber, kill) and
`_eweaponlistlist[hitpos] = [wood, steel, sharp]` (`_esharpweapon` in both). Then:

1. pose 0 -> nothing. `hitpos` = 0 (HEAD) if `ProjectAnimationLib.IsUpperDamagePose` 0x7f077c, i.e.
   pose in {1,2,3, 7,8,9, 13,14,15, 19,20,21, 23, 25, 27}; else 1 (BODY). (20 `STUN_MIDDLE` and 21
   `STUN_UPPER_BACK` count as upper, 22 does not - as coded.)
2. `tUberDamage` (inflictor's `m_ninrageuberdamagefactor > 1`) -> uber list; else `tKill` -> kill
   list; else weapon present -> `m_ieffecttype` of the weapon (`WEAPON_EFFECT_TYPES`: 0 WOOD,
   1 STEEL, 2 SHARP, 3 TASER): **TASER first fires effect id 1 `ELECTRIC_ARMOR_DISCHARGE`
   (`LightningImpact.particle` + sound) and then uses the STEEL entry**; else pose in
   {1,2,5,6,23,24} -> fast list, any other pose -> heavy list. (3 `LIGHT_UPPER_RIGHT` and
   4 `LIGHT_MIDDLE_LEFT` therefore take the *heavy* effect - as coded.)
3. Extra: pose in {17,18,27,28} -> `_eknockdown`; pose in {19,20,21,22} -> `_estun`.

**Correction to `dominatrix_audit.md` (i1) and wp6_audio.md 2.4:** "a sharp weapon also fires its own
effect" is wrong. Type 2 SHARP simply selects `_esharpweapon` from the weapon list; the extra effect
belongs to type **3 TASER** and is effect id 1.

The weapon passed is the inflictor's `m_eweapon`, none when `tIgnoreWeapon`, and
`ProjectLib.g_efaketwilightladyweapon` when the inflictor's character type is 0x23 (Twilight Lady;
set in `CharacterRoot.command_set_weapon` 0x694378 from her `m_emodelcollbash1h` collection) [R]. The
node of that fake weapon was not located in the staged fragments; that it carries effect type 3 is
[I] from the TASER branch.

### 1.4 The complete Dominatrix table [D + R]

Effects (`EffectDb.fragment`, particles resolved through `ParticleDb.fragment`; sounds / speak ids as
in wp6_audio.md 2.4). All particle children use placement 1 (world position = impact position +
`CalcImpactOffset`, orientation = Y axis along the impact direction).

| Effect | Particles (`/Art/Effects/CombatEffects/...`) | Speak |
|---|---|---|
| `EN_dam_body_light` | `ParticleSystems/BluntImpactBody_Medium` | 30 |
| `EN_dam_body_heavy`, `Block`, `Stun` | `BluntImpactBody_Medium`, `StunShock` | 27 (`Stun`: none) |
| `EN_dam_body_uber` (effect id 11) | `StunFlash`, `BluntImpactBody_Medium`, `UberEffect` | 27 |
| `EN_dam_body_weapon_wood` / `_steel` | `ImpactBigBody_uk` | 27 |
| `EN_dam_body_kill` | `SharpImpactBody_Heavy_uk`, `StunFlash`, `StunShock` | 27 |
| `EN_dam_head_light` | `BluntImpactHead_Light_uk`, `BluntImpactBody_Light` | 29 |
| `EN_dam_head_heavy` | `BluntImpactHead_Medium_uk`, `BluntImpactBody_Light`, `StunShock` | 26 |
| `EN_dam_head_uber` (id 10) | `BluntImpactHead_Heavy_uk`, `StunFlash`, `BluntImpactBody_Light`, `UberEffect` | 26 |
| `EN_dam_head_weapon_wood` / `_steel` | `BluntImpactHead_Heavy_uk`, `BluntImpactBody_Light` | 26 |
| `EN_dam_head_kill` | `BluntImpactHead_Heavy_uk`, `StunFlash`, `StunShock`, `BluntImpactBody_Light` | 26 |
| `EN_dam_weapon_sharp` | `SharpImpactBody_Heavy_uk` | 26 |
| `Knockdown` | `StunFlash` | 31 |

**Hits on a Dominatrix** (victim def `EnemyDamageEffectDef`, referenced by `Dominatrices.fragment`
`m_echaractereffectdef`; the same def serves every enemy type):

| Damage pose | unarmed | wood | steel | sharp | attacker in uber rage | killing hit |
|---|---|---|---|---|---|---|
| 1, 2, 23 | head_light | head_weapon_wood | head_weapon_steel | weapon_sharp | head_uber | head_kill |
| 3, 7, 8, 9, 13, 14, 15, 25 | head_heavy | " | " | " | " | " |
| 5, 6, 24 | body_light | body_weapon_wood | body_weapon_steel | weapon_sharp | body_uber | body_kill |
| 4, 10, 11, 12, 16, 26 | body_heavy | " | " | " | " | " |
| 17, 18, 28 | body_heavy + Knockdown | body row + Knockdown | | | | |
| 27 | head_heavy + Knockdown | head row + Knockdown | | | | |
| 19, 20, 21 | head_heavy + Stun | head row + Stun | | | | |
| 22 | body_heavy + Stun | body row + Stun | | | | |

**Hits by her** (victim def `RSH_DamageEffectDef` or `NTO_DamageEffectDef`). Her weapons [D
`WeaponDB.fragment` folder `DominitrixWeapons_1H`]: `PoliceBaton.model` effect type **1 STEEL**,
`Paddle.model` type **0 WOOD**; unarmed attacks pass no weapon. Her attack states and authored poses
(`wp7_tables.json` `dominatrix.attack_states.Enemy04`): `1H_light_A` 3, `_B` 1, `_C` 6, `_D` 2,
`1H_Heavy_A` 7, `_B` 9, area 9, knock-down / super 14, sidekick 11; unarmed light 1-6, heavy 7-12.

| Victim | pose group | unarmed | paddle (wood) | baton (steel) |
|---|---|---|---|---|
| Rorschach | head (1,2,23 fast; 3,7-9,13-15,25 heavy) | `RSHdam_head_light` (HeadLight_uk + BodyLight) / `RSH_dam_head_heavy` (+ StunShock) | `RSH_dam_head_weapon_wood` (BluntImpactHead_Heavy_uk + BodyLight) | `RSH_dam_head_weapon_steel` (same particles, other sound) |
| | body | `RSH_dam_body_light` / `_heavy` (BodyMedium [+ StunShock]) | **`RSH_dam_head_weapon_wood`** - the def's `_ebodyweaponwood` points at the *head* effect (data slip) | `RSH_dam_body_weapon_steel` (BodyMedium) |
| Nite Owl | head | `NTO_dam_head_light` / `_heavy` | `NTO_dam_head_weapon_wood` | `NTO_dam_head_weapon_steel` |
| | body | `NTO_dam_body_light` / `_heavy` | `NTO_dam_body_weapon_wood` | `NTO_dam_body_weapon_steel` |
| either | + pose 17,18,27,28 / 19-22 | `RSH_Knockdown` (sound, speak 31) / `RSH_Stun` (StunShock); `NTO_` same | | |

Full per-pose rows with particle, sound and speak lists: `wp7_tables.json`
`dominatrix.damage_effect_by_pose`. Also fired on every hit she lands that damages a **player**:
section 1.5; on every hit a player lands on her: recoil, light flash, possibly slow motion (3.2).

### 1.5 Player-side feedback of being hit [R]

`CharacterRoot.DecreaseHealth` 0x695632 (send at 0x6961d7, missed by the lifter): when the victim
survives, has a `PlayerCtrl`, damage > 0 and the hit has a damage pose, it sends
`PlayerCtrl.command_do_damage_effect` 0x7f4531 (the other sender is the `IMPACT_EFFECTS` case):

1. `PlayerHUD.command_damage(health)` 0x7f9791: `DamageSprite` opacity = `_nminopacity +
   (1 - health) x (_nmaxopacity - _nminopacity)` = 0.5 .. 1.0 [D]; `StateActive` 0x801778 then lowers
   it by `lerp(_nmindecreate, _nmaxdecrease, health)` per second. Texture `/Art/UI/Textures/HitOverlay.bmp`.
2. `VibrationMotorCtrl.command_damage_received` 0x8ab701: power = 0.3 + 0.7 x (1 - health) for
   0.23 s [D values].
3. `CameraCtrl.command_start_damage_modifiers` 0x636059: sinus shake 0.25 s, amplitude 0.02 rad per
   axis x random direction, time factor 40; `CameraModifierHealthEffect.command_apply_smack(health)`.

---

## 2. Particle system

### 2.1 The `.particle` file as the engine reads it [R]

Loader: `ParticleSystemAsset::vfunc_24` 0x55d3ed (binary; `vfunc_21` 0x55d4c9 falls back to an XML
form with `<version>` 1 / 2 through `FUN_0055bdff`, printing "Particle asset '%s' is an old format").
Generic object reader `FUN_00511f96` (into an existing object) / `FUN_00511eb5` (create by class name),
record application `FUN_00510e5f`.

```
file   = object(ParticleSystemAsset)
         u32 nTypes
         nTypes x { object(ParticleType)
                    u32 nAffectors     ; nAffectors x object      -> type+0x60  (0x55b49f)
                    u32 nSpawners      ; nSpawners  x object      -> type+0x48  (0x55b4f9)
                    u32 nInitializers  ; nInit      x object      -> type+0x54  (0x55b4d7) }
object = [u32 len][ClassName\0][u32 payloadDwords][payloadDwords x 4 bytes of records]
record = [u32 id][u32 keyHash][u32 typeHash][u32 k][k dwords]
```

- A record is applied only when the class has a property with that hash **and** the stored type
  hash equals the property's type (`FUN_004ee10d`, then `Entity set property` 0x510737); unknown or
  mismatching records are skipped. The first dword of a record is not interpreted.
- The save order (`vfunc_23` 0x558a29) and the XML element names ("Spawner", "Initializer",
  "Affector", `vfunc_22` 0x558b39) confirm which list is which.

**Toolkit vs engine** (`tk160/wlib/kapow_props.py`, FORMATS_MISC.md):

| Toolkit says | Engine | Consequence |
|---|---|---|
| `[0-4 stray u32s]` before a block (`pre`) | the list counts `nTypes`, `nAffectors`, `nSpawners`, `nInitializers` | the tree structure (which module belongs to which type, and its role) is in these counts; the flat block list loses it when a count is 0 or a list is empty |
| `schemaCount` | payload length in dwords | the parser can jump instead of walking with the "same owner id" heuristic |
| `ownerId` anchors a block | ignored by the loader | - |
| key names from the hash dictionary: `Texture`, `Duration`, `Position`, `Speed`, `Force`, `Ambient`, `Factor` | registered names are `texture`, `duration`, `position`, `speed`, `force`, `ambient`, `factor` (hash is case-blind) | cosmetic |
| unresolved `329262a2`, `72aab21a`, `72aab29a`, `2282b20a`, `f20aa272` | `life` (VarianceInitializer), `numX`, `numY` (UVArrayInitializer / UVArrayAffector), `damp` (DampeningAffector), `open` (Node) - hashes reproduced | add to `prop_hash_dict.pkl` |
| value `enum`-less integers | dropdown items are in the registration strings (below) | emit names |

All 89 files parse to the last byte with the existing parser (0 warnings) [D]; the proposal is a
structural reader, not a repair.

### 2.2 Properties (registration strings; units from the UI text) [R]

`ParticleSystemAsset::RegisterMembers` 0x55da60: `duration` (s, 0-50; an emitter stops when its
time exceeds it unless looping, `FUN_0055b104`), `loop`, `enableUpdateEvents` (+0xa1),
`enableDieEvents` (+0xa2), `enableSpawnEvents` (+0xa3), `alwaysUpdate` (+0xa4: simulate even when
culled), `evolveFramesOnStart` (0-100 pre-simulated frames of 0.033 s, `FUN_0055d180`),
`cullingRadius`, `cullingDistance` (+0xac / +0xb0, m), `renderInstanced`, `numVariations` (1-20),
`particleTypes`.

`ParticleType::RegisterMembers` 0x55c1d2 (offsets from the accessors / ctor `FUN_0055b2bb`):

| Property | Type / items | Meaning |
|---|---|---|
| `simulationMode` +0x6c | 0 World space, 1 Local space, 2 Local Instanced | world: spawn position is interpolated along the emitter's motion within the frame (`FUN_005563a3`); local: particles live in emitter space |
| `maxParticles` +0xe0 | 0-10000 (default 50) | ring pool size per type |
| `particleSpeed` +0x80 | m/s | initial speed along `localOrientation` x Z |
| `particleLife` +0x84 | s | |
| `particleSize` +0x78 | m | initial size x = y |
| `blendMode` | Normal 0, Additive 1, Subtract 2, Multiply 3, Custom 4 | |
| `srcBlend` +0x114 / `dstBlend` +0x118 | zero 1, one 2, srcColor 3, invSrcColor 4, srcAlpha 5, invSrcAlpha 6, dstAlpha 7, invDestAlpha 8, dstColor 9, invDstColor 10, srcAlphaSat 11 (D3DBLEND values) | category "Soft Alpha"; used with Custom |
| `blendOp` +0x11c | add 1, subtract 2, revSubtract 3, max 4, min 5 | |
| `particleDepth` | m | soft-particle fade depth (`SOFTPARTICLES` variant reads the depth texture) [I from name + shader constants `$DepthAndNearClip`] |
| `texture` / `model` | `.bmp` / `.model` | |
| `renderStyle` +0xe8 | Billboard 0, Model 1, Refraction 2 | |
| `alignment` +0x70 | None 0, Camera 1, Velocity 2, Camera (Stretch last) 3, Camera (Stretch first) 4 | selects the vertex-shader variant |
| `stretchFactor` | 0-1 | `$stretchFactor` |
| `startTime`, `endTime` +0xc0 / +0xc4 | fraction of the emitter duration | spawners run only inside the window (`FUN_0055a722`) |
| `localPosition` +0x90, `localOrientation` +0xa0, `particleOrientation` +0x120 | | emitter-local offset / direction; initial particle angles |
| `immortalParticles` +0xec | | alternative integrator `FUN_00555456` (no life countdown) |
| `localMode` | deprecated ("use simulationMode") | |
| `uScale`, `vScale` | | |
| `alphaFalloffEnabled`, `alphaFalloffStart` +0x108, `alphaFalloffEnd` +0x10c | m | distance fade (`$falloff`) |
| `useOcclusion` +0x12c, `occlusionAttenuationLow/High`, `occlusionId` +0x138 | | darkening inside a `ParticleOcclusionBox` with the same id (`OCCLUSION` variants) |

Modules (30 registrations incl. the two assets; full list with UI strings in `wp7_tables.json`
`particle.classes`; update bodies named where read):

| Kind | Class | Properties | Behaviour |
|---|---|---|---|
| spawner | `RegularSpawner` | `particlesPerSec` | [R name] |
| | `IrregularSpawner` 0x55b804 | `particlesPerSec`, `variance` | next spawn after `1 / (rate + (2r-1) x variance)` s [R] |
| | `BurstSpawner` 0x554342 | `min/maxBurstAmount`, `min/maxBurstInterval` (s) | [R] |
| | `EmitterTrailSpawner` 0x549059 | `stretchAdjust` | one particle per call, centred half-way back along the emitter's displacement, size y = max(size, stretchAdjust x displacement x 0.5): **the motion-trail primitive** [R] |
| | `EventSpawner` | `eventChannel` (COLLISION 4, DIE 5, CUSTOM_1 9, CUSTOM_2 10), `particleTypeNr`, `min/maxBurstAmount`, `inheritedVelocity` | spawns another type on particle events |
| | `SurfaceSpawner` 0x553d4d / 0x553bae | `particleAmount` (particles/m2), `radius`, `speed`, `lifeVariance`, `faceCullLimit` (-1..1), `spawnOnCharacters`, `spawnOnGeometry`, `materialId` | see 2.4 |
| | `TerrainSurfaceSpawner`, `ProximityNoise(Spawner)` | amount, radius, `spawnDistance`, `fadeDistance`, `particleDensity`, `followCamera`, ... | not used in Part 2; Part 1: `TerrainSurfaceSpawner` 1 file (`rain_terrainsplash`), `EventGeneratorAffector` 2 (`lightning_02`, `BloodSplatter_Ground_01`); `ProximityNoise`, `PlaneCollisionAffector`, `TerrainCollisionAffector` in no file |
| initializer | `VarianceInitializer` 0x54964e (6.4 kB) | `position`, `orientation`, `rotation` (vectors), `sizeVariance`, `alpha`, `life`, `speed` ("Speed Variance (pct)"), `spread` ("Spread (degrees)"), `useLocalOrientation` | random start state; body not read |
| | `ColorRangeInitializer` 0x548454 | `colorSequence` ("start color") | random point of the gradient -> particle rgb [R] |
| | `UVArrayInitializer` 0x5559ce | `numX`, `numY` | random cell of an atlas [R] |
| | `PositionInitializer` | - | no properties; not used |
| affector | `LinearForceAffector` 0x555b81 | `force` (m/s2) | `v += dt x force` [R] |
| | `DampeningAffector` 0x555c4c | `damp` (1/s) | `v -= damp x dt x v` [R] |
| | `GrowthAffector` 0x55f332 | `growth` (m/s) | `size.xy += growth x dt` [R] |
| | `RotateAffector` 0x555ab0 | `rotationx/y/z` (deg/s) | angles += [R] |
| | `SizeSequenceAffector` 0x55f3fe | `sizeOverTime` (gradient), `factor` | `size = factor x curve(t)` [R] |
| | `OpacitySequenceAffector` 0x5552d3 | `colorSequence` ("Opacity over time") | alpha = curve(t) [R] |
| | `ColorSequenceAffector` 0x5483a7 | `colorSequence` ("Color over time") | rgb = gradient(t), alpha kept [R] |
| | `IlluminationAffector` 0x55f491 | `ambient` ("Receive ambient"), `selfIllumination` (gradient), `bloomFactor`, `bloomSequence` | writes illumination rgb (+0x60) and a packed bloom colour (+0x78) [R dispatch, bodies skimmed] |
| | `TraceAffector` 0x55f375 | `stretchRatio` | `size.y += ratio x speed x dt` [R] |
| | `UVArrayAffector` 0x560b32 | `frameRate`, `numX`, `numY`, `animationMode` (Forward 0, reverse 1), `randomize` | flip-book |
| | `GeometryCollisionAffector` 0x54bfab (4.2 kB) | `radius`, `elasticity`, `friction`, `collisionMask` (`COLLISION_TYPES` flags), `alignToCollisionNormal`, `safetyRadius`, `dieOnImpact` | world collision; body not read |
| | `PlaneCollisionAffector`, `TerrainCollisionAffector` | `radius`, `elasticity`, `nodeRef` | not used in Part 2; Part 1: `TerrainSurfaceSpawner` 1 file (`rain_terrainsplash`), `EventGeneratorAffector` 2 (`lightning_02`, `BloodSplatter_Ground_01`); `ProximityNoise`, `PlaneCollisionAffector`, `TerrainCollisionAffector` in no file |
| | `EventGeneratorAffector` | `eventChannel` (CUSTOM_1/2), `interval`, `startTime`, `endTime` | not used in Part 2; Part 1: `TerrainSurfaceSpawner` 1 file (`rain_terrainsplash`), `EventGeneratorAffector` 2 (`lightning_02`, `BloodSplatter_Ground_01`); `ProximityNoise`, `PlaneCollisionAffector`, `TerrainCollisionAffector` in no file |

Gradient strings are `t,r,g,b,a|...` with t in 0..1 over the particle's life, t = 1 - timeLeft / life
(every sequence affector computes it that way) [R].

Corpus [D, all 89 files]: 208 types; classes used: VarianceInitializer 206, OpacitySequence 202,
BurstSpawner 114, LinearForce 89, Illumination 88, SizeSequence 85, RegularSpawner 81,
UVArrayInitializer 70, Growth 63, Dampening 53, ColorRange 51, ColorSequence 36, IrregularSpawner 11,
GeometryCollision 9, EventSpawner 5, Rotate 2, EmitterTrailSpawner 1, UVArrayAffector 1.
`renderStyle`: 192 billboard, 16 refraction, **0 model**. `alignment`: Camera 152, None 35, stretch
first 18, velocity 2, stretch last 1. `simulationMode`: world 150, local 58. Blend: normal 121,
additive 87; custom factors on 9.

### 2.3 Simulation [R]

- Particle record: 128 bytes; pool = `{ptr, ?, alive bytes, capacity, ..., head +0x44, tail +0x48}`.

  | Offset | Field |
  |---|---|
  | +0x00 | position xyz(w) |
  | +0x10 | velocity |
  | +0x20 / +0x30 | orientation angles / angular rate |
  | +0x40 / +0x44 | time left / life (s) |
  | +0x48 | fade factor (1.0) |
  | +0x50..+0x5c | colour rgb, alpha |
  | +0x60 | illumination rgb |
  | +0x70 / +0x74 | size x / y |
  | +0x78 / +0x7c | packed bloom colour / uv cell |

- Per frame (`ParticleExecuteThreadContainer` job -> `FUN_008bd6e4` -> `FUN_0055b16f(dt)`):
  emitter clocks (`FUN_0055b104`: stop at `duration` unless looping); per type `FUN_0055a722`:
  for each active emitter inside the type's `startTime..endTime` window run the spawners
  (`FUN_00559287`; a spawner asks `vfunc_19` how many, allocates, `FUN_005560c1` default state,
  initializers `FUN_00559211`, spawn event if enabled); then `FUN_0055a643` over the live range:
  integrate (`FUN_0055a503`: `pos += dt x vel`, `angles += dt x rate`, `timeLeft -= dt`, <= 0 ->
  dead, die event 5 if enabled), then every affector's `vfunc_15(dt)`, then update events (7).
- Events (`PARTICLESYSTEMEVENT`: EMITTERCREATED 0 .. PARTICLECOLLIDE 4, PARTICLEDIE 5,
  PARTICLESPAWN 6, PARTICLEUPDATE 7, EMITTERRESET 8) reach scripts as
  `ParticleSystemEvent(integer,integer,integer,vector)`; only `EventSpawner` consumes them in
  Part 2 (5 uses).
- Culling / LOD (`ParticleSystemSlot::vfunc_17` 0x5586e3): unless `alwaysUpdate`, a system is
  simulated only when for some active camera the distance is below `cullingDistance` and the sphere
  of `cullingRadius` is in the frustum. There are no particle LOD levels; `numVariations`
  pre-builds N variants of the system (`SetNumVariations` 0x55d6b2; use not read).

### 2.4 Emitter surfaces in model node records [R]

The third list of a model node tail ("surface", FORMATS_MISC.md: `[nT x (f32x3, f32, i32)][nV x
f32x3][nI x u32]`) is consumed by `SurfaceSpawner`: `Node::Deserialize` 0x545927 keeps 0x28-byte
surface objects at node+0x64; the spawner queries up to 100 nodes inside `radius`
(`FUN_0055224e`, asynchronous), then per model node (`FUN_0054fc6b`) or per character bone
(`FUN_0054fba7`, bone -> node index bone+0x98, bone matrix) walks the triangles
(`FUN_0054decc` / `FUN_0054e23e`): a triangle is used when its material id (the i32) equals the
spawner's `materialId` (or always when that is negative) and its world normal's Y is at least
`faceCullLimit`; the per-triangle float is the area weight for "Particles/m2" [I for the float;
filter read]. So the record is an **emission mesh for rain splashes / drips on models and
characters**. No Part 2 `.particle` uses `SurfaceSpawner` [D], so the single surface in the PC
corpus is unused content.

### 2.5 Rendering [R + shader archive]

- Collection: `ParticleUpdateJobContainer` -> `FUN_00476a4b` packs each live particle whose
  alpha x fade >= 0.01 into a 56-byte instance record: position, angles, packed colour
  (`colour x clamp(ambient + illumination)` when the type is lit), uv cell, size xy, bloom,
  velocity. Quads are hardware-instanced (`FUN_0055f0d5` builds the 4-vertex / 6-index unit quad).
- Sorting: per system, not per particle: 24-byte entries ordered by a priority integer, then by
  distance descending (`FUN_0056189f` / compare `FUN_0056881d`).
- `REParticles` ctor 0x58d1fe builds: `ParticleVS` x {none, `ALIGN_VELOCITY`, `ALIGN_RESTRAINCAM`,
  `ALIGN_RESTRAINVELOCITY`} x {`OCCLUSION`} x {`BLOOM`}; `ParticlePS` x {none, `OCCLUSION`} plus
  `SOFTPARTICLES`[+`OCCLUSION`] and `BLOOM`[+`OCCLUSION`]; `ParticleRefractionPS` (normal map
  distorting `$backgroundMap`); `MainVS[TANGENTSPACE]` for model particles. Mapping of the five
  `alignment` values to the four VS variants is [I] (0/1 -> default with `$camOrient`, 2 ->
  VELOCITY, 3/4 -> the two RESTRAIN variants).
- Passes (wp1_renderer.md): `Particles` (pass 17, soft particles read depth), `Bloom Particles`
  (pass 6), `RefractiveParticles` after the scene copy (pass 19), `Reflection - Particles`.
- Trails / meshes: there is no ribbon primitive. Trails are stretched billboards
  (`EmitterTrailSpawner`, `TraceAffector`, alignment 3/4). Mesh particles exist in code, unused in
  data.

### 2.6 Blood, decals, weapon trails, electricity, lens flares

- **Blood** [D]: only particles. The ten `*_uk.particle` files (`ImpactBigBody/BigHead/SmallHead/
  StunHead`, `BluntImpactHead_*`, `SharpImpactBody_*`) are per-language assets (NAZ "localized"
  entries); [I] the `_uk` suffix is the language variant that allows a censored set for other
  territories - only `_uk` is in the PC archive.
- **Decals** [R + D]: native `DecalManager` (properties `texture`, `bufferSize` 1-100,
  `perFrameFillSize`; messages `SetDecal(vector,vector,number,entity)` and the 7-argument form) and
  script `GFXDecalEffectType` (`m_ndecalscale`; `CheckDecalValidity` 0x75af1f does line checks at
  the corners before `SetDecalEx`) exist, but **no fragment instantiates either**. All "decals" in
  the levels are ordinary meshes. Nothing projects onto characters. How `DecalManager` builds its
  geometry (0x4c4a8c, 3 kB) was not read.
- **Weapon / fist trails** [D + R]: `RorschachCharVisual.fragment` and `NiteOwnCharVisual.fragment`
  hold `BoneAttacher "AttackEffectAttacher"` (bone 11) -> `EmitterNode` with
  `/Art/Effects/MotionTrails/Rorschach_Hands.particle` (looping, `autoStart`, `EmitterTrailSpawner`
  stretchAdjust 1, alignment 4, life 0.4 s, size 0.05 m, texture `MotionTrail02.bmp`).
  `CharacterVisual.command_activate_model` 0x69e354 stores the attacher in `m_eeffectattacher`; no
  script toggles it, so the trail is always emitted and only visible when the hand moves fast [I].
  Enemy visuals (`En4CharVisual`, the Dominatrix) have no emitters: **her baton has no trail**.
  `WeaponBase._eglowingmodel` + `art/Effects/Highlights/*.sequence` (keys on `TextureSheet`
  `bloompower` 0 -> 2 -> 0 and `selfilluminance` 0 -> 0.5 -> 0 over 1 s) are the pick-up highlight of
  dropped weapons, not a trail [D]. `EffectsLib.SpriteLine` 0x71d694 stretches a sprite between two
  points; its callers are `ElectricArmor.UpdateElectricSprites`, `GrapplingGun` (rope) and
  `SpriteStrecher` - not weapons [R].
- **Electricity** [D + R]: cattle prod = `EmitterNode` `/Art/Effects/Electricity/TWL_Weapon01.particle`
  (`autoStart`) in `Bs2CharVisual.fragment`; its hit = TASER branch (1.3). Nite Owl's armour =
  nine `ElectrifyArmor_*.particle` emitters on body bones + `LightningImpact.particle` + sprites
  stretched to targets (`ElectricArmor` 0x730af0). `FXLighting` (0x749101: storm lightning - random
  pitch / yaw in a sky slice, pulse list, per pulse a billboard `FXLightningShowSprite`, a light, a
  sound, `FXLightningLightUpSky`, and `FXLightningBlendToGFX` which blends the grade) is sky
  lightning, generates **no geometry**, and has no instance in Part 2.
- **Lens flares** [R props + D]: native `LensFlare` (texture, blendMode Normal / Additive, opacity,
  offset -1..1 along the flare axis, colour, size 10-1500 px, `fadeCameraAngle1/2`,
  `fadeCamBlindDiming`, `fadeFlareAngle`, `inverseFlareAngle`, `maxDistance`,
  `distanceSizeScaleFactor`) under a `LensFlareManager` (sizeReduction, fadeDistance,
  numberOfFadeInFrames, emitterSize, lineCheckLength, occlusionSize, opacityModifier; occlusion by
  line checks). 840 `LensFlare` nodes in 59 fragments, authored as prefab fragments in
  `art/Effects/LensFlare/`. Drawn in pass 19 (0x56dc9e). Update code (lensflare.cpp 7.7 kB) not read.

### 2.7 Screen-space effects driven by gameplay

| Effect | Mechanism | Evidence |
|---|---|---|
| Hit flash | `LightFlash(Light)` "ImpactLight" on the two player visuals: `command_flash(0.3 s, impact pos)` moves the light, brightness = initial x t/T (2.82 -> 0, range 0.7 m, colour 0.86, 0.86, 1.0); sent to the **attacker's** `m_elightflash` at the end of `SetCloseCombatDamageToTarget` | [R] 0x7756fc, 0x7702ef, 0x6ae57f; [D] |
| Damage vignette | HUD sprite, 1.5 | [R + D] |
| Low-health look | camera roll, 3.3; heart-beat loops below 50 % / 25 % (`PlayerHUD.HandleSounds` 0x7f0310, not in co-op) | [R + D] |
| Slow motion | `WorldLib.SetTimeMultiplier` 0x8a9d27 -> `MasterSceneCtrl.command_set_time_multiplier` and physics rate `const / multiplier`; **ignored in co-op** unless the value is 1. Sources: knock-down poses by a player (13-18, 27, 28), kills with heavy / knock-down / stun poses by a player, both for 0.4 s real time (`CharacterRoot.StateActive` restore); `CAMERA_CUT.nTimeMultiplier`; `TriggerActionGeneral` | [R]; value of `CharacterRoot._nslomotimemultiplier` [N] (never assigned in script, not present in the staged fragments) |
| Slow-motion desaturation, hit-flash grade | **do not exist**: the only caller of `EffectsLib.OverrideGfxSettings` 0x71d1c5 -> `FXGfxEffectCtrl.command_override` is `FXLightningBlendToGFX` (no instance) | [R + D] |
| Rage mode look | `art/Effects/RageMode/RageMaterialPulse.sequence`: `falloffpower` 1 -> 0.25 -> 1 over 1 s on seven Rorschach `TextureSheet`s (rim falloff pulse), referenced from each level's root fragment; effects `UBER_RAGE_INITIALIZE` (12: `StunGrenade.particle`, sound, speak 38) and `UBER_RAGE_ACTIVE` (13, empty) at event `STARTING_UBER_RAGE`; `EN_dam_*_uber` on hits; HUD bar pulse | [D]; who starts the sequence [N] |
| Block flash | event `DO_BLOCK_FLASH` (84): `SetTextureSheetData` on Nite Owl (`MATERIAL_SHEETS` *_ELECTRIC) | events.md; not re-read |
| Depth of field | event `ACTIVATE_DEPTH_OF_FIELD` (89) and `TriggerActionGeneral.ActivateDepthOfField` 0x8520f5 -> `FXGfxEffectCtrl.command_fade_in(refNode, time)` 0x73ce78 copies five DOF values from a reference node (instant when time < threshold, else blended in state `Active`) | [R] |
| Screen fade | `ScreenFadeCtrl(Sprite)` (8 nodes): black sprite opacity; used by scene changes, tours, movies, save icon | callers listed; class not read |
| Target highlight | `FxHighlightCtrl` clones texture sheets (audit g13); `EffectsLib.Highlight` 0x714cc1 has **no caller** outside a debug prototype | [R] |

### 2.8 `FXGfxEffectCtrl` and the level grade [R + D]

- Data: `FXGfxEffectCtrl(GFXEffect)` nodes in `Levels/Game_Levels_Part2/<level>/Art.fragment`
  (Tutorial: `Art_NOlair.fragment`; main menu: `Levels/Game_Levels/MainMenu/FX.fragment`). Each level
  has "RS GFX" (`_iplayerctrl` 0) and "NO GFX" (1) with identical values; PvP has a third neutral
  node. `initialize_external` 0x73ccb6 sends `command_set_gfx_node(self)` to the `PlayerCtrl` of that
  playable character (2 = both), which forwards it to its `CameraCtrl` (`camera.gfxNode`, the
  renderer's `camera+0x348`).
- Native properties (`GFXEffect::RegisterMembers` 0x4c0af2, 61 properties, UI ranges in
  `wp7_tables.json` `native_nodes.GFXEffect`): fog (`fog`, `fogBegin`, `fogEnd`, `fogColor`); filters
  (`enableFilters`, `bloomWeight`, `bloomContrast`, `bloomBrightness`, `bloomSlopeBias`,
  `bloomDepthBias`, `brightness`, `saturation`, `contrast`, `tintPower`, `tintColor`, `gamma`,
  `noiseTexture`, `noiseIntensity`); AA (`enableAA`, `edgeDetectGradient`, `edgeDetectCutoff`); DOF
  (`enableDOF`, `focalDist`, `focalNearFallOff`, `focalFarFallOff`, `maxFocalBlur`, `skyBoxBlur`);
  LOD (`globalGeometryLodFactor`, `globalReflectionLodFactor`, `geometryLodMode`,
  `globalMaterialLodFactor`, `max/minMaterialLodLevel` POM 0 / Normal map 1 / Diffuse 2 / Vertex 3,
  `globalLightFadeStart/End`); shadows (`globalShadowPower`, `shadowSlopeBias`, `shadowDepthBias`,
  `shadowBlurPower`, `shadowMaxRange`); 2D water simulation (8); reflections (4); Perlin water (7).
- Shipped values (complete nodes in `wp7_tables.json` `level_grade_nodes`):

  | Level | fog 0..end, colour | bloomWeight / Contrast / Brightness | brightness | saturation | contrast | tint x power | gamma | AA / DOF |
  |---|---|---|---|---|---|---|---|---|
  | Bordello, Tutorial | 80 m, (0.027, 0.043, 0.07) | 0.2 / 0.5 / 0.1 | 0.05 | 0 | 0.22 | (0.54, 0.693, 1.0) x 0.3 | 1.2 | on / off |
  | NightClub | 120 m, (0, 0, 0) | 0.2 / 0.5 / 0.1 | 0.07 | 0 | 0.22 | (0.99, 0.545, 0.129) x 0.2 | 1.2 | on / off |
  | StreetsOfRiot | 600 m, (0.137, 0.118, 0.14) | 0.2 / 0.5 / 0.1 | 0.05 | -0.2 | 0.22 | (1.0, 0.5, 0.9) x 0.3 | 1.2 | on / off |
  | PlayerVsPlayer | 80 m, (0.027, 0.043, 0.07) | 0.2 / 0.5 / 0.1 | 0.05 | 0 | 0.22 | (0.72, 0.792, 0.96) x 0.3 | 1.2 | on / off |
  | MainMenu | 600 m, (0.138, 0.129, 0.14) | 0 / 0.46 / 0.13 | 0.2 | -0.51 | 1.08 | (0.96, 0.64, 0.192) x 0.42 | 1.0 | on / on |

  (The menu capture in wp1_renderer.md read contrast 1.19, gamma 1.12, brightness 0.25: those are the
  node values plus the user adjustments below.)
- Script layer: `m_originalsettings` / `m_basesettings` are `gfxnodeproperties` snapshots (bloom x3,
  brightness, saturation, contrast, tintPower, tintColor, gamma, fogBegin, fogEnd, fogColor).
  `command_override(settings, weight)` 0x73c41a sets each value to `settings x w + original x (1-w)`,
  adding the user offsets `m_nbrightnessadjustment`, `m_ncontrastadjustment`, `m_ngammaadjustment`,
  `m_nsaturationadjustment` (set from the options menu through `GameStateCtrl.command_set_*` ->
  `EffectsLib.SetBrightness/Contrast/Gamma/Saturation` 0x716505.. -> `command_set_*` 0x73c139..,
  mapped around a per-platform centre, `InitializePlatform` 0x735084). `GfxBlender`
  (CollisionBoxNode with two gfx nodes and two lights per hero, blends by position inside the box,
  `command_set_gfx_values`) has no instance.
- For a grade export a level therefore needs exactly one node per hero and no time dependence.

---

## 3. Camera

### 3.1 Structure [R + D]

`PlayerCtrl._esingleplaycamera` / `_ecoopcamera` -> a `CameraCtrl(Camera)` in
`GameEssentials/PlayerCtrl/{Rorschach,NiteOwl}{Single,Coop}.fragment`. `CameraCtrl.StateActive`
0x637f66 each frame: `UpdateActiveCameras` 0x627980 (sends `command_update_camera` to every active
camera object), `CameraEvaluator` 0x627a54 picks the active one, copies its `cameradata`
`{vWorldPos, qWorldOrient, nFov}` to the native camera, derives linear / angular velocity, and sets
the sound listener at the character's centre + 0.5 m with the camera's orientation.

| `CAMERATYPE` | Class | Use |
|---|---|---|
| 0 CHARACTER | `CharacterCamera` 0x65c614 | gameplay camera, two modes (3.2) |
| 1 CINEMATIC | `CameraCinematic` 0x63dfbe | `command_move_to_target(duration, lookAt, targetPos, fov, lockInput)` / `command_cut_to_target`; states CutToTarget, MoveToPos, AtPos (look-at triggers: `PlayerCtrl.command_enter_lookat_trigger`) |
| 2 SEQUENCE_PLAYER | (scene `Camera` nodes) | cutscene tours (3.6) |
| 3 CINEMATIC_TO_CHARACTER | `CameraCinematicToCharacter` | blend back |
| 4 CHARACTER_SET_POS | `CameraCharacterSetPos` | scripted placement behind the character |
| 5 COMBAT_SPECIAL_CUTS | `CameraCombatSpecialCuts` 0x63ea3f | finisher / counter shots (3.4) |
| 6 PLAYER_VS_PLAYER | `CameraPlayerVsPlayer` 0x658bce | PvP (3.5) |

Modifiers (`CAMERA_MODIFIER_TYPE`), applied by each camera's `ApplyModifiers` (0x6457f3 /
0x626d3d): orientation x shake x health roll x recoil tilt, FOV x recoil factor.

### 3.2 The character camera [R for structure, partly read for the maths]

Two states, chosen by `m_irequestedcameramode` (`CAMERA_MODE`): `StateActiveExploration` 0x651632
and `StateActiveCombat` 0x64c330. `command_combat_begin(target, allowCut)` 0x64376d requests COMBAT
**only when the player does not use the mouse** (`InputCtrl.command_uses_mouse`); with mouse look
the camera stays in exploration mode (`BaseState` 0x64c1b4 forces mode 0) [R].

Parameters (`cameramodeproperties`, built by `InitializeCameraProperties` 0x655e27 from the node;
values of `RorschachSingle`, differences in `wp7_tables.json` `camera.per_player_ctrl`):

| Group | Property = value | Meaning (UI caption) |
|---|---|---|
| framing | `_nwantedheight` 2.5, `_nmaxheight` 3.0, `_nwantedlookatheight` 1.2, `_nminimumfloorlift` 0.5 | camera height above the look-at, look-at height on the character (m) |
| | `_ndefaultfov` 55 (co-op 70 / 65) | vertical FOV |
| | `_nmaxdist` 3.51, `_nmindist` 2.88 (Nite Owl co-op 4.5 / 3.0), `_ncollisionmindist` 0.8 | distance band; the camera only moves when the target leaves the band |
| springs ("sluggish factors", 1/s, larger = stiffer) | look-at 16.34, catch-up 13.31, get-away 30, collision clip-in 8, to-min-dist 20, from-min-dist 1 | `x = lerp(x, target, min(k·dt·extra, 1))`; extra = nveryclosefactor² for look-at, nveryclosefactor for get-away; catch-up is `offset·dt·k`, not clamped; the collision clip-in factor is dead in combat [R 0x64cee1] |
| FOV | `_nfovblendintime` 0.65, `_nfovblendouttime` 2.2 | blend of the FOV factor (`MathLib.PowerSmooth`) |
| user control | `_nrotatespeed` 3 rad/s, `_ntiltspeed` 5 m/s, accel / decel factors 8.95 / 19.88, 5 / 10 | right stick: orbit and height |
| cornering | `_npredictingturnmaxrate` 0.75, `_npredictingturnmodification` 1.2 | turn prediction from the character's velocity |
| avoid characters | `_tavoidcharactertilt` true, scan length 0.6, width 0.65, lift scale 2.5 | raises the camera when a character stands between it and the hero |
| def (`CharacterCameraDef`) | heading max speed 4, accel 0.5 s, decel 0.3 s, dead zone 0.4; pitch max speed 2, start 0.3, dead zone 0.6; sticky user control 1 s; collision sphere diameter 0.2; char avoid radius 1.0 / 0.3; `m_nyheight` 1.85; x-offset sphere 0.8; fall-in convolution 0.99, start -0.8; corner max speed 2; catch-up powers 10 / 10 | exploration controller |

Combat update (`command_update_camera` 0x64cee1, 2 kLOC lifted; read: entry, look-at selection,
collision calls, exit): it is a **chase camera around the player, not a two-target framing camera**.
The look-at is the player (plus `_nwantedlookatheight`) unless an override entity is set by
`command_lookat_target_timed(entity, time, fovFactor)` 0x650d42 - then the look-at blends to that
entity for `time` seconds and the FOV factor goes to `fovFactor` (blend in / out times above);
`command_force_rotate(angle, time)` 0x650d85 orbits by `angle`. Collision: `CapsuleCheckHitStruct`
0x65487e / `CastRay` 0x644f50 / `LineChecks` 0x65436e against `_icameracollisiongroupmask`; on a hit
the distance clips in at the collision factor, and when the camera is squeezed it can push the
player (`CharacterRoot.command_set_push_back_data`, line 1513). `m_ntimepassedhistory` 0.05 is the weight of the frame-time average; the output low-pass is `out += (new − out)·avgDt/0.2` (0x650ad7), position and orientation alike. The user tilt uses the raw stick; the capsule casts are sphere sweeps of diameter 0.3. **Lock-on**: there is no
camera lock; `PlayerCtrl.command_hit_by` 0x7f900e sets `CharacterRoot.m_etargetlockentity` to the
attacker when target locking is enabled, and the camera's only target coupling is the timed look-at.

Exploration update (0x651b3d) uses `CharacterCameraStateManager` 0x65b93e: a table indexed by
`CAMERA_CHARACTER_DB` (27 ids) of `CharacterCameraDBItem` variants (look-at offset X / Y, vertical
FOV, distance, pitch min / max - each only when its `m_t*` flag is set; priority BASE / OVERRIDE;
`m_tallowfallbehind`) with child `CameraCharacterTransition`s (duration, allow user input, pitch /
yaw options: `m_tyawcharacterrelative`, `m_tyawtwocharacterrelative`, `m_tyawcombatavoidwall`,
`m_tyawcombatonattack`, `m_tyawinsideobjectconehold`, convolution blend).
`PickStateStickBased` 0x64bb35 selects IDLE (< 0.1), WALK (0.1–0.6), RUN (≥ 0.6) from the movement stick; OVER_SHOULDER is held while the stick is idle and pitch ≤ `m_novershoulderoutpitch`; `command_combat_begin` 0x64b496 picks a random `COMBAT` variant;
animation events of id 18 (`CAMERA`, 63 in data) with a `CAMERA_ANIMATION_EVENTS` type force the
drain-pipe / jump-down / grappling states (0x64b304); transitions are picked by target id
(`PickTransition` 0x643659). Shipped states [D]: DEFAULT (fov 45, dist 3.5, offset (-0.6, 1.2),
pitch -0.9..1.2), COMBAT (fov 60), RUN / WALK / IDLE, JUMP_DOWN (dist 5), GRAPPLING_HOOK (dist 15),
pipe states (dist 1.5-3, offset Y 2.0). `CameraCharacterCombatManipulator` has no instance.

### 3.3 Modifiers [R + D]

- `CameraModifierSinusShake` 0x6586f4: a list of `{nTime, nModifierTime, vDirection, nTimeFactor}`;
  each frame `rotation += (T - t)/T x sin(...) x direction` (0x643d95; the sine's argument is not
  visible in the decompilation, [I] `t x nTimeFactor`), removed at `t >= T`; real-time clock.
  Sources: damage (0.25 s, 0.02, 40), kills (0.5 s, 0.04, 30; `give_damage`), `CAMERA_CUT` events
  (`nShakeModifierTime`, `nShakeSize`, `nShakeTimeFactor`), Underboss landing.
- `CameraModifierRecoil` 0x6581b7: `{tiltAngle, tiltTime, fovFactor, fovTime}` blended with
  `MathLib.PowerSmooth`; at most one new recoil per 0.1 s. `CharacterRoot.command_do_recoil(pose)`
  0x6902c0 (the **attacker's** camera when a player lands a hit): intensity 0.5 light, 1.0 heavy,
  2.1 knock-down, 1.4 stun, 0.2 otherwise -> tilt `0.025 x intensity` rad and FOV factor
  `1 - 0.06 x intensity`, both over 0.3 s (`command_start_recoil_modifiers` 0x63618d). Kill:
  `command_do_fov_effect(0.85, 0.4 s)`.
- `CameraModifierHealthEffect` 0x657d54 [D values]: roll (dutch tilt) =
  `lerp(_nminhealthroll 0, _nmaxhealthroll 0.5 rad, 1 - h / 0.5)` below 50 % health, plus a "smack"
  of up to 0.4 rad decaying over 0.77 s when hit below 66 % health, capped at 1.0 rad; sign random
  per episode (`command_get_effect` 0x645f4e).

### 3.4 Combat special cuts - the finisher / counter camera [R + D]

There is **camera data per paired animation, as animation events; no animated camera tracks**.
Event `CAMERA_CUT` (id 59, case 0x6aa7e4) on the **master's** state builds a `combatcutdata` and
sends `CameraCtrl.command_set_combat_cut_data(data, root)` -> `CameraCombatSpecialCuts.
command_set_cut_data` 0x6325c5; `CAMERA_CUT_TO_CHARACTER_CAM` (61, 41 events) sends
`command_return_to_character_camera(m_nvalue)`.

| `AnimationEventWM` field | `combatcutdata` | Meaning |
|---|---|---|
| `m_nvalue` | `nTransitionTime` | blend time to this shot (0 = cut) |
| `m_ttruth1` | `tLookAtAttackTarget` | look at the attack target (the victim) instead of the actor |
| `m_ivalue00` | `iLookAtBoneID` | bone of the looked-at character (`CharacterVisual.command_get_bone_worldpos_controlled`); 18 = root + look-at height |
| `m_nvalue09` | `nLookAtHeightAboveGround` | m |
| `m_nvalue02` | `nDistanceToLookAt` | m |
| `m_nvalue05` | `nHeightAboveGround` | camera height, m |
| `m_nvalue10` | `nAngleToLookAt` | degrees around the look-at, relative to the heading between the two characters (`MathLib.ToHeading` / `ToDirection`); 0 = pick a free side |
| `m_nvalue03` | `nFov` | vertical FOV (co-op uses `ncoopfov`) |
| `m_nvalue04` | `nTimeMultiplier` | game speed during the shot |
| `m_ttruth2` | `tKeepPreviousPosition` | keep the camera position, change only target / fov / time |
| `m_nvalue06/07/08` | `nShakeModifierTime`, `nShakeTimeFactor`, `nShakeSize` | shake started with the cut |

Behaviour: the wanted position is validated with a capsule cast of radius 0.2
(`SetValidStartPos` 0x6341f7; with angle 0 a second side is tried); if no valid position or
transition exists (`HasValidTransition` 0x634f62) the camera returns to the character camera and
ignores the following cuts of that animation (`_tignorefollowingcuts`). The shot ends by itself when
the actor leaves the stored animation state (`StateCombatCut` 0x625aec). In **co-op** the first cut
locks all players, switches the acting player's camera to the full screen
(`CameraLib.SetCamera(-1, cam)`, `SetupCameraViewport(-1)`) and disables the HUDs; an AI partner is
told `command_force_step_back`. 259 `CAMERA_CUT` events ship; decoded per state in
`wp7_tables.json` `animation_fx_events`.

`LOOK_AT_TARGET` (id 45, 141 events; events.md section 4): `command_lookat_target_timed(target,
m_nvalue, m_nvalue02)`; shipped 0.7 s and FOV factor 0.61 on most - a short push-in on the victim
or (bool1) on the actor, in the *character* camera; `m_ivalue00 == 1` adds a 180 degree orbit.

### 3.5 Co-op and PvP [R]

- `CameraCtrl.command_activate(playerId, isCoop, character)` 0x637de0 -> `CameraLib.
  SetupCameraViewport` 0x637b5c: game mode 3 (`COOP`) -> `SetViewportLeft` / `SetViewportRight`
  (which player gets which half follows `PlayerManager.m_tisplayer1controllingrorshachincoop`),
  otherwise `SetViewportFullscreen`. So co-op is a **vertical split screen with two independent
  character cameras**; there is no shared two-player framing in co-op. The co-op fragments use a
  wider default FOV (70 / 65) and for Nite Owl softer springs. `PlayerHUD._esplitscreenseperator`
  draws the divider.
- `CameraPlayerVsPlayer` (`_nfov` 40, `_nlookatheight` 1.0, `_nlookatpitch` 1.2, `_nsmoothing` 0.005):
  one shared camera - the primary player's object computes it (`UpdateCamera` 0x64748c: center = R + 0.5 (N − R); closest = N if |cam − N|² < |cam − R|² else R;
  n = normalize(pivot − center); lookat = center + up · _nlookatheight; ponline = center + n ·
  dot(closest − center, n); D = clamp((|closest − ponline| + 2) / tan(hfov / 2) + |ponline −
  center|, 2, 999); pos = lookat − n D + up D tan(_nlookatpitch); the distance uses the character
  **closest to the camera** and its distance to the centre→pivot line + 2 m, not the separation;
  no smoothing), the secondary copies it
  (0x6472c5). Start / end use `ScreenFadeCtrl`.

### 3.6 Cutscene cameras [R + D]

`TriggerActionCamera` 0x850da9, `_iaction` (`TRIGGER_ACTION_CAMERA_ACTIONS`): 0 `CAMERA_TOUR`,
1 `SET_CAMERA`, 2 `END_TOUR`, 3 `SET_CHARACTER_CAM_DIR` (74 nodes in Bordello `Gameplay/Cameras.
fragment`: 24 / 26 / 0 / 24). A tour node has a child `PropertySequenceNode` (`sequence` =
`/Levels/.../Sequence/Cam_*.sequence`) whose children are the `Camera` nodes of the shots, child
`SET_CAMERA` actions that switch between them, and character / sound actions. `StateTour` 0x84bed0:
resolve the viewport target (`VIEWPORT_TARGET` RORSCHACH / NITE_OWL / BOTH / ACTIVATOR), optional
start transition (`BLACK_SCREEN_TRANSITIONS` CUT / FADE / CUT_TO_BLACK), `DisablePlayerCtrl`,
`CombatOrchestrator.command_pause_attack`, play the sequence, move the listener with the camera,
allow skipping after `_tunskippabletime`, end at relative play position 0.99 or on skip, then
`_eontourend` / `_eontourskipped` actions. The sequences key `localpos`, `localorient` (Euler
degrees, FORMATS_MISC.md) and `fovvertical` per `Camera` (example `Cam_MainHall.sequence`: 13 s,
five cameras, spline keys). Movies (Bink) are `TriggerActionMovie`. In-game use-trigger cameras
(`TNT/Production/Fragments/Cameras/*`: ladders, drain pipes, jump-downs, lift gate) are the same
mechanism with short sequences.

---

## 4. HUD and feedback

### 4.1 HUD classes [R + D]

HUD fragments: `GameEssentials/PlayerCtrl/{Rorschach,NiteOwl}HUD_{SP,Coop}.fragment`, instanced by
four `PlayerHUD(FragmentNode)` nodes in `PlayerCtrl.fragment`.

| Element | Class / node | Reads | Shown when |
|---|---|---|---|
| Health bar | `HudBar(Sprite)` "HealthSprite" (+ `SpriteBar` fill / empty, label `TextBox`) | `CharacterRoot.m_nhealth` / def `m_nmaxhealth` (`HandleHealthBar` 0x7f2b83) | `_thealthbar` (true) |
| Rage / electrify bar | `HudBar` "RageSprite" (`RageFillSprite`, `EnergyFillSprite`) | Rorschach: `m_nrage` / `m_nmaxrage`; Nite Owl: `m_nelectrifypower` / max, charges; `SpriteBar.command_set_full_size_pulse` when the ability is unlocked and full (`HandleProgressBar` 0x7f2c74) | max > 0 |
| Damage overlay | `Sprite` "DamageSprite" (`HitOverlay.bmp`) | 1.5 | after damage |
| Use / interaction prompt | `TextBox` "UseIcon" | trigger type -> text slot index (0 -> 0x57, 1 -> 0x5f, ... 0xf -> 0x10f; `SetTriggerUseType` 0x7f2a38), device glyphs via `ProjectLib.SetTextSlotParams`; opacity pulses | inside a use trigger |
| Combo display | `ComboBuildupHud(TextBox)` + 14 `ComboButtonHud` + 2 `ComboTextShaker` | `command_visualize_combo_buildup(list(comboitemstruct))` 0x6ed9d5: one button glyph per combo step (logical button -> device button text), last one pulsates, build-up sounds 1 / 2 by length; `command_visualize_failed_combo` drops them; completed combo shows its name. It is a **button-sequence display, not a hit counter** | while a combo is alive (`CharacterRootLogic.command_update_combo_timing` fades it) |
| Finisher prompt | on the **enemy**: four `Sprite` + `SpriteWobbler(TextBox)` in `CharacterRootTemplate_Enemy.fragment` (Fast / Heavy / Throw / DodgeBlock) | `CharacterRoot.DecreaseHealth` (audit d5): health below `m_ncriticalhealth` by a player's hit -> one random button for `m_nfinishicontime` | critical state |
| Tutorial box | `PlayerTutotialHUD` + `TextBoxContentSizer` | `PlayerHUD.command_show_tutorial(integer,integer)` | tutorial events |
| Progression / pickup | "ProgressionHUD", "Pickup" (`PropertySequenceNode`) | `WaypointProgressionCtrl`, `command_got_pickup` | - |
| Boss bar | `BossHUD` 0x63a862 (name box, health bar) | `command_activate(entity)`; only for the Twilight Lady | boss fight |
| Subtitles | `SubtitleHUD(TextBox)` 0x84f6b4 | `SoundDef` playback asks `command_get_subtitle_slot_for_sound_slot`, then `command_show_subtitle(slot, time, owner)` -> `SubtitleSlot.GetIndexFromSoundSlotAndTime`; off when `GameStateCtrl.command_get_subtitles` is false | a subtitled sound plays |
| Save icon, reconnect controller, PvP result, trial timer | `SaveHUD`, "PleaseInsertController", "PlayerVsPlayer" (sequence on `opacity` / `textscaling`), `TrialTimer` | - | - |
| Enemy health bars, lock-on reticle, objective text | **none exist** (objectives are tutorial / progression boxes; targets get no marker) | - | [D + R] |

### 4.2 Sprite and text rendering [R props]

- `Sprite` (0x4c7270, 53 properties): `texture`, `spriteOffset` / `spriteSize` (pixels of a
  reference resolution; `...RelativeToScreen` forms), anchors (`horizontalSizeModifier`,
  `left/right/top/bottomAnchor`), `opacity`, `is3D` (+ `axisAlign3d`, `constantSizeMode`,
  `distFadeStart/End`, `infiniteDistance`), `priorityLayer` (draw order), `angle`, four corner UVs and
  colours, `clampTextureU/V`, `usePostProcessing`, mouse input. Drawn in the `ImmRA` pass with
  `FixedFunctionVS/PS[TEXTURING]` (wp1_renderer.md).
- `TextBox` : Sprite (0x4ca379): `font` (`.font`, FORMATS_MISC.md), `text` or `textSlot` +
  `textSlotIndex` (`useSlotIndex`, `textResMode`), `textColor`, `textScaling`, `horizontalSpacing`,
  `horizontalAlignment` (left / right / center / justify), `verticalAlignment`; messages
  `SetParameterFromString(i, s)`, `SetParameterFromTextSlotIndex(slot, index, i)` (parameter
  substitution - used for button glyphs). Fonts in the HUD: `TwCentMTCondExtra60.font` (26 boxes),
  `DaveGibbons40.font`. `Font` has one property, `textAlphaReference`.
- `TextSlot` (0x494bfc): `textRes` (`*.txt` asset), `currentIndex`, read-only
  `textStringIdentifier`, `numTextIndices`, `currentTextContent`. `SubtitleSlot` : TextSlot adds
  `defaultDuration` and the lookups by sound slot / key and time.

### 4.3 Text assets [R + D]

`TextSlots.fragment` [D]: `MenuTextSlot` -> `/Localize/Menu_uk_pc.txt`, `TutorialTextSlotRS` ->
`TutorialRS_uk_pc.txt`, `TutorialTextSlotNO` -> `TutorialNO_uk_pc.txt`, `Warnings` ->
`Warnings_uk_pc.txt`, `ControllerLayoutTextSlot` -> `ControllerLayout_pc.txt`,
`KeyboardLayoutTextSlot` -> `KeyboardLayout_uk.txt`. `MovieDbPart2.fragment`: eight cutscene
`SubtitleSlot`s (`/Localize/Cutscene08a_uk.txt` ...) and `IngameSubtitles` ->
`SubtitlesPrison_uk.txt`.

Format (`TextRes::vfunc_24` 0x5387ae; verified on `Localize/ControllerLayout_pc.txt`: 996 entries,
0 trailing bytes; parser `work/wp7/textres.py`):

```
[u32 count]  count x { [u32 nchars incl. NUL][UTF-16LE key]  [u32 nchars][UTF-16LE value] }
```

A text slot index is the entry index. Button glyphs are single characters of the font's icon page
(`GAMEPAD_LOWER` = U+00A2, `GAMEPAD_DPAD_UP` = U+00AD ...). **Of these assets only
`ControllerLayout_pc.txt` is in the extraction**; the `_uk` text assets and the subtitle tables are
not on disk (they are language-dependent NAZ entries), so their contents and the key convention of
the subtitle tables are [N].

### 4.4 Menus (high level; handler lists read, bodies not)

`MenuLib` (232 kB lifted, the helpers), `MenuCtrl` 0x7c3d2d (text slots, open / close broadcast to
listeners such as `PlayerHUD.command_menu_window_opened`), `MenuWindow` 0x7cbb6d (widget list,
selected index, push / replace / close, up / down, scrolling with `m_imaxdisplayedwidgets`,
toolbar type, activate / deactivate listeners), widgets `MenuWidgetBase` -> `MenuWidgetButton`
(states Unselected / Selected, `_inametextslotindex`, platform / trial / in-game filters, on-trigger
listener), `MenuWidgetSelector`, `MenuWidgetButtonMap`; `MenuNavigationToolBarCtrl` (`TOOLBAR_TYPES`),
`MenuMouseInput`, `MenuButtonPulsate`, `MenuSoundInit` (`MENU_SOUNDS`: silence, click, change
selection), controllers `MainMenuSceneCtrl`, `MenuIngameCtrl`, `MenuSettingsCtrl`,
`MenuAbilityCtrl`, `MenuTutorialCtrl`, `WarningWindowCtrl` (`WARNINGS`). 29 `MenuWindow` and 103
`MenuWidgetButton` nodes in `GameEssentials/Menu/*.fragment`.

### 4.5 Rumble [R + D]

`VibrationMotorCtrl` 0x8b5cbc, one per `PlayerCtrl` (`_ndamageduration` 0.23,
`_nmin/maxvibrationpoweratdamage` 0.3 / 1.0). `SetVibration(power)` 0x8a9645 clamps to 0..1 and
sends `InputCtrl.command_set_vibration(player, motor, value)` (-> XInput): power <= 0.5 -> motor 0
off, motor 1 = 1.5 x power; above -> both = power. `StateActive` 0x8ab937 counts the time down in
real time, fades linearly when asked, and forces 0 while the game is paused (time multiplier 0).

| Trigger | Duration, power, fade |
|---|---|
| player damaged (1.5) | 0.23 s, 0.3 + 0.7 x (1 - health), no fade |
| `IMPACT_EFFECTS` by a player whose partner confirms the hit, pose 1-6, 23, 24 | 0.2 s, 0.15 |
| ... pose 7-12, 19-22, 25, 26 | 0.35 s, 0.2, fade |
| ... pose 13-18, 27, 28 | 0.55 s, 0.2, fade |
| `RUMBLE` event (id 82, 231 events) | `m_nvalue` s, `m_nvalue02`, fade = `m_ttruth1` (finishers: 0.1-0.3 s at 0.5-1.0) |
| counter / dodge / block start, charge, fire volume, Underboss | `command_do_rumble_effect` senders 0x6867b7, 0x686a17, 0x686e56, 0x67d89e, 0x737257, 0x890013 (values not read) |

---

## 5. Walkthrough: baton hit, counter, finish

Rorschach (gamepad, single player) against a Dominatrix holding the police baton. Times are
playpos x clip length at normal speed, counted from each state's start; slow-motion segments stretch
real time. Sources: events from the binary `CharacterAnimation/*.fragment` (decoder
`work/wp7/evdec.py`), rules from sections 1-4.

**A. She swings: `Enemy04` state `1H_light_A`, clip `EN4_COM_WPN_1H_light_A` (2.67 s).**

| t | Event | What the player sees / feels | Source |
|---|---|---|---|
| 0 | attack start | no particle; speak 34 `MELEE_START_HEAVY` + `Heavy_Attack_start` whoosh (`Attack_start_weapon`) | 0x679525 |
| 1.45 | `PRE_IMPACT` | victim gets `command_hit_soon` (reaction choice) | events.md |
| 1.53 | `IMPACT`, authored pose 3 `LIGHT_UPPER_RIGHT` | `give_damage` on Rorschach -> `RSH_DamageEffectDef`, head, weapon STEEL -> **`RSH_dam_head_weapon_steel`**: `BluntImpactHead_Heavy_uk.particle` (blood) + `BluntImpactBody_Light.particle` at the impact point, weapon-steel hit sound, speak 26 | 1.3 |
| 1.53 | `DecreaseHealth` | HUD: health bar drops; `DamageSprite` to 0.5 + 0.5 x lost health, then fades; rumble 0.23 s; camera shake 0.25 s (0.02 rad); below 66 % health a roll "smack"; hit animation by `DAMAGE_POSE` | 1.5 |
| 1.53 | weapon | baton durability -0.16 | 0x8b33e0 |
| - | not fired | no light flash (her visual has no `LightFlash`), no camera recoil (she has no camera), no slow motion (pose 3) | 2.7, 3.3 |

**B. Player counters: `Rorschach` state `Disarm_1h`, clip `RSH_COM_ATT_disarm_EN4_WPN_1H`
(4.33 s), partner state `Disarmed_by_Rorshack` (`EN4_COM_DMG_WPN_1H_disarm_RSH`, 4.33 s, pair 318).**

| t | Event | Effect |
|---|---|---|
| 0 | counter start | rumble (`command_force_counter_attack` 0x6867b7); combo HUD shows the counter button |
| 0.43 | `DISABLE_ROTATION_INPUT` | - |
| 0.69 | `SPEAK` 34 | Rorschach effort line |
| 0.85 | partner `ABSOLUTE_GOTO_TARGET_POS` | she is pulled to the pair position |
| 1.13 | `LOOK_AT_TARGET` (0.7 s, FOV factor 0.61, self) | character camera pushes in on Rorschach for 0.7 s |
| 1.13 | `DROP_WEAPON_WITH_ANIM` | - |
| 1.60 | `IMPACT_EFFECTS` pose 5, local (0.5, 0.35, 0.3) | on her: `EN_dam_body_light` (`BluntImpactBody_Medium.particle`, sound, speak 30); rumble 0.2 s at 0.15; camera recoil intensity 0.5 (tilt 0.0125 rad, FOV x0.97, 0.3 s) |
| 1.95 | `COUNTER_ATTACK_WEAPON_STEAL` | the baton moves to Rorschach's hand |
| 2.69 | `IMPACT_EFFECTS` pose 8 | he now holds the baton (STEEL): `EN_dam_head_weapon_steel` (`BluntImpactHead_Heavy_uk` + `BluntImpactBody_Light`), speak 26; rumble 0.35 s at 0.2 fading; recoil intensity 1.0 (0.025 rad, FOV x0.94) |
| 2.77 | `IMPACT` | the real damage (non-attack-state branch: partner `is_attack_successful` -> `give_damage`); if this puts her below `m_ncriticalhealth` 44: **finisher prompt** - one random button sprite over her for 3 s |
| 2.90 / 3.25 | `EXTEND_COMBO_TIME` 1.01 / `ALLOW_ATTACKS` | combo window |

No `CAMERA_CUT` in this counter: the whole counter plays in the character camera.

**C. Player finishes: `Rorschach` state `FinishingMovesEnemy04/Finish_move_WPN_1H`, clip
`RSH_COM_WPN_1H_finish_EN4_B` (3.6 s); partner `Finished_by_Rorshack_1H`
(`EN4_COM_DMG_finish_RSH_1H_B`, 3.6 s, pair 384).**

| t | Event | Effect |
|---|---|---|
| 0 | partner `DROP_WEAPON` (enter) | - |
| 0.61 | `SPEAK` 34 | effort line |
| 0.65 | `CAMERA_CUT` cut (0 s): look at victim, bone 5, distance 1.5 m, height 2.1 m, FOV 65 | hard cut to a high close shot of her |
| 0.90 | `IMPACT_EFFECTS` pose 2 + `RUMBLE` 0.13 s at 1.0 | `EN_dam_head_weapon_steel` particles + sound, speak 26; recoil 0.5 |
| 0.94 | `LOOK_AT_TARGET` | stored in the character camera (not visible while the cut camera is active) |
| 1.44 | `IMPACT_EFFECTS` pose 2 + `RUMBLE` 0.13 s at 1.0 | same effect again |
| 1.85 | `CAMERA_CUT` 0.1 s: look at actor, bone 14, distance 2.6, height 1.2, angle -35 deg, FOV 45, **time x0.07** | slow-motion side shot of the wind-up |
| 1.91 | `CAMERA_CUT` 0.1 s: look at victim, bone 3, height 0.7, FOV 60, time x1, keep position | re-target to her, normal speed |
| 1.94 | `SOUND` `f131c37c` (at entity) | impact sweetener |
| 2.02 | `IMPACT_EFFECTS` pose 8 + `RUMBLE` 0.3 s at 1.0 fading | `EN_dam_head_weapon_steel`; recoil 1.0 |
| 2.27 | `KILL_ANIMATION_PARTNER` | her death: `give_damage` lethal -> speak 32 `DEATH`; ragdoll |
| 2.70 | `CAMERA_CUT_TO_CHARACTER_CAM` 0.3 s | blend back to the character camera |
| 2.77 | `ALLOW_ATTACKS` | - |
| 3.42 | `EXTEND_COMBO_TIME`, `SPEAK` 12 `TAUNT_FINISHING_MOVE` | Rorschach's line; combo HUD completes |
| 3.6 | partner `DIE` | - |

The enemy-agnostic variant of the same clip (`FinishingMovesEnemy01and03/Finish_move_WPN_1H`) has a
different event list (six cuts, a 0.666 s shake of size 0.1); the list above is the `Enemy04` one.
Every `CAMERA_CUT` is skipped when its capsule test fails (3.4).

---

## 6. Extractor consequences

1. **Particle reader.** Replace the heuristic block walk by the engine grammar (2.1): return
   `{asset, types:[{type, affectors:[], spawners:[], initializers:[]}]}`, use the payload dword
   count, add the five missing names, lower-case the seven mis-cased ones, and attach the dropdown
   names (`simulationMode`, `blendMode`, `src/dstBlend`, `blendOp`, `renderStyle`, `alignment`,
   `eventChannel`, `animationMode`) from `wp7_tables.json` `particle.classes`. Parse gradient
   strings into key lists. Validation: all 89 files already tile; the new reader must reproduce
   the same records and the counts.
2. **`fx` section in the animation metadata.** Today an event exports `name, playpos, on_enter,
   event_id, value`. Export the whole payload (`m_ivalue00`, `m_nvalue02..10`, `m_ttruth1..3`,
   `m_vvalue1/2`, `_etarget00..02`, `m_ieventtype` with its four trigger types) and add decoded
   records per state: `impact_effects` (pose, local position / direction, ignore-weapon),
   `camera_cuts` (the `combatcutdata` mapping of 3.4), `rumble`, `look_at`, `sound` / `speak`. A
   ready decoder is `work/wp7/evdec.py`; the decoded set (273 states, 1,328 events) is in
   `wp7_tables.json` `animation_fx_events`.
3. **Effect tables.** Export `EffectDb.fragment` as `effects[name] = {id, particles[{asset,
   placement, local transform}], sounds, speak}` and the three `CharacterEffectDef`s with the rule
   of 1.3, so that a consumer can resolve "pose + weapon + victim" to particle files. Carry the
   weapon `m_ieffecttype` in the weapon export (`weapons` table).
4. **Finisher camera with pairs.** For each pair, attach the master's `camera_cuts` and
   `CAMERA_CUT_TO_CHARACTER_CAM` to the pair record (time in seconds = playpos x master duration).
   A previewer can place the camera from look-at bone + distance + height + angle.
5. **Level grade metadata.** Per level, export the `FXGfxEffectCtrl(GFXEffect)` node of
   `Art.fragment` (`level_grade_nodes`): fog, bloom, brightness, saturation, contrast, tint, gamma -
   the inputs of the post-process formula in wp1_renderer.md section 6.
6. **Camera rig metadata** (optional): `camera.per_player_ctrl` (state table, transitions,
   springs) and the modifier constants.
7. **Text.** Add a `TextRes` decoder (4.3) and extract the localized text assets
   (`Menu_uk_pc`, `TutorialRS/NO_uk_pc`, `Warnings_uk_pc`, `KeyboardLayout_uk`, `Cutscene*_uk`,
   `SubtitlesPrison_uk`) - they are named by the fragments but absent from the extraction. With
   them, HUD prompts (text slot indices) and subtitles become exportable.
8. **Motion trail / emitters on characters**: the character export can list `EmitterNode`s and
   `LightFlash` of the `CharVisual` fragments (bone, asset) as attachments.
9. Documentation corrections: FORMATS_MISC.md "third list ... particle-emission surface is
   inferred" -> read (2.4); the `.particle` paragraph (2.1); `dominatrix_audit.md` i1 / wp6 2.4
   "sharp weapon fires its own effect" -> TASER.

## 7. Not established

| Item | What it would take |
|---|---|
| `VarianceInitializer` (6.4 kB) and `GeometryCollisionAffector` (4.2 kB) bodies; `IlluminationAffector` variants; exact use of `numVariations`, `renderInstanced`, "Local Instanced" | read 0x54964e, 0x54bfab, 0x55eba4-0x55ed81, 0x55d6b2 |
| Alignment value -> vertex shader variant; `particleDepth` use; billboard vertex maths | read the particle render instance (`FUN_00561e1c`, `ParticleRI`) and `ParticleVS` bytecode |
| Head advance of the particle ring, emitter auto-delete flag (+0x14) | read `FUN_0055a400`, `FUN_0055d161`, callers of emitter+0x14 |
| `DecalManager` geometry (projected quad or clipped mesh) | read 0x4c4a8c, 0x4c5777 (no data uses it) |
| Lens flare update / occlusion maths | read lensflare.cpp 0x4bd024 area (7.7 kB) |
| Value of `CharacterRoot._nslomotimemultiplier`; who plays `RageMaterialPulse.sequence` | property default in the game database or the level root fragments (`Bordello.fragment` etc., not staged); callers of `PropertySequenceNode.Play` in `CharacterRootLogic` rage handlers |
| TASER weapon node (`g_efaketwilightladyweapon`) and its `m_ieffecttype` | parse the Twilight Lady's `m_emodelcollbash1h` collection |
| Combat camera maths in full (0x64cee1: pull timers, min-dist blending, predicted turn, avoid-character lift), exploration camera (0x651b3d), transition yaw options | done: FX_META.md "Gameplay cameras"; the exploration collision helpers (`LineChecks`, `CapsuleCheck`, `OffsetXCheck`) are in FX_META.md |
| `CameraCombatSpecialCuts` angle convention (sign, reference heading) and `HasValidTransition` | read 0x6341f7 / 0x634f62 fully; check against one finisher in game |
| PvP framing formula | done: FX_META.md "Gameplay cameras" |
| Sine argument of the shake | disassemble 0x643d95 |
| `ScreenFadeCtrl`, `SpriteWobbler`, `SpriteBar`, `ComboTextShaker`, `PlayerTutotialHUD`, `BossHUD` bodies; menu controllers | lifted classes, not read |
| Sprite / TextBox draw path (layout from anchors, text wrapping, font kerning), `Font` asset use | `ui.text` natives 0x4b39d2.. (36 kB) |
| Contents and key convention of the localized text assets and subtitle tables | extract them from the NAZ localized section first |
| Rumble values of counter / dodge / block / charge | read the six senders |
| Whether the `_uk` particle set has censored siblings on other platforms / languages | compare the X360 / PS3 archives |

## 8. Coverage

Lifted classes read (bytes of lifted text; F = all gameplay handlers, P = the handlers named in the
text, H = header / handler list only): EffectCtrl 22 k F; EffectBase 27 k F (debug skipped);
EffectParticle 36 k F; CharacterEffectDef 17 k F; EffectsLib 40 k H + callers; GFXEffectType 12 k H;
GFXParticleEffectType 12 k P; GFXDecalEffectType 20 k P; GFXPackageCtrl 29 k H; CollisionEffectCtrl
22 k H; DynamicObjectsEffectCtrl 95 k H; FXGfxEffectCtrl 31 k P; GfxBlender 23 k H; FXLighting 49 k
H; FXLightning* H; FxHighlightCtrl 31 k H; LightFlash 4.5 k F; ElectricArmor 74 k H; WeaponBase 49 k
H; CameraCtrl 51 k P; CameraLib 20 k P; CharacterCamera 304 k P (states, small commands, property
builder; update bodies skimmed); CharacterCameraStateManager 49 k P; CharacterCameraDBItem,
CameraCharacterTransition H; CameraCombatSpecialCuts 128 k P; CameraModifierSinusShake 16 k F;
CameraModifierRecoil 12 k F; CameraModifierHealthEffect 11 k F; CameraPlayerVsPlayer 39 k P;
CameraCinematic 49 k H; TriggerActionCamera 112 k P; PlayerHUD 63 k P; HudBar, BossHUD H;
ComboBuildupHud 36 k P; ComboButtonHud 30 k H; SubtitleHUD 15 k F; VibrationMotorCtrl 14 k F;
PlayerCtrl (three handlers); CharacterRoot (`give_damage`, `do_recoil`, `give_block_damage`,
`DecreaseHealth` send, `set_weapon`); CharacterRootLogic (event cases 56, 59, 61,
`SetCloseCombatDamageToTarget` tail); MenuCtrl, MenuWindow, MenuWidgetBase, MenuWidgetButton H.

Native: particle loader and object reader (0x55d3ed, 0x511f96, 0x511eb5, 0x510e5f), 30
`RegisterMembers`, 16 module update bodies, simulation step (0x55b16f, 0x55a722, 0x55a643,
0x55a503, 0x55e17b), slot culling 0x5586e3, emitter create 0x55d059, surface spawner (0x553bae,
0x54fc6b, 0x54fba7, 0x54decc head), instance packing 0x476a4b, sort 0x56189f, `REParticles` ctor
0x58d1fe, `TextRes` loader 0x5387ae, property tables of `GFXEffect`, `LensFlare`,
`LensFlareManager`, `DecalManager`, `GeometryEffect`, `GEKeyFrame`, `Sprite`, `TextBox`,
`TextSlot`, `Font`.

Data parsed (binary, toolkit `kapow_fragment` / `kapow_props` / `decode_sequence`): 89 `.particle`
(census on the PC; 49 staged), `EffectDb`, `ParticleDb`, `CollisionGFXDB`, `WeaponDB`,
`PlayerCtrl` + 8 player camera / HUD fragments, 5 level `Art.fragment` + main-menu `FX`, 3
`Cameras.fragment`, 8 `CharVisual`, 45 `CharacterAnimation` fragments (5,119 events), `TextSlots`,
`MovieDbPart2`, 5 sequences, `ControllerLayout_pc.txt`; class-name index of all 604 non-sound
fragments.

## 9. Files

- `findings/wp7_fx_camera_hud.md` (this report), `findings/wp7_tables.json` (enums; effects and
  defs; weapons; Dominatrix per-pose tables and attack states; particle grammar, classes,
  properties, census; native node property tables; level grade nodes; camera tables and constants;
  rumble; player damage feedback; 1,328 decoded fx / camera / rumble animation events; HUD text).
- `work/wp7/`: `c.py` / `s.py` (condensed and skeleton views of a lifted class), `who.py` (callers
  by regex), `k.py` (constants from exe bytes), `regm.py` (native `RegisterMembers` -> property
  table), `pp.py` (particle dump), `dumpf.py` (fragment tree dump, `txt/`), `efftab.py`,
  `build_tables.py`, `camtab.py`, `evx.py` / `evdec.py` (animation events, full payload),
  `textres.py`, `final_json.py`; intermediate `efftab.json`, `dom_tables.json`,
  `camera_tables.json`, `gfx_nodes.json`, `weapons.json`, `particle_props.txt`, `native_props.txt`.
