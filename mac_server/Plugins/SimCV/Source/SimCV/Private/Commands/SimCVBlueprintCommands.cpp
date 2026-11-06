#include "SimCVCommands.h"

#include "Dom/JsonObject.h"
#include "Misc/Parse.h"
#include "Misc/ScopeExit.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"
#include "SimCVCommandRouter.h"
#include "SimCVWorld.h"
#include "UObject/PropertyPortFlags.h"
#include "UObject/UnrealType.h"

/*
 * vbp <object> <Function> [args...]
 *
 * Mirrors UnrealCV's FAliasHandler::VExecWithOutput: arguments are whitespace tokens bound to the
 * function's input parameters in declaration order (a trailing FString takes the rest of the line),
 * ProcessEvent runs the function, and the reply is a pretty-printed JSON object mapping every output
 * parameter / ReturnValue name to a *string*. So a C++ UFUNCTION(BlueprintCallable)
 *     void SitDown(bool& Success);
 * replies {"Success": "true"} exactly like the original blueprint did.
 */

namespace
{
bool IsInputParam(const FProperty* Param)
{
	// Same rule the blueprint editor uses for input pins (UPARAM(ref) counts as input).
	return !Param->HasAnyPropertyFlags(CPF_ReturnParm)
		&& (!Param->HasAnyPropertyFlags(CPF_OutParm) || Param->HasAnyPropertyFlags(CPF_ReferenceParm));
}

bool IsOutputParam(const FProperty* Param)
{
	return Param->HasAnyPropertyFlags(CPF_ReturnParm)
		|| (Param->HasAnyPropertyFlags(CPF_OutParm) && !Param->HasAnyPropertyFlags(CPF_ConstParm));
}

bool NextToken(const TCHAR*& Cursor, FString& Out)
{
	Out.Reset();
	return FParse::Token(Cursor, Out, /*UseEscape=*/true) && !Out.IsEmpty();
}

bool ParseNumber(const FString& Token, double& Out)
{
	if (LexTryParseString(Out, *Token))
	{
		return true;
	}
	bool bValue = false;
	if (SimCV::ParseBool(Token, bValue)) // python passes bools as "True"/"False"
	{
		Out = bValue ? 1.0 : 0.0;
		return true;
	}
	return false;
}

/** "x y z" (three tokens), "x,y,z", or "(X=..,Y=..,Z=..)" / "P=.. Y=.. R=.." style single token. */
bool ParseTriple(const TCHAR*& Cursor, double Out[3])
{
	FString First;
	if (!NextToken(Cursor, First))
	{
		return false;
	}

	TArray<FString> Parts;
	if (First.Contains(TEXT(",")))
	{
		First.Replace(TEXT("("), TEXT("")).Replace(TEXT(")"), TEXT("")).ParseIntoArray(Parts, TEXT(","));
	}
	else
	{
		Parts.Add(First);
		for (int32 Index = 0; Index < 2; ++Index)
		{
			FString Token;
			if (!NextToken(Cursor, Token))
			{
				return false;
			}
			Parts.Add(Token);
		}
	}
	if (Parts.Num() != 3)
	{
		return false;
	}
	for (int32 Index = 0; Index < 3; ++Index)
	{
		FString Part = Parts[Index].TrimStartAndEnd();
		int32 Equals = INDEX_NONE;
		if (Part.FindChar(TEXT('='), Equals))
		{
			Part.RightChopInline(Equals + 1);
		}
		if (!ParseNumber(Part, Out[Index]))
		{
			return false;
		}
	}
	return true;
}

bool ImportArg(FProperty* Param, void* Value, const TCHAR*& Cursor, bool bLastInput, FString& OutError)
{
	if (const FStrProperty* StrParam = CastField<FStrProperty>(Param))
	{
		if (bLastInput)
		{
			StrParam->SetPropertyValue(Value, FString(Cursor).TrimStartAndEnd());
			Cursor += FCString::Strlen(Cursor);
			return true;
		}
		FString Token;
		NextToken(Cursor, Token);
		StrParam->SetPropertyValue(Value, Token);
		return true;
	}

	if (const FStructProperty* StructParam = CastField<FStructProperty>(Param))
	{
		const bool bVector = StructParam->Struct == TBaseStructure<FVector>::Get();
		const bool bRotator = StructParam->Struct == TBaseStructure<FRotator>::Get();
		if (bVector || bRotator)
		{
			const TCHAR* Start = Cursor;
			double Triple[3] = {0, 0, 0};
			if (ParseTriple(Cursor, Triple))
			{
				if (bVector)
				{
					*static_cast<FVector*>(Value) = FVector(Triple[0], Triple[1], Triple[2]);
				}
				else
				{
					*static_cast<FRotator*>(Value) = FRotator(Triple[0], Triple[1], Triple[2]); // pitch yaw roll
				}
				return true;
			}
			Cursor = Start; // fall through to ImportText for "(X=1,Y=2,Z=3)"
		}
	}

	FString Token;
	if (!NextToken(Cursor, Token))
	{
		return true; // missing trailing arguments keep their zero/default value
	}

	if (const FBoolProperty* BoolParam = CastField<FBoolProperty>(Param))
	{
		bool bValue = false;
		double Number = 0.0;
		if (!SimCV::ParseBool(Token, bValue) && LexTryParseString(Number, *Token))
		{
			bValue = Number != 0.0;
		}
		BoolParam->SetPropertyValue(Value, bValue);
		return true;
	}

	if (const FNumericProperty* NumericParam = CastField<FNumericProperty>(Param))
	{
		double Number = 0.0;
		if (ParseNumber(Token, Number))
		{
			if (NumericParam->IsFloatingPoint())
			{
				NumericParam->SetFloatingPointPropertyValue(Value, Number);
			}
			else
			{
				NumericParam->SetIntPropertyValue(Value, static_cast<int64>(Number));
			}
			return true;
		}
		// Byte enums fall through to ImportText, which accepts enumerator names.
	}

	if (const FEnumProperty* EnumParam = CastField<FEnumProperty>(Param))
	{
		double Number = 0.0;
		if (LexTryParseString(Number, *Token))
		{
			EnumParam->GetUnderlyingProperty()->SetIntPropertyValue(Value, static_cast<int64>(Number));
			return true;
		}
	}

	if (const FNameProperty* NameParam = CastField<FNameProperty>(Param))
	{
		NameParam->SetPropertyValue(Value, FName(*Token));
		return true;
	}

	if (const FTextProperty* TextParam = CastField<FTextProperty>(Param))
	{
		TextParam->SetPropertyValue(Value, FText::FromString(Token));
		return true;
	}

	if (!Param->ImportText_Direct(*Token, Value, nullptr, PPF_None))
	{
		OutError = FString::Printf(TEXT("Bad value '%s' for parameter '%s'"), *Token, *Param->GetName());
		return false;
	}
	return true;
}

FString ExportValue(const FProperty* Param, const void* Value)
{
	if (const FStrProperty* StrParam = CastField<FStrProperty>(Param))
	{
		return StrParam->GetPropertyValue(Value);
	}
	if (const FNameProperty* NameParam = CastField<FNameProperty>(Param))
	{
		return NameParam->GetPropertyValue(Value).ToString();
	}
	if (const FTextProperty* TextParam = CastField<FTextProperty>(Param))
	{
		return TextParam->GetPropertyValue(Value).ToString();
	}
	if (const FBoolProperty* BoolParam = CastField<FBoolProperty>(Param))
	{
		return BoolParam->GetPropertyValue(Value) ? TEXT("true") : TEXT("false");
	}
	if (const FNumericProperty* NumericParam = CastField<FNumericProperty>(Param); NumericParam && !NumericParam->GetIntPropertyEnum())
	{
		return NumericParam->GetNumericPropertyValueToString(Value); // floats as "%f", like UnrealCV
	}
	if (const FStructProperty* StructParam = CastField<FStructProperty>(Param))
	{
		// ToString forms ("X=.. Y=.. Z=..", "P=.. Y=.. R=..") are what SimWorld's regexes expect.
		if (StructParam->Struct == TBaseStructure<FVector>::Get())
		{
			return static_cast<const FVector*>(Value)->ToString();
		}
		if (StructParam->Struct == TBaseStructure<FRotator>::Get())
		{
			return static_cast<const FRotator*>(Value)->ToString();
		}
	}
	FString Text;
	Param->ExportTextItem_Direct(Text, Value, nullptr, nullptr, PPF_None);
	return Text;
}

FSimCVReply CallFunction(UObject* Target, const FString& FunctionName, const FString& ArgText)
{
	UFunction* Function = Target->FindFunction(FName(*FunctionName, FNAME_Find));
	if (!Function)
	{
		return FSimCVReply::Error(FString::Printf(TEXT("Can not find function '%s' on '%s'"), *FunctionName, *Target->GetName()));
	}

	// Same parameter-frame setup as UObject::CallFunctionByNameWithArguments.
	uint8* Params = static_cast<uint8*>(FMemory_Alloca_Aligned(FMath::Max<int32>(Function->ParmsSize, 1), Function->GetMinAlignment()));
	FMemory::Memzero(Params, Function->ParmsSize);
	for (TFieldIterator<FProperty> It(Function); It && It->HasAnyPropertyFlags(CPF_Parm); ++It)
	{
		if (!It->HasAnyPropertyFlags(CPF_ZeroConstructor))
		{
			It->InitializeValue_InContainer(Params);
		}
	}
	ON_SCOPE_EXIT
	{
		for (TFieldIterator<FProperty> It(Function); It && It->HasAnyPropertyFlags(CPF_Parm); ++It)
		{
			It->DestroyValue_InContainer(Params);
		}
	};

	TArray<FProperty*> Inputs;
	for (TFieldIterator<FProperty> It(Function); It && It->HasAnyPropertyFlags(CPF_Parm); ++It)
	{
		if (IsInputParam(*It))
		{
			Inputs.Add(*It);
		}
	}

	const TCHAR* Cursor = *ArgText;
	for (int32 Index = 0; Index < Inputs.Num(); ++Index)
	{
		FString Error;
		if (!ImportArg(Inputs[Index], Inputs[Index]->ContainerPtrToValuePtr<void>(Params), Cursor, Index == Inputs.Num() - 1, Error))
		{
			return FSimCVReply::Error(FString::Printf(TEXT("%s when calling %s"), *Error, *FunctionName));
		}
	}

	Target->ProcessEvent(Function, Params);

	const TSharedRef<FJsonObject> Json = MakeShared<FJsonObject>();
	for (TFieldIterator<FProperty> It(Function); It && It->HasAnyPropertyFlags(CPF_Parm); ++It)
	{
		if (IsOutputParam(*It))
		{
			Json->SetStringField(It->GetName(), ExportValue(*It, It->ContainerPtrToValuePtr<void>(Params)));
		}
	}

	// Default (pretty) writer, as UnrealCV: "{\r\n\t\"Key\": \"value\"\r\n}". SimWorld strips \r\n\t itself.
	FString Out;
	const TSharedRef<TJsonWriter<>> Writer = TJsonWriterFactory<>::Create(&Out);
	FJsonSerializer::Serialize(Json, Writer);
	return FSimCVReply::Ok(Out);
}

FSimCVReply ResolveAndCall(const FSimCVArgs& Args, bool bReturnJson)
{
	UWorld* World = SimCV::GetWorld();
	UObject* Target = World ? SimCV::FindObject(World, Args[0]) : nullptr;
	if (!Target)
	{
		return FSimCVReply::Error(FString::Printf(TEXT("Can not find actor with id '%s'"), *Args[0]));
	}
	FSimCVReply Reply = CallFunction(Target, Args[1], Args[2]);
	return (bReturnJson || Reply.IsError()) ? Reply : FSimCVReply::Ok();
}
}

void SimCV::RegisterBlueprintCommands(FSimCVCommandRouter& Router)
{
	Router.Register(TEXT("vbp [str] [str] [rest]"), [](const FSimCVArgs& Args) { return ResolveAndCall(Args, true); },
		TEXT("Call a UFUNCTION by name; replies with output params as a JSON object of strings"));
	Router.Register(TEXT("vexec [str] [str] [rest]"), [](const FSimCVArgs& Args) { return ResolveAndCall(Args, false); },
		TEXT("Call a UFUNCTION by name; replies ok"));
}
