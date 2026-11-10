"""Editor Python (scratch project, USDImporter enabled on the command line): imports standin_hair.usda as a
GroomAsset under /Game/Characters/TestParts, for the m6 part tests (mac_server/tests/test_bodies.py). Writes
import_standins.json next to this file. Quits the editor when MH_QUIT is set."""
import json, os
import unreal

HERE = os.path.dirname(os.path.abspath(__file__))
DEST = '/Game/Characters/TestParts'
rep = {}
try:
    opts = unreal.UsdStageImportOptions()
    for k, v in (('import_actors', False), ('import_geometry', True), ('import_materials', False),
                 ('import_skeletal_animations', False), ('import_level_sequences', False), ('import_groom_assets', True)):
        try:
            opts.set_editor_property(k, v)
        except Exception as e:  # noqa: BLE001
            rep.setdefault('option_errors', []).append(f'{k}: {e}')
    task = unreal.AssetImportTask()
    task.filename = os.path.join(HERE, 'standin_hair.usda')
    task.destination_path = DEST
    task.automated = True
    task.save = True
    task.replace_existing = True
    task.options = opts
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
    rep['imported'] = [str(p) for p in task.imported_object_paths]
    assets = unreal.EditorAssetLibrary.list_assets(DEST, recursive=True)
    rep['assets'] = {}
    for a in assets:
        o = unreal.EditorAssetLibrary.load_asset(a)
        rep['assets'][a] = o.get_class().get_name()
        if isinstance(o, unreal.GroomAsset):
            new = f'{DEST}/GA_StandinHair'
            if a.split('.')[0] != new:
                unreal.EditorAssetLibrary.rename_asset(a, new)
                rep['renamed'] = new
    unreal.EditorAssetLibrary.save_directory(DEST)
    rep['final'] = {a: unreal.EditorAssetLibrary.load_asset(a).get_class().get_name()
                    for a in unreal.EditorAssetLibrary.list_assets(DEST, recursive=True)}
except Exception as e:  # noqa: BLE001
    import traceback
    rep['exception'] = traceback.format_exc()
json.dump(rep, open(os.path.join(HERE, 'import_standins.json'), 'w'), indent=1)
unreal.log_warning('[STANDINS] ' + json.dumps(rep))
