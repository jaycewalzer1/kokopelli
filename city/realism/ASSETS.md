# Downloaded assets (realism pilot)

All from [ambientCG](https://ambientcg.com) under **CC0 1.0** (public domain dedication: free for any use, no attribution
required; see https://docs.ambientcg.com/license/). Downloaded 2026-11-06 without an account, as PNG zips via
`https://ambientcg.com/get?file=<Id>_<Res>-PNG.zip`, into `mac_server/Saved/realism_src/<Id>/` (not in git). Only the
colour, NormalDX, roughness, AO and opacity maps are kept; the bundled .blend/.usdc/.mtlx/.tres files were deleted.

| Asset | Page | Resolution | Used for |
|---|---|---|---|
| Planks023A | https://ambientcg.com/view?id=Planks023A | 2K | `M_Timber_Real` (deck, rails, CLT facades) |
| Plaster003 | https://ambientcg.com/view?id=Plaster003 | 1K | `M_RammedEarth_Real` (render / earth walls) |
| PavingStones138 | https://ambientcg.com/view?id=PavingStones138 | 1K | `M_PermeableStone_Real`, `M_Path_Real` |
| Metal009 | https://ambientcg.com/view?id=Metal009 | 1K | `M_Metal_Real` |
| Bark014 | https://ambientcg.com/view?id=Bark014 | 1K | `M_Bark_Real` |
| Moss002 | https://ambientcg.com/view?id=Moss002 | 1K | `M_Moss_Real`, `M_GreenRoof_Real` |
| LeafSet024 | https://ambientcg.com/view?id=LeafSet024 | 2K | leaves composited into the leaf-card atlas `T_R_Leaf_*` (`M_Foliage_Real`) |

Derived files: `Tools/look/realism_tex.py` packs them into `T_R_*_C` (colour) / `T_R_*_D` (normal, roughness, AO) and
builds the leaf-cluster atlas; `Tools/look/make_realism.py` imports them into `/Game/Realism/Textures`.
