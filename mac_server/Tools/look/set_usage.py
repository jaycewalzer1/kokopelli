"""One-off: set the instanced-mesh usage flag on existing Solarpunk materials and save them."""
import unreal

# Commandlets don't scan content up front.
unreal.AssetRegistryHelpers.get_asset_registry().scan_paths_synchronous(['/Game/Solarpunk'], True)
assets = unreal.EditorAssetLibrary.list_assets('/Game/Solarpunk/Materials', recursive=False)
unreal.log_warning(f'[SP] {len(assets)} assets')

for asset in assets:
    mat = unreal.load_asset(asset)
    if isinstance(mat, unreal.Material):
        mat.set_editor_property('used_with_instanced_static_meshes', True)
        unreal.MaterialEditingLibrary.recompile_material(mat)
        unreal.EditorAssetLibrary.save_loaded_asset(mat)
        unreal.log_warning(f'[SP] usage flag set: {asset}')
