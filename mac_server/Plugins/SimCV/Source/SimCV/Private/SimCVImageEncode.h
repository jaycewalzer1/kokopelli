#pragma once

#include "CoreMinimal.h"

namespace SimCV
{
	/** RGBA PNG (the client strips the 4th channel and flips to BGR). */
	bool EncodePng(const TArray<FColor>& Pixels, int32 Width, int32 Height, TArray<uint8>& Out);
	/** 32-bit top-down BMP, byte-identical layout to UnrealCV's FImageUtil::ConvertToBmp. */
	void EncodeBmp(const TArray<FColor>& Pixels, int32 Width, int32 Height, TArray<uint8>& Out);
	/** NPY v1.0, '<f4', shape (H, W) or (H, W, C), C order. */
	void EncodeNpyFloat32(const TArray<float>& Values, int32 Width, int32 Height, int32 Channels, TArray<uint8>& Out);
}
