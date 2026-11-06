#include "SimCVServer.h"

#include "Common/TcpSocketBuilder.h"
#include "HAL/PlatformProcess.h"
#include "HAL/RunnableThread.h"
#include "Interfaces/IPv4/IPv4Address.h"
#include "Interfaces/IPv4/IPv4Endpoint.h"
#include "SimCVLog.h"
#include "Sockets.h"
#include "SocketSubsystem.h"

namespace
{
constexpr uint32 SimCVMagic = 0x9E2B83C1; // FNFSMessageHeader magic, same as the python client
constexpr uint32 MaxPayloadBytes = 64u << 20;
constexpr int32 RecvChunkBytes = 64 << 10;

ISocketSubsystem* SocketSubsystem()
{
	return ISocketSubsystem::Get(PLATFORM_SOCKETSUBSYSTEM);
}

void DestroySocket(FSocket* Socket)
{
	if (Socket)
	{
		Socket->Close();
		SocketSubsystem()->DestroySocket(Socket);
	}
}

TArray<uint8> ToUtf8(const FString& Text)
{
	const FTCHARToUTF8 Utf8(*Text);
	return TArray<uint8>(reinterpret_cast<const uint8*>(Utf8.Get()), Utf8.Length());
}
}

// ---------------------------------------------------------------------------
// Connection

FSimCVConnection::FSimCVConnection(FSocket* InSocket, uint32 InId, const FString& InPeer)
	: Id(InId)
	, Peer(InPeer)
	, Socket(InSocket)
{
}

FSimCVConnection::~FSimCVConnection()
{
	Close();
	DestroySocket(Socket);
}

void FSimCVConnection::Close()
{
	// No lock: shutting the socket down is what unblocks a Send stuck on a dead peer.
	if (bOpen.exchange(false) && Socket)
	{
		Socket->Shutdown(ESocketShutdownMode::ReadWrite);
	}
}

bool FSimCVConnection::SendFrame(const TArray<uint8>& Payload)
{
	FScopeLock Lock(&SendLock);
	if (!bOpen.load())
	{
		return false;
	}

	// Native little-endian uint32s, matching struct.pack('I', ...) on the (arm64/x64) client.
	const uint32 Header[2] = {SimCVMagic, static_cast<uint32>(Payload.Num())};
	if (!SendAll(reinterpret_cast<const uint8*>(Header), sizeof(Header)) || !SendAll(Payload.GetData(), Payload.Num()))
	{
		UE_LOG(LogSimCV, Warning, TEXT("Send to %s failed; closing connection"), *Peer);
		Close();
		return false;
	}
	return true;
}

bool FSimCVConnection::SendAll(const uint8* Data, int32 Count)
{
	int32 Sent = 0;
	while (Sent < Count)
	{
		int32 Chunk = 0;
		if (!Socket->Send(Data + Sent, Count - Sent, Chunk))
		{
			return false;
		}
		if (Chunk <= 0)
		{
			if (!bOpen.load() || !Socket->Wait(ESocketWaitConditions::WaitForWrite, FTimespan::FromSeconds(5)))
			{
				return false;
			}
			continue;
		}
		Sent += Chunk;
	}
	return true;
}

// ---------------------------------------------------------------------------
// Server

FSimCVServer::FSimCVServer(const FString& InBindAddress, int32 InPort, const FString& InBanner)
	: BindAddress(InBindAddress)
	, Port(InPort)
	, Banner(InBanner)
{
	Scratch.SetNumUninitialized(RecvChunkBytes);
}

FSimCVServer::~FSimCVServer()
{
	Shutdown();
}

bool FSimCVServer::Start()
{
	FIPv4Address Address;
	if (!FIPv4Address::Parse(BindAddress, Address))
	{
		UE_LOG(LogSimCV, Warning, TEXT("Bad bind address '%s', using 127.0.0.1"), *BindAddress);
		Address = FIPv4Address::InternalLoopback;
	}

	Listener = FTcpSocketBuilder(TEXT("SimCVListener"))
		.AsReusable()
		.BoundToEndpoint(FIPv4Endpoint(Address, Port))
		.Listening(8)
		.Build();
	if (!Listener)
	{
		UE_LOG(LogSimCV, Error, TEXT("Could not listen on %s:%d (port in use?)"), *Address.ToString(), Port);
		return false;
	}

	Thread = FRunnableThread::Create(this, TEXT("SimCVServer"));
	if (!Thread)
	{
		DestroySocket(Listener);
		Listener = nullptr;
		return false;
	}
	UE_LOG(LogSimCV, Display, TEXT("Listening on %s:%d"), *Address.ToString(), Port);
	return true;
}

void FSimCVServer::Shutdown()
{
	if (Thread)
	{
		Thread->Kill(true); // calls Stop(), waits for Run() to return
		delete Thread;
		Thread = nullptr;
	}
	DestroySocket(Listener);
	Listener = nullptr;
}

uint32 FSimCVServer::Run()
{
	while (!bStopping.load())
	{
		if (!Client.IsValid())
		{
			bool bPending = false;
			if (!Listener->WaitForPendingConnection(bPending, FTimespan::FromMilliseconds(100)))
			{
				FPlatformProcess::Sleep(0.1f);
				continue;
			}
			if (bPending)
			{
				AcceptClient();
			}
			continue;
		}

		RejectPendingClients();
		if (!PumpClient())
		{
			DropClient();
		}
	}
	DropClient();
	return 0;
}

void FSimCVServer::AcceptClient()
{
	FSocket* Socket = Listener->Accept(TEXT("SimCVClient"));
	if (!Socket)
	{
		return;
	}
	// macOS accept() inherits O_NONBLOCK from the (non-blocking) listener; we want blocking + Wait().
	Socket->SetNonBlocking(false);
	Socket->SetNoDelay(true);
	int32 ActualSize = 0;
	Socket->SetSendBufferSize(4 << 20, ActualSize);

	TSharedRef<FInternetAddr> PeerAddr = SocketSubsystem()->CreateInternetAddr();
	Socket->GetPeerAddress(*PeerAddr);

	FSimCVConnectionPtr Connection = MakeShared<FSimCVConnection, ESPMode::ThreadSafe>(Socket, NextConnectionId++, PeerAddr->ToString(true));
	if (!Connection->SendFrame(ToUtf8(Banner)))
	{
		return; // destructor destroys the socket
	}

	RecvBuffer.Reset();
	Client = Connection;
	bHasClient = true;
	UE_LOG(LogSimCV, Display, TEXT("Client %s connected"), *Client->Peer);
}

void FSimCVServer::RejectPendingClients()
{
	bool bPending = false;
	while (Listener->HasPendingConnection(bPending) && bPending)
	{
		bPending = false;
		FSocket* Extra = Listener->Accept(TEXT("SimCVRejected"));
		if (!Extra)
		{
			break;
		}
		UE_LOG(LogSimCV, Warning, TEXT("Rejected a second client: only one connection at a time"));
		DestroySocket(Extra);
	}
}

bool FSimCVServer::PumpClient()
{
	if (!Client->IsOpen())
	{
		return false;
	}

	FSocket* Socket = Client->GetSocket();
	if (!Socket->Wait(ESocketWaitConditions::WaitForRead, FTimespan::FromMilliseconds(50)))
	{
		return Socket->GetConnectionState() != SCS_ConnectionError;
	}

	int32 BytesRead = 0;
	if (!Socket->Recv(Scratch.GetData(), Scratch.Num(), BytesRead) || BytesRead <= 0)
	{
		return false; // readable with no data == orderly close
	}
	RecvBuffer.Append(Scratch.GetData(), BytesRead);
	return ParseFrames();
}

bool FSimCVServer::ParseFrames()
{
	int32 Offset = 0;
	while (RecvBuffer.Num() - Offset >= 8)
	{
		uint32 Header[2];
		FMemory::Memcpy(Header, RecvBuffer.GetData() + Offset, sizeof(Header));
		if (Header[0] != SimCVMagic)
		{
			UE_LOG(LogSimCV, Error, TEXT("Bad frame magic 0x%08X from %s"), Header[0], *Client->Peer);
			return false;
		}
		if (Header[1] > MaxPayloadBytes)
		{
			UE_LOG(LogSimCV, Error, TEXT("Frame of %u bytes exceeds limit"), Header[1]);
			return false;
		}
		const int32 Size = static_cast<int32>(Header[1]);
		if (RecvBuffer.Num() - Offset - 8 < Size)
		{
			break;
		}
		HandlePayload(RecvBuffer.GetData() + Offset + 8, Size);
		Offset += 8 + Size;
	}
	if (Offset > 0)
	{
		RecvBuffer.RemoveAt(0, Offset);
	}
	return true;
}

void FSimCVServer::HandlePayload(const uint8* Data, int32 Size)
{
	const FUTF8ToTCHAR Converted(reinterpret_cast<const ANSICHAR*>(Data), Size);
	const FString Raw(FStringView(Converted.Get(), Converted.Length()));

	// "<digits>:<command>" — the client counts replies, so the id must be echoed back verbatim.
	int32 Colon = INDEX_NONE;
	bool bValid = Raw.FindChar(TEXT(':'), Colon) && Colon > 0;
	for (int32 Index = 0; bValid && Index < Colon; ++Index)
	{
		bValid = FChar::IsDigit(Raw[Index]);
	}
	if (!bValid)
	{
		UE_LOG(LogSimCV, Warning, TEXT("Malformed request (no id prefix), dropped: '%s'"), *Raw.Left(200));
		return;
	}

	FSimCVRequest Request;
	Request.Connection = Client;
	Request.RequestId = FCString::Strtoui64(*Raw.Left(Colon), nullptr, 10);
	Request.Message = Raw.Mid(Colon + 1);
	Requests.Enqueue(MoveTemp(Request));
}

void FSimCVServer::DropClient()
{
	if (Client.IsValid())
	{
		UE_LOG(LogSimCV, Display, TEXT("Client %s disconnected"), *Client->Peer);
		Client->Close();
		Client.Reset(); // queued requests keep their own reference; the game thread skips closed ones
	}
	bHasClient = false;
	RecvBuffer.Reset();
}
