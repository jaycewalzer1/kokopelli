using System.IO;
using UnrealBuildTool;

public class SimCV : ModuleRules
{
	public SimCV(ReadOnlyTargetRules Target) : base(Target)
	{
		PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;

		// Command files live in Private/Commands and include Private/*.h.
		PrivateIncludePaths.Add(Path.Combine(ModuleDirectory, "Private"));

		PublicDependencyModuleNames.AddRange(new string[]
		{
			"Core",
			"CoreUObject",
			"Engine",
			"DeveloperSettings",
		});

		PrivateDependencyModuleNames.AddRange(new string[]
		{
			"Sockets",
			"Networking",
			"ImageWrapper",
			"Json",
			"RenderCore",
		});

		// Stage the class-path redirect table into packaged builds (read via FPaths::ProjectConfigDir()).
		RuntimeDependencies.Add("$(ProjectDir)/Config/SimCVRedirects.json", StagedFileType.UFS);
	}
}
