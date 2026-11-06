#pragma once

#include "CoreMinimal.h"
#include "Dom/JsonObject.h"
#include "Dom/JsonValue.h"
#include "City/SWCityMesh.h"

/** Tiny readers for the builder's JSON (all optional with defaults). */
namespace SWCity::Json
{
	inline double Num(const TSharedPtr<FJsonObject>& J, const TCHAR* Key, double Default = 0.0)
	{
		double V = Default;
		return J.IsValid() && J->TryGetNumberField(Key, V) ? V : Default;
	}

	inline FString Str(const TSharedPtr<FJsonObject>& J, const TCHAR* Key, const FString& Default = FString())
	{
		FString V;
		return J.IsValid() && J->TryGetStringField(Key, V) ? V : Default;
	}

	inline bool Bool(const TSharedPtr<FJsonObject>& J, const TCHAR* Key, bool Default = false)
	{
		bool V = Default;
		return J.IsValid() && J->TryGetBoolField(Key, V) ? V : Default;
	}

	inline const TArray<TSharedPtr<FJsonValue>>* Arr(const TSharedPtr<FJsonObject>& J, const TCHAR* Key)
	{
		const TArray<TSharedPtr<FJsonValue>>* A = nullptr;
		return J.IsValid() && J->TryGetArrayField(Key, A) ? A : nullptr;
	}

	inline TArray<double> Nums(const TArray<TSharedPtr<FJsonValue>>* A)
	{
		TArray<double> Out;
		if (A)
		{
			for (const TSharedPtr<FJsonValue>& V : *A)
			{
				Out.Add(V.IsValid() && V->Type == EJson::Number ? V->AsNumber() : 0.0);
			}
		}
		return Out;
	}

	inline TArray<double> Nums(const TSharedPtr<FJsonObject>& J, const TCHAR* Key) { return Nums(Arr(J, Key)); }

	/** [x0,y0,x1,y1] -> min/max (sorted). */
	inline bool Rect(const TSharedPtr<FJsonObject>& J, const TCHAR* Key, FVector2D& Min, FVector2D& Max)
	{
		const TArray<double> R = Nums(J, Key);
		if (R.Num() < 4) return false;
		Min = FVector2D(FMath::Min(R[0], R[2]), FMath::Min(R[1], R[3]));
		Max = FVector2D(FMath::Max(R[0], R[2]), FMath::Max(R[1], R[3]));
		return true;
	}

	inline TArray<FVector2D> Points(const TArray<TSharedPtr<FJsonValue>>* A)
	{
		TArray<FVector2D> Out;
		if (A)
		{
			for (const TSharedPtr<FJsonValue>& V : *A)
			{
				const TArray<TSharedPtr<FJsonValue>>* P = nullptr;
				if (V.IsValid() && V->TryGetArray(P) && P->Num() >= 2)
				{
					Out.Add(FVector2D((*P)[0]->AsNumber(), (*P)[1]->AsNumber()));
				}
			}
		}
		return Out;
	}

	inline TArray<FVector2D> Points(const TSharedPtr<FJsonObject>& J, const TCHAR* Key) { return Points(Arr(J, Key)); }

	inline FLinearColor Color(const TSharedPtr<FJsonObject>& J, const TCHAR* Key, const FLinearColor& Default)
	{
		return ColorFromJson(Arr(J, Key), Default);
	}

	/** palette_rgb: [[r,g,b],...] */
	inline TArray<FLinearColor> Palette(const TSharedPtr<FJsonObject>& J)
	{
		TArray<FLinearColor> Out;
		if (const TArray<TSharedPtr<FJsonValue>>* A = Arr(J, TEXT("palette_rgb")))
		{
			for (const TSharedPtr<FJsonValue>& V : *A)
			{
				const TArray<TSharedPtr<FJsonValue>>* C = nullptr;
				if (V.IsValid() && V->TryGetArray(C))
				{
					Out.Add(ColorFromJson(C, FLinearColor::Gray));
				}
			}
		}
		return Out;
	}

	inline TArray<FString> Strs(const TSharedPtr<FJsonObject>& J, const TCHAR* Key)
	{
		TArray<FString> Out;
		if (const TArray<TSharedPtr<FJsonValue>>* A = Arr(J, Key))
		{
			for (const TSharedPtr<FJsonValue>& V : *A)
			{
				FString S;
				if (V.IsValid() && V->TryGetString(S)) Out.Add(S);
			}
		}
		return Out;
	}

	inline TArray<TSharedPtr<FJsonObject>> Objs(const TSharedPtr<FJsonObject>& J, const TCHAR* Key)
	{
		TArray<TSharedPtr<FJsonObject>> Out;
		if (const TArray<TSharedPtr<FJsonValue>>* A = Arr(J, Key))
		{
			for (const TSharedPtr<FJsonValue>& V : *A)
			{
				const TSharedPtr<FJsonObject>* O = nullptr;
				if (V.IsValid() && V->TryGetObject(O)) Out.Add(*O);
			}
		}
		return Out;
	}
}

/** Shared colours (sRGB picks; with the real materials they multiply the texture). */
namespace SWCity::Col
{
	inline FLinearColor Timber() { return Srgb(196, 148, 98); }
	inline FLinearColor TimberDark() { return Srgb(140, 98, 62); }
	inline FLinearColor Bamboo() { return Srgb(205, 175, 110); }
	inline FLinearColor Bark() { return Srgb(98, 76, 58); }
	inline FLinearColor Ochre() { return Srgb(200, 146, 92); }
	inline FLinearColor Rose() { return Srgb(208, 136, 96); } // relative to the ochre earth texture: a rosy shift, not pink
	inline FLinearColor Stone() { return Srgb(176, 166, 150); }
	inline FLinearColor StoneDark() { return Srgb(130, 124, 114); }
	inline FLinearColor Gravel() { return Srgb(206, 190, 160); }
	inline FLinearColor Sand() { return Srgb(222, 204, 165); }
	inline FLinearColor Soil() { return Srgb(96, 72, 52); }
	inline FLinearColor Water() { return Srgb(64, 118, 128); }
	inline FLinearColor Glass() { return Srgb(52, 72, 96); }
	inline FLinearColor GlassWarm() { return Srgb(150, 165, 160); }
	inline FLinearColor Grass() { return Srgb(104, 142, 66); }
	inline FLinearColor Lawn() { return Srgb(118, 160, 72); }
	inline FLinearColor Meadow() { return Srgb(132, 150, 74); }
	inline FLinearColor GreenRoof() { return Srgb(112, 140, 70); }
	inline FLinearColor Moss() { return Srgb(88, 120, 58); }
	inline FLinearColor Leaf(int32 i)
	{
		static const FColor C[] = {FColor(78, 124, 56), FColor(58, 104, 50), FColor(112, 148, 64), FColor(92, 136, 72)};
		return FLinearColor(C[((i % 4) + 4) % 4]);
	}
	inline FLinearColor Flower(int32 i)
	{
		static const FColor C[] = {FColor(206, 62, 140), FColor(244, 176, 196), FColor(238, 204, 72), FColor(246, 240, 228), FColor(164, 128, 206), FColor(232, 110, 60)};
		return FLinearColor(C[((i % 6) + 6) % 6]);
	}
	inline FLinearColor Metal() { return Srgb(70, 74, 72); }
	inline FLinearColor Brass() { return Srgb(196, 160, 84); }
	inline FLinearColor Verdigris() { return Srgb(96, 160, 140); }
	inline FLinearColor Lantern() { return Srgb(255, 196, 120); }
}
