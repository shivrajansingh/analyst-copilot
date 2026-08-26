"""The parser version stamped into every index.

Kept in its own module so the storage layer can import it without depending on
any one format's parser. Bump it whenever a parsing change alters segment
boundaries or the text a segment yields: persisted indices record the value and
are treated as absent when it no longer matches, so a parser fix can never be
masked by stale embeddings on disk.

History:
  1-2  HTML page-break split, plain text
  3    `page-break-before` matched as well as `-after`
  4    Multi-format parsers; every segment is normalized to Markdown
"""

from __future__ import annotations

PARSER_VERSION = "4"
