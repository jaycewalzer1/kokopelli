#pragma once

#include "CoreMinimal.h"
#include "Templates/Function.h"

class FRegexPattern;

/** Result of one command. Serialised exactly like UnrealCV's FExecStatus. */
struct SIMCV_API FSimCVReply
{
	enum class EKind : uint8
	{
		Ok,
		Error,
		Binary,
		Pending,
	};

	EKind Kind = EKind::Ok;
	FString Text;
	TArray<uint8> Bytes;

	/** Pending replies are polled once per frame on the game thread until they fill Out and return true.
	 *  Requests behind a pending reply wait, so per-client reply order is preserved. */
	TFunction<bool(FSimCVReply& Out)> Poll;

	static FSimCVReply Ok(const FString& InText = FString());
	static FSimCVReply Error(const FString& Message);
	static FSimCVReply Binary(TArray<uint8>&& Data);
	static FSimCVReply Pending(TFunction<bool(FSimCVReply& Out)>&& InPoll);

	bool IsError() const { return Kind == EKind::Error; }

	/** Wire payload after the "id:" prefix: "ok" | text | "error <msg>" | raw bytes. */
	void AppendPayload(TArray<uint8>& Out) const;
};

using FSimCVArgs = TArray<FString>;
using FSimCVHandler = TFunction<FSimCVReply(const FSimCVArgs& Args)>;

/**
 * Pattern-based command registry, UnrealCV style.
 *
 * Templates are literal text plus placeholders, e.g. "vget /object/[str]/location".
 *   [str]   one non-whitespace token (may contain '/', e.g. asset paths)
 *   [int]   signed integer      [uint] unsigned integer
 *   [float] number, exponent allowed
 *   [rest]  the remainder of the line, spaces included; must be last and is optional
 *           (an empty string is passed when absent)
 * Whitespace in a template matches one or more spaces. Captured values are passed in order.
 * Later registrations win over earlier ones, so game code can override built-ins.
 * Handlers run on the game thread.
 */
class SIMCV_API FSimCVCommandRouter
{
public:
	bool Register(const FString& Template, FSimCVHandler Handler, const FString& Help = FString());

	FSimCVReply Execute(const FString& Command) const;

	/** Templates in the form the python client checks against ([rest] expanded to repeated [str]). */
	TArray<FString> GetClientTemplates() const;

	/** (template, help) pairs in registration order. */
	TArray<TPair<FString, FString>> GetHelp() const;

private:
	struct FRoute
	{
		FString Template;
		FString Verb;
		FString Help;
		TSharedPtr<FRegexPattern> Pattern;
		int32 NumArgs = 0;
		bool bHasRest = false;
		FSimCVHandler Handler;
	};

	TArray<FRoute> Routes;
};
