#pragma once

#include "CoreMinimal.h"
#include "Containers/Queue.h"
#include "HAL/Runnable.h"

#include <atomic>

class FRunnableThread;
class FSocket;

/** One accepted client. Read by the server thread, written by the game thread (SendFrame). */
class FSimCVConnection
{
public:
	FSimCVConnection(FSocket* InSocket, uint32 InId, const FString& InPeer);
	~FSimCVConnection();

	/** Thread-safe. Wraps Payload in the UnrealCV header: uint32 magic 0x9E2B83C1, uint32 size. */
	bool SendFrame(const TArray<uint8>& Payload);
	void Close();
	bool IsOpen() const { return bOpen.load(); }
	FSocket* GetSocket() const { return Socket; }

	const uint32 Id;
	const FString Peer;

private:
	bool SendAll(const uint8* Data, int32 Count);

	FSocket* Socket;
	FCriticalSection SendLock;
	std::atomic<bool> bOpen{true};
};

using FSimCVConnectionPtr = TSharedPtr<FSimCVConnection, ESPMode::ThreadSafe>;

struct FSimCVRequest
{
	FSimCVConnectionPtr Connection;
	uint64 RequestId = 0;
	FString Message;
};

/**
 * Background accept/read loop. Like UnrealCV, serves one client at a time and closes
 * concurrent connection attempts without a banner; the next client is accepted after
 * the current one disconnects. Parsed requests go to a queue drained on the game thread.
 */
class FSimCVServer final : public FRunnable
{
public:
	FSimCVServer(const FString& InBindAddress, int32 InPort, const FString& InBanner);
	virtual ~FSimCVServer() override;

	bool Start();
	void Shutdown();

	bool Dequeue(FSimCVRequest& Out) { return Requests.Dequeue(Out); }
	bool IsListening() const { return Listener != nullptr; }
	bool HasClient() const { return bHasClient.load(); }

	virtual uint32 Run() override;
	virtual void Stop() override { bStopping = true; }

private:
	void AcceptClient();
	void RejectPendingClients();
	bool PumpClient();
	bool ParseFrames();
	void HandlePayload(const uint8* Data, int32 Size);
	void DropClient();

	FString BindAddress;
	int32 Port;
	FString Banner;

	FSocket* Listener = nullptr;
	FRunnableThread* Thread = nullptr;
	std::atomic<bool> bStopping{false};
	std::atomic<bool> bHasClient{false};

	// Server-thread only.
	FSimCVConnectionPtr Client;
	uint32 NextConnectionId = 1;
	TArray<uint8> RecvBuffer;
	TArray<uint8> Scratch;

	TQueue<FSimCVRequest, EQueueMode::Spsc> Requests;
};
