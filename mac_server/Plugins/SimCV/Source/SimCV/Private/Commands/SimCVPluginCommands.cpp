#include "SimCVCommands.h"

#include "Engine/World.h"
#include "SimCVCommandRouter.h"
#include "SimCVModule.h"
#include "SimCVWorld.h"

namespace
{
// The python client parses digits only; >= 1.1.0 enables its command capability check.
const TCHAR* SimCVServerVersion = TEXT("1.1.0-simcv");
}

void SimCV::RegisterPluginCommands(FSimCVCommandRouter& Router)
{
	// Probed by unrealcv.Client.connect(); one template per line, must include itself.
	Router.Register(TEXT("vget /unrealcv/commands"), [&Router](const FSimCVArgs&)
	{
		return FSimCVReply::Ok(FString::Join(Router.GetClientTemplates(), TEXT("\n")));
	}, TEXT("List supported command templates"));

	Router.Register(TEXT("vget /unrealcv/help"), [&Router](const FSimCVArgs&)
	{
		FString Text;
		for (const TPair<FString, FString>& Entry : Router.GetHelp())
		{
			Text += Entry.Key + TEXT("\n") + Entry.Value + TEXT("\n");
		}
		return FSimCVReply::Ok(Text);
	}, TEXT("List commands with descriptions"));

	Router.Register(TEXT("vget /unrealcv/version"), [](const FSimCVArgs&)
	{
		return FSimCVReply::Ok(SimCVServerVersion);
	}, TEXT("Server version"));

	Router.Register(TEXT("vget /unrealcv/status"), [](const FSimCVArgs&)
	{
		const FSimCVModule& Module = FSimCVModule::Get();
		FString Text;
		Text += Module.IsListening() ? TEXT("Is Listening\n") : TEXT("Not Listening\n");
		Text += Module.HasClient() ? TEXT("Client Connected\n") : TEXT("No Client Connected\n");
		Text += FString::Printf(TEXT("%d\n"), Module.GetPort());
		Text += TEXT("Configuration\n");
		Text += FString::Printf(TEXT("Port: %d\n"), Module.GetPort());
		return FSimCVReply::Ok(Text);
	}, TEXT("Server status"));

	Router.Register(TEXT("vget /unrealcv/echo [str]"), [](const FSimCVArgs& Args)
	{
		return FSimCVReply::Ok(Args[0]);
	}, TEXT("Echo the argument"));

	auto LevelName = [](const FSimCVArgs&)
	{
		UWorld* World = GetWorld();
		if (!World)
		{
			return FSimCVReply::Error(TEXT("No valid world"));
		}
		return FSimCVReply::Ok(UWorld::RemovePIEPrefix(World->GetMapName()));
	};
	Router.Register(TEXT("vget /scene/name"), LevelName, TEXT("Current map name"));
	Router.Register(TEXT("vget /level/name"), LevelName, TEXT("Current map name"));

	// Intercepted by the request pump before routing; registered so it is advertised to the client.
	Router.Register(TEXT("vbatch [uint]"), [](const FSimCVArgs&)
	{
		return FSimCVReply::Ok();
	}, TEXT("Run the next N requests in the same frame"));
}
