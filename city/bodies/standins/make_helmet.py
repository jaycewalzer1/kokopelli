"""Editor Python (scratch project): GA_StandinHairHelmet = GA_StandinHair whose LOD 0 is a rigid 'Meshes' (helmet)
LOD, so a Low body can show it (the server forces the first non-strands LOD). Appends to import_standins.json."""
import json, os, traceback
import unreal

HERE = os.path.dirname(os.path.abspath(__file__))
SRC, DST = '/Game/Characters/TestParts/GA_StandinHair', '/Game/Characters/TestParts/GA_StandinHairHelmet'
EAL = unreal.EditorAssetLibrary
path = os.path.join(HERE, 'import_standins.json')
rep = json.load(open(path)) if os.path.exists(path) else {}
h = rep['helmet'] = {}
try:
    if EAL.does_asset_exist(DST):
        EAL.delete_asset(DST)
    g = EAL.duplicate_asset(SRC, DST)
    sphere = unreal.load_asset('/Engine/BasicShapes/Sphere')
    meshes = g.get_editor_property('hair_groups_meshes')
    m = unreal.HairGroupsMeshesSourceDescription()
    for k, v in (('imported_mesh', sphere), ('group_index', 0), ('lod_index', 0)):
        try:
            m.set_editor_property(k, v)
        except Exception as e:  # noqa: BLE001
            h.setdefault('errors', []).append(f'mesh.{k}: {e}')
    meshes = list(meshes) + [m]
    g.set_editor_property('hair_groups_meshes', meshes)
    lods = list(g.get_editor_property('hair_groups_lod'))
    h['groups'] = len(lods)
    for grp in lods:
        ls = list(grp.get_editor_property('lods'))
        h['lods_before'] = [str(x.get_editor_property('geometry_type')) for x in ls]
        ls[0].set_editor_property('geometry_type', unreal.GroomGeometryType.MESHES)
        grp.set_editor_property('lods', ls)
    g.set_editor_property('hair_groups_lod', lods)
    EAL.save_loaded_asset(g)
    g = unreal.load_asset(DST)
    h['lods_after'] = [str(x.get_editor_property('geometry_type')) for x in g.get_editor_property('hair_groups_lod')[0].get_editor_property('lods')]
    h['meshes'] = len(g.get_editor_property('hair_groups_meshes'))
except Exception:  # noqa: BLE001
    h['exception'] = traceback.format_exc()
json.dump(rep, open(path, 'w'), indent=1)
unreal.log_warning('[STANDINS] helmet ' + json.dumps(h))
