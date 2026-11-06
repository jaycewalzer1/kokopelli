#include "SimCVCommands.h"

#include "Engine/World.h"
#include "GameFramework/Pawn.h"
#include "GameFramework/PlayerController.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "SimCVCameraActor.h"
#include "SimCVCameraComponent.h"
#include "SimCVCommandRouter.h"
#include "SimCVImageEncode.h"
#include "SimCVSettings.h"
#include "SimCVWorld.h"

namespace
{
using namespace SimCV;

enum class EOutput : uint8 { Png, Bmp, Npy, Invalid };

/** UnrealCV rule: a bare "png"/"bmp"/"npy" means return bytes; anything with a '.' is a file path. */
EOutput ParseOutput(const FString& Arg, bool& bOutToFile)
{
	int32 Dot = INDEX_NONE;
	bOutToFile = Arg.FindChar(TEXT('.'), Dot);
	const FString Ext = (bOutToFile ? FPaths::GetExtension(Arg) : Arg).ToLower();
	if (Ext == TEXT("png")) { return EOutput::Png; }
	if (Ext == TEXT("bmp")) { return EOutput::Bmp; }
	if (Ext == TEXT("npy")) { return EOutput::Npy; }
	return EOutput::Invalid;
}

FSimCVReply InvalidOutput(const FString& Arg)
{
	return FSimCVReply::Error(FString::Printf(TEXT("Invalid filename type, filename %s"), *Arg));
}

/** Bytes back to the client, or written to Path with the path as the reply. */
FSimCVReply Deliver(TArray<uint8>&& Bytes, bool bToFile, const FString& Path)
{
	if (!bToFile)
	{
		return FSimCVReply::Binary(MoveTemp(Bytes));
	}
	if (!FFileHelper::SaveArrayToFile(Bytes, *Path))
	{
		return FSimCVReply::Error(FString::Printf(TEXT("Can not save file %s"), *Path));
	}
	return FSimCVReply::Ok(Path);
}

FSimCVReply DeliverColor(const TArray<FColor>& Pixels, int32 Width, int32 Height, const FString& Arg)
{
	bool bToFile = false;
	TArray<uint8> Bytes;
	switch (ParseOutput(Arg, bToFile))
	{
	case EOutput::Png:
		if (!EncodePng(Pixels, Width, Height, Bytes))
		{
			return FSimCVReply::Error(TEXT("PNG encoding failed"));
		}
		break;
	case EOutput::Bmp:
		EncodeBmp(Pixels, Width, Height, Bytes);
		break;
	default:
		return InvalidOutput(Arg); // colour data has no npy form in UnrealCV
	}
	return Deliver(MoveTemp(Bytes), bToFile, Arg);
}

FSimCVReply DeliverFloat(const TArray<float>& Values, int32 Width, int32 Height, const FString& Arg)
{
	bool bToFile = false;
	if (ParseOutput(Arg, bToFile) != EOutput::Npy)
	{
		return InvalidOutput(Arg); // depth is npy only, as in UnrealCV
	}
	TArray<uint8> Bytes;
	EncodeNpyFloat32(Values, Width, Height, 1, Bytes);
	return Deliver(MoveTemp(Bytes), bToFile, Arg);
}

USimCVCameraComponent* CameraById(const FString& Id, FSimCVReply& OutError)
{
	UWorld* World = GetWorld();
	const TArray<USimCVCameraComponent*> Cameras = GetCameras(World);
	const int32 Index = FCString::Atoi(*Id);
	if (!World || !Cameras.IsValidIndex(Index))
	{
		OutError = FSimCVReply::Error(TEXT("Invalid sensor id"));
		return nullptr;
	}
	USimCVCameraComponent* Camera = Cameras[Index];
	if (Camera->bFollowPlayerView)
	{
		Camera->SyncToPlayerView();
	}
	return Camera;
}

void RegisterCameraCommand(FSimCVCommandRouter& Router, const FString& Template,
	TFunction<FSimCVReply(USimCVCameraComponent*, const FSimCVArgs&)> Body, const FString& Help)
{
	Router.Register(Template, [Body = MoveTemp(Body)](const FSimCVArgs& Args)
	{
		FSimCVReply Error;
		USimCVCameraComponent* Camera = CameraById(Args[0], Error);
		return Camera ? Body(Camera, Args) : Error;
	}, Help);
}
}

void SimCV::RegisterCameraCommands(FSimCVCommandRouter& Router)
{
	Router.Register(TEXT("vget /cameras"), [](const FSimCVArgs&)
	{
		FString List;
		for (const USimCVCameraComponent* Camera : GetCameras(GetWorld()))
		{
			List += Camera->GetName() + TEXT(" ");
		}
		return FSimCVReply::Ok(List);
	}, TEXT("Camera component names in id order"));

	Router.Register(TEXT("vset /cameras/spawn"), [](const FSimCVArgs&)
	{
		UWorld* World = GetWorld();
		ASimCVCameraActor* Actor = World ? World->SpawnActor<ASimCVCameraActor>() : nullptr;
		if (!Actor)
		{
			return FSimCVReply::Error(TEXT("Failed to spawn actor"));
		}
		const USimCVSettings* Settings = GetDefault<USimCVSettings>();
		Actor->Camera->FOVAngle = Settings->DefaultFOV;
		Actor->Camera->SetFilmSize(Settings->DefaultWidth, Settings->DefaultHeight);
		return FSimCVReply::Ok(Actor->GetName());
	}, TEXT("Spawn a free camera; returns its actor name"));

	RegisterCameraCommand(Router, TEXT("vget /camera/[uint]/location"), [](USimCVCameraComponent* Camera, const FSimCVArgs&)
	{
		return FSimCVReply::Ok(FormatVector(Camera->GetComponentLocation()));
	}, TEXT("Camera location x y z (cm)"));

	RegisterCameraCommand(Router, TEXT("vset /camera/[uint]/location [float] [float] [float]"), [](USimCVCameraComponent* Camera, const FSimCVArgs& Args)
	{
		const FVector Location = VectorFromArgs(Args, 1);
		if (Camera->bFollowPlayerView)
		{
			// UnrealCV moves the player pawn for camera 0.
			APlayerController* PC = GetPlayerController(Camera->GetWorld());
			if (APawn* Pawn = PC ? PC->GetPawn() : nullptr)
			{
				Pawn->SetActorLocation(Location, false, nullptr, ETeleportType::TeleportPhysics);
				return FSimCVReply::Ok();
			}
			Camera->bFollowPlayerView = false; // no pawn: detach and move the camera itself
		}
		Camera->SetWorldLocation(Location);
		return FSimCVReply::Ok();
	}, TEXT("Set camera location x y z (cm); camera 0 moves the player pawn"));

	RegisterCameraCommand(Router, TEXT("vget /camera/[uint]/rotation"), [](USimCVCameraComponent* Camera, const FSimCVArgs&)
	{
		return FSimCVReply::Ok(FormatRotator(Camera->GetComponentRotation()));
	}, TEXT("Camera rotation pitch yaw roll (degrees)"));

	RegisterCameraCommand(Router, TEXT("vset /camera/[uint]/rotation [float] [float] [float]"), [](USimCVCameraComponent* Camera, const FSimCVArgs& Args)
	{
		const FVector PYR = VectorFromArgs(Args, 1);
		const FRotator Rotation(PYR.X, PYR.Y, PYR.Z);
		if (Camera->bFollowPlayerView)
		{
			if (APlayerController* PC = GetPlayerController(Camera->GetWorld()))
			{
				PC->SetControlRotation(Rotation);
				Camera->SyncToPlayerView();
				return FSimCVReply::Ok();
			}
			Camera->bFollowPlayerView = false;
		}
		Camera->SetWorldRotation(Rotation);
		return FSimCVReply::Ok();
	}, TEXT("Set camera rotation pitch yaw roll; camera 0 sets the control rotation"));

	RegisterCameraCommand(Router, TEXT("vget /camera/[uint]/fov"), [](USimCVCameraComponent* Camera, const FSimCVArgs&)
	{
		return FSimCVReply::Ok(FString::Printf(TEXT("%f"), Camera->FOVAngle));
	}, TEXT("Horizontal field of view (degrees)"));

	RegisterCameraCommand(Router, TEXT("vset /camera/[uint]/fov [float]"), [](USimCVCameraComponent* Camera, const FSimCVArgs& Args)
	{
		Camera->FOVAngle = FMath::Clamp(FCString::Atof(*Args[1]), 1.f, 170.f);
		return FSimCVReply::Ok();
	}, TEXT("Set horizontal field of view (degrees)"));

	RegisterCameraCommand(Router, TEXT("vget /camera/[uint]/size"), [](USimCVCameraComponent* Camera, const FSimCVArgs&)
	{
		return FSimCVReply::Ok(FString::Printf(TEXT("%d %d"), Camera->GetFilmWidth(), Camera->GetFilmHeight()));
	}, TEXT("Capture resolution: width height"));

	RegisterCameraCommand(Router, TEXT("vset /camera/[uint]/size [uint] [uint]"), [](USimCVCameraComponent* Camera, const FSimCVArgs& Args)
	{
		Camera->SetFilmSize(FCString::Atoi(*Args[1]), FCString::Atoi(*Args[2]));
		return FSimCVReply::Ok();
	}, TEXT("Set capture resolution: width height"));

	RegisterCameraCommand(Router, TEXT("vget /camera/[uint]/lit [str]"), [](USimCVCameraComponent* Camera, const FSimCVArgs& Args)
	{
		TArray<FColor> Pixels;
		if (!Camera->CaptureLit(Pixels))
		{
			return FSimCVReply::Error(TEXT("Captured data is empty"));
		}
		return DeliverColor(Pixels, Camera->GetFilmWidth(), Camera->GetFilmHeight(), Args[1]);
	}, TEXT("Lit image: png | bmp | /path/file.png|bmp"));

	RegisterCameraCommand(Router, TEXT("vget /camera/[uint]/depth [str]"), [](USimCVCameraComponent* Camera, const FSimCVArgs& Args)
	{
		TArray<float> Depth;
		if (!Camera->CaptureDepth(Depth))
		{
			return FSimCVReply::Error(TEXT("Captured data is empty"));
		}
		return DeliverFloat(Depth, Camera->GetFilmWidth(), Camera->GetFilmHeight(), Args[1]);
	}, TEXT("Depth in cm, float32: npy | /path/file.npy"));

	RegisterCameraCommand(Router, TEXT("vget /camera/[uint]/normal [str]"), [](USimCVCameraComponent* Camera, const FSimCVArgs& Args)
	{
		TArray<FColor> Pixels;
		if (!Camera->CaptureNormal(Pixels))
		{
			return FSimCVReply::Error(TEXT("Captured data is empty"));
		}
		return DeliverColor(Pixels, Camera->GetFilmWidth(), Camera->GetFilmHeight(), Args[1]);
	}, TEXT("World normals as colour: png | bmp | path"));

	auto ObjectMask = [](USimCVCameraComponent* Camera, const FSimCVArgs& Args)
	{
		TArray<FColor> Pixels;
		if (!Camera->CaptureObjectMask(Pixels))
		{
			return FSimCVReply::Error(TEXT("Object mask capture failed (check AnnotationMaterial in SimCV settings)"));
		}
		return DeliverColor(Pixels, Camera->GetFilmWidth(), Camera->GetFilmHeight(), Args[1]);
	};
	RegisterCameraCommand(Router, TEXT("vget /camera/[uint]/object_mask [str]"), ObjectMask, TEXT("Instance mask: png | bmp | path"));
	RegisterCameraCommand(Router, TEXT("vget /camera/[uint]/seg [str]"), ObjectMask, TEXT("Alias of object_mask"));
}
