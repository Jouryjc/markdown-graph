"""mdgraph: Markdown knowledge graph + vector dual-engine retrieval."""

from mdgraph.engine import MarkdownGraph
from mdgraph.models import (
    Chunk,
    Document,
    Edge,
    EdgeType,
    Node,
    NodeType,
)

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "Chunk",
    "Document",
    "Edge",
    "EdgeType",
    "MarkdownGraph",
    "Node",
    "NodeType",
]
