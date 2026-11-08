using UnrealBuildTool;
public class MHLocal : ModuleRules
{
	public MHLocal(ReadOnlyTargetRules Target) : base(Target)
	{
		PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;
		PublicDependencyModuleNames.AddRange(new string[] { "Core", "CoreUObject", "Engine", "RHI", "RenderCore" });
		PrivateDependencyModuleNames.AddRange(new string[] {
			"UnrealEd", "MetaHumanCharacter", "MetaHumanCharacterEditor", "MetaHumanCoreTechLib", "RigLogicModule", "RigLogicLib", "MetaHumanCharacterPalette", "MetaHumanDefaultEditorPipeline", "MetaHumanSDKRuntime", "Blutility", "ControlRig", "DataflowCore", "DataflowEngine", "RigVM"
		});
	}
}
