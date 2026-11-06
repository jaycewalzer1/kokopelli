#pragma once

#include "CoreMinimal.h"
#include "Containers/Ticker.h"
#include "Modules/ModuleInterface.h"
#include "SimCVCommandRouter.h"

struct FSimCVPump;
struct FSimCVRequest;

/**
 * Owns the TCP server and the command router. Game modules add commands with
 *   FSimCVModule::Get().GetRouter().Register(TEXT("vget /my/thing [str]"), Handler);
 */
class SIMCV_API FSimCVModule : public IModuleInterface
{
public:
	FSimCVModule();
	virtual ~FSimCVModule() override;

	static FSimCVModule& Get();
	static bool IsAvailable();

	FSimCVCommandRouter& GetRouter() { return Router; }
	int32 GetPort() const { return Port; }
	bool IsListening() const;
	bool HasClient() const;

	virtual void StartupModule() override;
	virtual void ShutdownModule() override;

private:
	bool Tick(float DeltaTime);
	void StartServer();
	void SendReply(const FSimCVRequest& Request, const FSimCVReply& Reply) const;

	FSimCVCommandRouter Router;
	TUniquePtr<FSimCVPump> Pump;
	FTSTicker::FDelegateHandle TickHandle;
	int32 Port = 9000;
	bool bServerStartAttempted = false;
};
