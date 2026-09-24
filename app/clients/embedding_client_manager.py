"""
Embedding 客户端管理器

负责按配置初始化 Embedding 服务客户端，并为字段、指标和用户问题的向量化
提供统一访问入口
"""

import asyncio
from typing import Optional

import httpx
from langchain_core.embeddings import Embeddings
from langchain_huggingface import HuggingFaceEndpointEmbeddings

from app.conf.app_config import EmbeddingConfig, app_config


class OllamaEmbeddings(Embeddings):
    """通过 Ollama 原生 `/api/embed` 接口生成本地向量。"""

    def __init__(self, *, base_url: str, model: str):
        self.base_url = base_url.rstrip("/")
        self.model = model

    @staticmethod
    def _parse(payload: dict) -> list[list[float]]:
        embeddings = payload.get("embeddings")
        if not isinstance(embeddings, list):
            raise ValueError("Ollama embedding response has no embeddings")
        return embeddings

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        with httpx.Client(timeout=120, trust_env=False) as client:
            response = client.post(
                f"{self.base_url}/api/embed",
                json={"model": self.model, "input": texts},
            )
        response.raise_for_status()
        return self._parse(response.json())

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        async with httpx.AsyncClient(timeout=120, trust_env=False) as client:
            response = await client.post(
                f"{self.base_url}/api/embed",
                json={"model": self.model, "input": texts},
            )
        response.raise_for_status()
        return self._parse(response.json())

    async def aembed_query(self, text: str) -> list[float]:
        return (await self.aembed_documents([text]))[0]


class EmbeddingClientManager:
    """管理 Embedding 服务客户端的初始化与复用"""

    def __init__(self, config: EmbeddingConfig):
        self.client: Optional[Embeddings] = None
        self.config = config

    def _get_url(self) -> str:
        """拼接 Embedding 服务地址"""
        return f"http://{self.config.host}:{self.config.port}"

    def init(self):
        """显式初始化客户端，避免模块导入时立即建立外部连接"""
        if self.config.provider == "ollama":
            self.client = OllamaEmbeddings(
                base_url=self._get_url(), model=self.config.model
            )
            return
        if self.config.provider != "huggingface_endpoint":
            raise ValueError(f"Unsupported embedding provider: {self.config.provider}")
        self.client = HuggingFaceEndpointEmbeddings(model=self._get_url())


# 模块级单例，供整个项目复用同一套 Embedding 客户端管理器
embedding_client_manager = EmbeddingClientManager(app_config.embedding)


if __name__ == "__main__":
    embedding_client_manager.init()
    client = embedding_client_manager.client

    async def test():
        """执行一次最小化向量化调用，验证服务是否可用"""
        text = "What is deep learning?"
        query_result = await client.aembed_query(text)
        print(query_result[:3])

    asyncio.run(test())
