"""Collections: folders of documents that are indexed together and searched together."""

from analyst_copilot.collections.indexer import CollectionIndexer
from analyst_copilot.collections.models import (
    Collection,
    CollectionDocument,
    InvalidCollectionName,
    sanitize_collection_name,
)
from analyst_copilot.collections.searcher import CollectionSearcher
from analyst_copilot.collections.store import CollectionNotFound, CollectionStore

__all__ = [
    "Collection",
    "CollectionDocument",
    "CollectionIndexer",
    "CollectionNotFound",
    "CollectionSearcher",
    "CollectionStore",
    "InvalidCollectionName",
    "sanitize_collection_name",
]
