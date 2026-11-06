using UnrealBuildTool;

public class SimWorld : ModuleRules
{
	public SimWorld(ReadOnlyTargetRules Target) : base(Target)
	{
		PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;

		PublicDependencyModuleNames.AddRange(new string[] { "Core", "CoreUObject", "Engine" });

		// Game classes register extra commands / expose UFUNCTIONs for vbp through SimCV.
		PrivateDependencyModuleNames.Add("SimCV");
	}
}
