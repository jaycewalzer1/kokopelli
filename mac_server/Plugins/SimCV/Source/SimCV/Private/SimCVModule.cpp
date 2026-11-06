#include "SimCVModule.h"

#include "CoreGlobals.h"
#include "Misc/App.h"
#include "Misc/CommandLine.h"
#include "Misc/Optional.h"
#include "Misc/Parse.h"
#include "Modules/ModuleManager.h"
#include "SimCVCommands.h"
#include "SimCVLog.h"
#include "SimCVServer.h"
#include "SimCVSettings.h"
#include "SimCVWorld.h"

DEFINE_LOG_CATEGORY(LogSimCV);

IMPLEMENT_MODULE(FSimCVModule, SimCV)

namespace
{
constexpr double PendingTimeoutSeconds = 120.0;

/** "vbatch N": the next N requests run back-to-back in one frame (UnrealCV semantics). */
bool ParseBatchHeader(const FString& Message, int32& OutCount)
{
	if (!Message.StartsWith(TEXT("vbatch")))
	{
		return false;
	}
	OutCount = FCString::Atoi(*Message.Mid(6).TrimStartAndEnd());
	return true;
}
}

struct FSimCVPump
{
	struct FInFlight
	{
		FSimCVRequest Request;
		FSimCVReply Reply;
		double StartTime = 0.0;
	};

	TUniquePtr<FSimCVServer> Server;
	TOptional<FInFlight> InFlight;
	TArray<FSimCVRequest> Ready;
	TArray<FSimCVRequest> Batch;
	int32 BatchRemaining = 0;
	uint32 BatchConnectionId = 0;
};

FSimCVModule::FSimCVModule() = default;
FSimCVModule::~FSimCVModule() = default;

FSimCVModule& FSimCVModule::Get()
{
	return FModuleManager::LoadModuleChecked<FSimCVModule>(TEXT("SimCV"));
}

bool FSimCVModule::IsAvailable()
{
	return FModuleManager::Get().IsModuleLoaded(TEXT("SimCV"));
}

bool FSimCVModule::IsListening() const
{
	return Pump && Pump->Server && Pump->Server->IsListening();
}

bool FSimCVModule::HasClient() const
{
	return Pump && Pump->Server && Pump->Server->HasClient();
}

void FSimCVModule::StartupModule()
{
	Pump = MakeUnique<FSimCVPump>();

	SimCV::RegisterPluginCommands(Router);
	SimCV::RegisterObjectCommands(Router);
	SimCV::RegisterActionCommands(Router);
	SimCV::RegisterCameraCommands(Router);
	SimCV::RegisterBlueprintCommands(Router);
	SimCV::InitStepping();

	if (IsRunningCommandlet() || FParse::Param(FCommandLine::Get(), TEXT("nosimcv")))
	{
		return; // never open a port while cooking etc.
	}
	// The server starts on the first tick, once config and the engine are fully up.
	TickHandle = FTSTicker::GetCoreTicker().AddTicker(FTickerDelegate::CreateRaw(this, &FSimCVModule::Tick), 0.0f);
}

void FSimCVModule::ShutdownModule()
{
	FTSTicker::GetCoreTicker().RemoveTicker(TickHandle);
	SimCV::ShutdownStepping();
	if (Pump)
	{
		Pump->InFlight.Reset();
		Pump->Ready.Reset();
		Pump->Batch.Reset();
		Pump->Server.Reset(); // joins the server thread
	}
	Pump.Reset();
}

void FSimCVModule::StartServer()
{
	const USimCVSettings* Settings = GetDefault<USimCVSettings>();
	Port = Settings->Port;
	if (!FParse::Value(FCommandLine::Get(), TEXT("cvport="), Port))
	{
		FParse::Value(FCommandLine::Get(), TEXT("UnrealCVPort="), Port);
	}
	FString BindAddress = Settings->BindAddress;
	FParse::Value(FCommandLine::Get(), TEXT("cvbind="), BindAddress);

	SimCV::LoadRedirects();

	// The client only checks that the banner starts with "connected".
	const FString Banner = FString::Printf(TEXT("connected to %s"), FApp::GetProjectName());
	Pump->Server = MakeUnique<FSimCVServer>(BindAddress, Port, Banner);
	if (!Pump->Server->Start())
	{
		Pump->Server.Reset();
	}
}

bool FSimCVModule::Tick(float DeltaTime)
{
	if (!bServerStartAttempted)
	{
		bServerStartAttempted = true;
		StartServer();
	}

	FSimCVPump& P = *Pump;
	if (!P.Server)
	{
		return true;
	}

	const USimCVSettings* Settings = GetDefault<USimCVSettings>();
	const double Deadline = FPlatformTime::Seconds() + Settings->TickBudgetMs / 1000.0;
	int32 Processed = 0;

	for (;;)
	{
		if (P.InFlight.IsSet())
		{
			FSimCVReply Result;
			if (!P.InFlight->Reply.Poll(Result))
			{
				if (FPlatformTime::Seconds() - P.InFlight->StartTime < PendingTimeoutSeconds)
				{
					return true; // everything behind it waits: replies must stay in order
				}
				Result = FSimCVReply::Error(TEXT("Timed out waiting for the command to finish"));
			}
			SendReply(P.InFlight->Request, Result);
			P.InFlight.Reset();
		}

		FSimCVRequest Request;
		if (P.Ready.Num() > 0)
		{
			// A completed vbatch: run all of it in this frame, ignoring the budget.
			Request = MoveTemp(P.Ready[0]);
			P.Ready.RemoveAt(0);
		}
		else
		{
			if (Processed >= Settings->MaxRequestsPerTick || FPlatformTime::Seconds() > Deadline)
			{
				break;
			}
			if (!P.Server->Dequeue(Request))
			{
				break;
			}

			if (P.BatchRemaining > 0 && Request.Connection->Id != P.BatchConnectionId)
			{
				P.Batch.Reset(); // the batching client went away mid-batch
				P.BatchRemaining = 0;
			}
			if (P.BatchRemaining > 0)
			{
				P.Batch.Add(MoveTemp(Request));
				if (--P.BatchRemaining == 0)
				{
					P.Ready = MoveTemp(P.Batch);
					P.Batch.Reset();
				}
				continue;
			}
			int32 BatchCount = 0;
			if (ParseBatchHeader(Request.Message, BatchCount))
			{
				SendReply(Request, FSimCVReply::Ok());
				P.BatchRemaining = FMath::Max(0, BatchCount);
				P.BatchConnectionId = Request.Connection->Id;
				continue;
			}
		}

		if (!Request.Connection->IsOpen())
		{
			continue;
		}

		++Processed;
		UE_LOG(LogSimCV, Verbose, TEXT("%llu: %s"), Request.RequestId, *Request.Message);
		FSimCVReply Reply = Router.Execute(Request.Message);
		if (Reply.Kind == FSimCVReply::EKind::Pending)
		{
			P.InFlight.Emplace(FSimCVPump::FInFlight{MoveTemp(Request), MoveTemp(Reply), FPlatformTime::Seconds()});
			continue;
		}
		SendReply(Request, Reply);
	}
	return true;
}

void FSimCVModule::SendReply(const FSimCVRequest& Request, const FSimCVReply& Reply) const
{
	const FTCHARToUTF8 Header(*FString::Printf(TEXT("%llu:"), Request.RequestId));
	TArray<uint8> Payload;
	Payload.Reserve(Header.Length() + (Reply.Kind == FSimCVReply::EKind::Binary ? Reply.Bytes.Num() : Reply.Text.Len() + 8));
	Payload.Append(reinterpret_cast<const uint8*>(Header.Get()), Header.Length());
	Reply.AppendPayload(Payload);
	Request.Connection->SendFrame(Payload);
}
