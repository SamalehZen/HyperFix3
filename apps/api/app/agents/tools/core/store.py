from typing import cast

from langchain_core.embeddings import Embeddings
from langgraph.store.base import BaseStore

from app.config.settings import settings
from app.core.lazy_loader import MissingKeyStrategy, lazy_provider, providers


class _LocalDeterministicEmbeddings(Embeddings):
    """HyperFix : embeddings locaux déterministes (hachage, dim 768).

    Remplace GoogleGenerativeAIEmbeddings (GOOGLE_API_KEY absent de notre
    déploiement) pour l'indexation des tools/triggers dans ChromaDB. Le sens
    sémantique est dégradé (hachage ≠ modèle), mais :
    - le retrieve_tools garde le keyword/token matching (fallback prévu) ;
    - la dimension colle à EMBEDDING_DIM (768) attendue par les stores ;
    - zéro dépendance externe, zéro coût.
    """

    def __init__(self, dims: int = 768) -> None:
        self._dims = dims

    def _embed(self, text: str) -> list[float]:
        import hashlib

        vec = [0.0] * self._dims
        for token in text.lower().split():
            h = int(hashlib.sha256(token.encode()).hexdigest(), 16)
            vec[h % self._dims] += 1.0
        norm = sum(v * v for v in vec) ** 0.5 or 1.0
        return [v / norm for v in vec]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(t) for t in texts]


@lazy_provider(
    name="google_embeddings",
    required_keys=[],
    strategy=MissingKeyStrategy.WARN,
    auto_initialize=False,
    warning_message="Embeddings locaux deterministes (HyperFix). La recherche semantique tools/triggers est degradee.",
)
def init_embeddings() -> Embeddings:
    if settings.GOOGLE_API_KEY:
        from langchain_google_genai import GoogleGenerativeAIEmbeddings

        return GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-001")
    return _LocalDeterministicEmbeddings()


async def get_tools_store() -> BaseStore:
    tools_store = await providers.aget("chroma_tools_store")
    if tools_store is None:
        raise RuntimeError("Tools store not available")
    # providers.aget declares -> Any | None; the "chroma_tools_store" provider
    # factory (initialize_chroma_tools_store) always returns a ChromaStore(BaseStore).
    return cast(BaseStore, tools_store)
