#include "SimCVCommandRouter.h"

#include "Internationalization/Regex.h"
#include "SimCVLog.h"

FSimCVReply FSimCVReply::Ok(const FString& InText)
{
	FSimCVReply Reply;
	Reply.Kind = EKind::Ok;
	Reply.Text = InText;
	return Reply;
}

FSimCVReply FSimCVReply::Error(const FString& Message)
{
	FSimCVReply Reply;
	Reply.Kind = EKind::Error;
	Reply.Text = Message;
	return Reply;
}

FSimCVReply FSimCVReply::Binary(TArray<uint8>&& Data)
{
	FSimCVReply Reply;
	Reply.Kind = EKind::Binary;
	Reply.Bytes = MoveTemp(Data);
	return Reply;
}

FSimCVReply FSimCVReply::Pending(TFunction<bool(FSimCVReply& Out)>&& InPoll)
{
	FSimCVReply Reply;
	Reply.Kind = EKind::Pending;
	Reply.Poll = MoveTemp(InPoll);
	return Reply;
}

void FSimCVReply::AppendPayload(TArray<uint8>& Out) const
{
	if (Kind == EKind::Binary)
	{
		Out.Append(Bytes);
		return;
	}
	const FString Message = Kind == EKind::Error ? FString(TEXT("error ")) + Text
		: (Text.IsEmpty() ? FString(TEXT("ok")) : Text);
	const FTCHARToUTF8 Utf8(*Message);
	Out.Append(reinterpret_cast<const uint8*>(Utf8.Get()), Utf8.Length());
}

namespace
{
const TCHAR* PlaceholderRegex(const FString& Type)
{
	if (Type == TEXT("str")) { return TEXT("(\\S+)"); }
	if (Type == TEXT("int")) { return TEXT("([-+]?\\d+)"); }
	if (Type == TEXT("uint")) { return TEXT("(\\d+)"); }
	if (Type == TEXT("float")) { return TEXT("([-+]?(?:\\d+\\.?\\d*|\\.\\d+)(?:[eE][-+]?\\d+)?)"); }
	return nullptr;
}

FString FirstWord(const FString& Text)
{
	int32 Space = INDEX_NONE;
	return Text.FindChar(TEXT(' '), Space) ? Text.Left(Space) : Text;
}
}

bool FSimCVCommandRouter::Register(const FString& Template, FSimCVHandler Handler, const FString& Help)
{
	FString Regex = TEXT("^");
	int32 NumArgs = 0;
	bool bHasRest = false;
	bool bPrevSpace = false;

	for (int32 Index = 0; Index < Template.Len(); ++Index)
	{
		if (bHasRest)
		{
			UE_LOG(LogSimCV, Error, TEXT("[rest] must be the last element: '%s'"), *Template);
			return false;
		}

		const TCHAR Ch = Template[Index];
		if (Ch == TEXT('['))
		{
			const int32 Close = Template.Find(TEXT("]"), ESearchCase::CaseSensitive, ESearchDir::FromStart, Index);
			if (Close == INDEX_NONE)
			{
				UE_LOG(LogSimCV, Error, TEXT("Unclosed '[' in template '%s'"), *Template);
				return false;
			}
			const FString Type = Template.Mid(Index + 1, Close - Index - 1);
			if (Type == TEXT("rest"))
			{
				// The rest is optional: swallow the separating whitespace into an optional group.
				if (bPrevSpace)
				{
					Regex.LeftChopInline(3); // "\\s+"
				}
				Regex += TEXT("(?:\\s+([\\s\\S]*?))?");
				bHasRest = true;
			}
			else if (const TCHAR* Fragment = PlaceholderRegex(Type))
			{
				Regex += Fragment;
			}
			else
			{
				UE_LOG(LogSimCV, Error, TEXT("Unknown placeholder [%s] in template '%s'"), *Type, *Template);
				return false;
			}
			++NumArgs;
			bPrevSpace = false;
			Index = Close;
			continue;
		}

		if (FChar::IsWhitespace(Ch))
		{
			if (!bPrevSpace)
			{
				Regex += TEXT("\\s+");
			}
			bPrevSpace = true;
			continue;
		}

		bPrevSpace = false;
		if (FCString::Strchr(TEXT("\\^$.|?*+()[]{}"), Ch))
		{
			Regex.AppendChar(TEXT('\\'));
		}
		Regex.AppendChar(Ch);
	}
	Regex += TEXT("\\s*$");

	FRoute& Route = Routes.AddDefaulted_GetRef();
	Route.Template = Template;
	Route.Verb = FirstWord(Template);
	Route.Help = Help;
	Route.Pattern = MakeShared<FRegexPattern>(Regex);
	Route.NumArgs = NumArgs;
	Route.bHasRest = bHasRest;
	Route.Handler = MoveTemp(Handler);
	return true;
}

FSimCVReply FSimCVCommandRouter::Execute(const FString& Command) const
{
	const FString Trimmed = Command.TrimStartAndEnd();
	const FString Verb = FirstWord(Trimmed);

	for (int32 Index = Routes.Num() - 1; Index >= 0; --Index)
	{
		const FRoute& Route = Routes[Index];
		if (!Route.Verb.Equals(Verb, ESearchCase::CaseSensitive))
		{
			continue;
		}

		FRegexMatcher Matcher(*Route.Pattern, Trimmed);
		if (!Matcher.FindNext())
		{
			continue;
		}

		FSimCVArgs Args;
		Args.Reserve(Route.NumArgs);
		for (int32 Group = 1; Group <= Route.NumArgs; ++Group)
		{
			Args.Add(Matcher.GetCaptureGroupBeginning(Group) == INDEX_NONE ? FString() : Matcher.GetCaptureGroup(Group));
		}
		return Route.Handler(Args);
	}

	return FSimCVReply::Error(FString::Printf(TEXT("No handler found for URI '%s'"), *Command));
}

TArray<FString> FSimCVCommandRouter::GetClientTemplates() const
{
	// The python client turns each [..] into \S*, so a [rest] route is listed once per token count.
	constexpr int32 MaxRestTokens = 16;

	TArray<FString> Templates;
	for (const FRoute& Route : Routes)
	{
		if (!Route.bHasRest)
		{
			Templates.AddUnique(Route.Template);
			continue;
		}
		FString Base = Route.Template.Replace(TEXT("[rest]"), TEXT("")).TrimEnd();
		Templates.AddUnique(Base);
		for (int32 Count = 1; Count <= MaxRestTokens; ++Count)
		{
			Base += TEXT(" [str]");
			Templates.AddUnique(Base);
		}
	}
	Templates.Sort();
	return Templates;
}

TArray<TPair<FString, FString>> FSimCVCommandRouter::GetHelp() const
{
	TArray<TPair<FString, FString>> Help;
	for (const FRoute& Route : Routes)
	{
		Help.Emplace(Route.Template, Route.Help);
	}
	return Help;
}
