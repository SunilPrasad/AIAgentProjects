using System.Reflection;
using System.Text.Json;

namespace GreatIndians.Factory;

public static class FailureDetails
{
    public static Exception Unwrap(Exception exception)
    {
        while (true)
        {
            if (exception is TargetInvocationException { InnerException: { } inner })
            {
                exception = inner;
            }
            else if (exception is AggregateException aggregate
                && aggregate.InnerExceptions.Count == 1)
            {
                exception = aggregate.InnerExceptions[0];
            }
            else
            {
                return exception;
            }
        }
    }

    public static string Reason(Exception exception)
    {
        var cause = Unwrap(exception);

        return cause switch
        {
            EditorialException or InvalidDataException => cause.Message,
            HttpRequestException http when http.StatusCode.HasValue
                => $"HTTP {(int)http.StatusCode.Value}: source or model request failed.",
            _ => cause.GetType().Name
        };
    }

    public static string Report(Exception exception)
    {
        var cause = Unwrap(exception);

        // Stack traces contain code locations; API response bodies and request data are excluded.
        return Data.Write(new
        {
            recordedAt = DateTimeOffset.UtcNow,
            wrapperType = exception.GetType().FullName,
            causeType = cause.GetType().FullName,
            reason = Reason(cause),
            stackTrace = cause.StackTrace
        });
    }
}
