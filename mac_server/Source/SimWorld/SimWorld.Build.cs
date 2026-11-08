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
			"AnimationCore", // two-bone IK for the body animation
			"HairStrandsCore", // Bodies.json grooms (UGroomComponent); the HairStrands plugin is enabled in the .uproject
			// City (docs/CITY.md): runtime static meshes + frame timing
			"MeshDescription",
			"StaticMeshDescription",
			"RenderCore",
			"RHI",
			"InputCore", // EKeys for SWPlayerController's fly/walk keys
			"Slate", "SlateCore", // SWindow::Minimize (resting the window stops the Metal present leak)
		});

		// Bodies (city/bodies): Config/Bodies.json is read with a plain file load, so stage it loose (editable next to the app).
		RuntimeDependencies.Add("$(ProjectDir)/Config/Bodies.json", StagedFileType.NonUFS);

		if (Target.Platform == UnrealTargetPlatform.Mac)
		{
			// The launcher-installed 5.8 engine does not stage oneTBB, but the game binary links it via
			// @rpath (.../Engine/Source/ThirdParty/Intel/TBB/Deploy/.../Mac/lib), so a packaged app fails at launch without this.
			string TbbLib = "$(EngineDir)/Source/ThirdParty/Intel/TBB/Deploy/oneTBB-2022.3.0/Mac/lib";
			RuntimeDependencies.Add(TbbLib + "/libtbb.12.dylib", StagedFileType.NonUFS);
			RuntimeDependencies.Add(TbbLib + "/libtbbmalloc.2.dylib", StagedFileType.NonUFS);
		}
	}
}
