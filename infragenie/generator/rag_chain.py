"""
RAG pipeline for Dockerfile generation.
Uses LLMFactory to work across OpenAI, Google Gemini, Anthropic, and Ollama.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from infragenie.config import settings
from infragenie.llm import LLMFactory
from infragenie.utils.exceptions import LLMError, RAGIndexError
from infragenie.utils.logger import get_logger

if TYPE_CHECKING:
    from infragenie.analyzer.models import AnalysisReport

log = get_logger(__name__)

KNOWLEDGE_DIR = Path(__file__).parent / "knowledge"
COLLECTION_NAME = "infragenie_aws_docs"


class RAGChain:
    """
    Retrieval-Augmented Generation pipeline.
    Uses LLMFactory to support all configured LLM providers (Google, OpenAI, Anthropic, Ollama).
    """

    def __init__(self) -> None:
        self._provider = None
        self._vectorstore = None
        self._initialized = False

    def initialize(self) -> None:
        """Initialize LLM provider and ChromaDB vectorstore."""
        if self._initialized:
            return

        try:
            self._provider = LLMFactory.create()
        except Exception as exc:
            raise LLMError(f"Failed to initialize LLM provider: {exc}") from exc

        try:
            from langchain_chroma import Chroma
            from langchain_community.document_loaders import TextLoader
            from langchain_text_splitters import RecursiveCharacterTextSplitter
            
            embeddings = self._provider.get_embeddings()
            persist_path = Path(settings.chroma_persist_dir)

            if (persist_path / COLLECTION_NAME).exists():
                log.info("Loading existing ChromaDB index")
                self._vectorstore = Chroma(
                    collection_name=COLLECTION_NAME,
                    embedding_function=embeddings,
                    persist_directory=str(persist_path),
                )
            else:
                log.info("Building ChromaDB index from knowledge docs")
                docs = self._load_knowledge_docs()
                splitter = RecursiveCharacterTextSplitter(chunk_size=800, chunk_overlap=100)
                chunks = splitter.split_documents(docs)
                self._vectorstore = Chroma.from_documents(
                    documents=chunks,
                    embedding=embeddings,
                    collection_name=COLLECTION_NAME,
                    persist_directory=str(persist_path),
                )
        except Exception as exc:
            log.warning("Vectorstore initialization skipped (direct LLM will be used)", error=str(exc))
            self._vectorstore = None

        self._initialized = True
        log.info("RAG pipeline ready", provider=self._provider.provider_name)

    def _load_knowledge_docs(self) -> list:
        """Load all markdown knowledge files from the knowledge directory."""
        from langchain_community.document_loaders import TextLoader

        docs = []
        for md_file in KNOWLEDGE_DIR.glob("*.md"):
            loader = TextLoader(str(md_file), encoding="utf-8")
            docs.extend(loader.load())
        return docs

    def retrieve_context(self, query: str, k: int = 3) -> str:
        """Retrieve top-k relevant chunks for a given query."""
        if not self._initialized:
            self.initialize()

        if self._vectorstore is None:
            # Fallback to reading knowledge files directly
            try:
                kb = (KNOWLEDGE_DIR / "aws_best_practices.md").read_text(encoding="utf-8")
                return kb[:1500]
            except Exception:
                return ""

        try:
            retriever = self._vectorstore.as_retriever(search_kwargs={"k": k})
            docs = retriever.invoke(query)
            return "\n\n---\n\n".join(d.page_content for d in docs)
        except Exception as e:
            log.warning("Vector search error, using direct knowledge fallback", error=str(e))
            kb = (KNOWLEDGE_DIR / "aws_best_practices.md").read_text(encoding="utf-8")
            return kb[:1500]

    def generate(self, prompt: str) -> str:
        """Send a prompt to the LLM and return the response text."""
        if not self._initialized:
            self.initialize()

        system_prompt = (
            "You are an expert DevSecOps engineer specializing in Docker and AWS security. "
            "Generate production-ready, security-hardened Docker configurations. "
            "NEVER include hardcoded secrets, root users, or insecure configurations. "
            "Always follow CIS Docker Benchmark and AWS Well-Architected best practices."
        )
        return self._provider.chat(system_prompt, prompt)
