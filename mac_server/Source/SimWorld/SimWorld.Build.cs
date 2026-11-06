using System.IO;
using UnrealBuildTool;

public class SimWorld : ModuleRules
{
	public SimWorld(ReadOnlyTargetRules Target) : base(Target)
	{
		PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;

		PrivateIncludePaths.Add(Path.Combine(ModuleDirectory, "Private"));

		PublicDependencyModuleNames.AddRange(new string[]
		{
			"Core",
			"CoreUObject",
			"Engine",
			"DeveloperSettings", // USWSettings
		});

		PrivateDependencyModuleNames.AddRange(new string[]
		{
			// Cameras (USimCVCameraComponent), settings, and exact-key vbp routes registered on its router.
			"SimCV",
			"Json",
			// City (docs/CITY.md): runtime static meshes + frame timing
			"MeshDescription",
			"StaticMeshDescription",
			"RenderCore",
			"RHI",
		});
	}
}
