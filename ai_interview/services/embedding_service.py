
from typing import List, Tuple, Optional
import numpy as np
import dashscope
from dashscope import TextEmbedding
from django.conf import settings


class EmbeddingService:

    _api_key = None
    _model_name = None

    @classmethod
    def initialize(cls):
        if cls._api_key is None:
            cls._api_key = getattr(settings, 'DASHSCOPE_API_KEY', '')
            cls._model_name = getattr(settings, 'QWEN_EMBEDDING_MODEL', 'text-embedding-v4')
            dashscope.api_key = cls._api_key

    @classmethod
    def encode(cls, texts: List[str]) -> List[List[float]]:
        cls.initialize()
        if not cls._api_key or not texts:
            return [[0.0] * 1024 for _ in texts]

        try:
            response = TextEmbedding.call(
                model=cls._model_name,
                input=texts,
                text_type='document'
            )

            if response.status_code == 200:
                embeddings = [item['embedding'] for item in response.output['embeddings']]
                return embeddings

            return [[0.0] * 1024 for _ in texts]

        except Exception as e:
            return [[0.0] * 1024 for _ in texts]

    @classmethod
    def compute_similarity(cls, text1: str, text2: str) -> float:
        embeddings = cls.encode([text1, text2])
        emb1 = np.array(embeddings[0])
        emb2 = np.array(embeddings[1])

        norm1 = np.linalg.norm(emb1)
        norm2 = np.linalg.norm(emb2)

        if norm1 == 0 or norm2 == 0:
            return 0.0

        similarity = np.dot(emb1, emb2) / (norm1 * norm2)
        return float(similarity)

    @classmethod
    def are_semantically_similar(cls, text1: str, text2: str, threshold: float = 0.3) -> bool:
        similarity = cls.compute_similarity(text1, text2)
        return similarity >= threshold

    @classmethod
    def compute_text_similarity_with_question(
        cls,
        question: str,
        answer: str,
        threshold: float = 0.3
    ) -> Tuple[float, bool]:
        similarity = cls.compute_similarity(question, answer)
        is_valid = similarity >= threshold
        return similarity, is_valid

    @classmethod
    def find_best_match(cls, target: str, candidates: List[str]) -> Tuple[Optional[str], float]:
        if not candidates:
            return None, 0.0

        embeddings = cls.encode([target] + candidates)
        target_emb = np.array(embeddings[0])

        best_score = -1.0
        best_match = None

        for i, candidate_emb in enumerate(embeddings[1:]):
            score = cls.compute_similarity(target, candidates[i])
            if score > best_score:
                best_score = score
                best_match = candidates[i]

        return best_match, float(best_score)
