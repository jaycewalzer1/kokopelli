#pragma once

#include "CoreMinimal.h"

class FSimCVCommandRouter;

namespace SimCV
{
	void RegisterPluginCommands(FSimCVCommandRouter& Router);
	void RegisterObjectCommands(FSimCVCommandRouter& Router);
	void RegisterActionCommands(FSimCVCommandRouter& Router);
	void RegisterCameraCommands(FSimCVCommandRouter& Router);
	void RegisterBlueprintCommands(FSimCVCommandRouter& Router);
}
