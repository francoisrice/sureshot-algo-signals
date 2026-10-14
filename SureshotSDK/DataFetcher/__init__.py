from .client import DataFetcherClient

__all__ = ["DataFetcherClient", "DataFetcherPool"]


def __getattr__(name):
    # The pool pulls in stagehand (browser automation); only the DataFetcher service needs it
    if name == "DataFetcherPool":
        from .pool import DataFetcherPool
        return DataFetcherPool
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
