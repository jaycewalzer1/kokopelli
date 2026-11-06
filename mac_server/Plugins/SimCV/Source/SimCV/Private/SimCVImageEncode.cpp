#include "SimCVImageEncode.h"

#include "IImageWrapper.h"
#include "IImageWrapperModule.h"
#include "Modules/ModuleManager.h"

static_assert(PLATFORM_LITTLE_ENDIAN, "FColor is assumed to be laid out as B,G,R,A in memory");

namespace
{
void AppendU16(TArray<uint8>& Out, uint16 Value)
{
	Out.Add(Value & 0xFF);
	Out.Add(Value >> 8);
}

void AppendU32(TArray<uint8>& Out, uint32 Value)
{
	for (int32 Shift = 0; Shift < 32; Shift += 8)
	{
		Out.Add((Value >> Shift) & 0xFF);
	}
}
}

bool SimCV::EncodePng(const TArray<FColor>& Pixels, int32 Width, int32 Height, TArray<uint8>& Out)
{
	if (Pixels.Num() != Width * Height || Pixels.Num() == 0)
	{
		return false;
	}
	IImageWrapperModule& Module = FModuleManager::LoadModuleChecked<IImageWrapperModule>(TEXT("ImageWrapper"));
	const TSharedPtr<IImageWrapper> Png = Module.CreateImageWrapper(EImageFormat::PNG);
	if (!Png.IsValid() || !Png->SetRaw(Pixels.GetData(), Pixels.Num() * sizeof(FColor), Width, Height, ERGBFormat::BGRA, 8))
	{
		return false;
	}
	const TArray64<uint8> Compressed = Png->GetCompressed();
	Out.Reset(Compressed.Num());
	Out.Append(Compressed.GetData(), static_cast<int32>(Compressed.Num()));
	return Out.Num() > 0;
}

void SimCV::EncodeBmp(const TArray<FColor>& Pixels, int32 Width, int32 Height, TArray<uint8>& Out)
{
	constexpr uint32 HeaderBytes = 14 + 40;
	const uint32 DataBytes = static_cast<uint32>(Width) * Height * 4;

	Out.Reset(HeaderBytes + DataBytes);
	// BITMAPFILEHEADER
	Out.Add('B');
	Out.Add('M');
	AppendU32(Out, HeaderBytes + DataBytes);
	AppendU16(Out, 0);
	AppendU16(Out, 0);
	AppendU32(Out, HeaderBytes);
	// BITMAPINFOHEADER; negative height = rows stored top-down
	AppendU32(Out, 40);
	AppendU32(Out, static_cast<uint32>(Width));
	AppendU32(Out, static_cast<uint32>(-Height));
	AppendU16(Out, 1);
	AppendU16(Out, 32);
	AppendU32(Out, 0);
	AppendU32(Out, DataBytes);
	AppendU32(Out, 2835);
	AppendU32(Out, 2835);
	AppendU32(Out, 0);
	AppendU32(Out, 0);
	// 32-bit BMP pixels are B,G,R,A — exactly FColor's memory layout.
	Out.Append(reinterpret_cast<const uint8*>(Pixels.GetData()), DataBytes);
}

void SimCV::EncodeNpyFloat32(const TArray<float>& Values, int32 Width, int32 Height, int32 Channels, TArray<uint8>& Out)
{
	const FString Shape = Channels == 1
		? FString::Printf(TEXT("(%d, %d)"), Height, Width)
		: FString::Printf(TEXT("(%d, %d, %d)"), Height, Width, Channels);
	FString Header = FString::Printf(TEXT("{'descr': '<f4', 'fortran_order': False, 'shape': %s, }"), *Shape);

	// Magic(6) + version(2) + header length(2) + header + '\n' must be a multiple of 64.
	constexpr int32 PreambleBytes = 10;
	const int32 Unpadded = PreambleBytes + Header.Len() + 1;
	Header += FString::ChrN((64 - Unpadded % 64) % 64, TEXT(' '));
	Header += TEXT("\n");

	const int32 DataBytes = Values.Num() * sizeof(float);
	Out.Reset(PreambleBytes + Header.Len() + DataBytes);
	const uint8 Magic[] = {0x93, 'N', 'U', 'M', 'P', 'Y', 1, 0};
	Out.Append(Magic, UE_ARRAY_COUNT(Magic));
	AppendU16(Out, static_cast<uint16>(Header.Len()));
	for (const TCHAR Ch : Header)
	{
		Out.Add(static_cast<uint8>(Ch));
	}
	Out.Append(reinterpret_cast<const uint8*>(Values.GetData()), DataBytes);
}
