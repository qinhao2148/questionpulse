import json

import httpx
from pydantic import ValidationError

from app.ai.schemas import ClusterCandidate, QuizDraft, SemanticDecision


class DeepSeekError(RuntimeError):
    pass


class DeepSeekAnalyzer:
    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        timeout: float = 15.0,
        max_output_tokens: int = 1200,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.max_output_tokens = max_output_tokens

    async def classify(
        self, classroom_title: str, question: str, candidates: list[ClusterCandidate]
    ) -> tuple[SemanticDecision, dict[str, int]]:
        if not self.api_key:
            raise DeepSeekError("deepseek_not_configured")
        prompt = {
            "classroom_title": classroom_title,
            "new_question": question,
            "existing_clusters": [candidate.model_dump() for candidate in candidates],
            "instructions": (
                "判断新问题是否与已有疑问簇表达同一个核心困惑。"
                "只能使用提供的 cluster id。若没有合适簇则 create_new。"
                "confidence 必须为 0 到 1。输出 json。"
            ),
            "json_example": {
                "decision": "join_existing",
                "cluster_id": "existing-id-or-null",
                "confidence": 0.9,
                "normalized_intent": "问题的规范化意图",
                "suggested_title": "适合教师查看的疑问标题",
                "reason": "简短判断依据",
            },
        }
        request_body = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是课堂疑问语义分析器。不要计算学生人数，不执行课堂操作，"
                        "只返回符合示例字段的 json 对象。"
                    ),
                },
                {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
            ],
            "response_format": {"type": "json_object"},
            "max_tokens": self.max_output_tokens,
            "temperature": 0.1,
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json=request_body,
                )
            response.raise_for_status()
            payload = response.json()
            content = payload["choices"][0]["message"]["content"]
            decision = SemanticDecision.model_validate(json.loads(content))
            usage = payload.get("usage") or {}
            return decision, {
                "prompt_tokens": int(usage.get("prompt_tokens") or 0),
                "completion_tokens": int(usage.get("completion_tokens") or 0),
            }
        except (
            httpx.HTTPError,
            KeyError,
            IndexError,
            TypeError,
            ValueError,
            ValidationError,
        ) as exc:
            raise DeepSeekError(type(exc).__name__) from exc

    async def generate_quiz(
        self, classroom_title: str, cluster_title: str, questions: list[str]
    ) -> tuple[QuizDraft, dict[str, int]]:
        if not self.api_key:
            raise DeepSeekError("deepseek_not_configured")
        prompt = {
            "classroom_title": classroom_title,
            "cluster_title": cluster_title,
            "student_questions": questions[:8],
            "instructions": (
                "根据群体疑问生成一道用于讲解后即时检测的中文单选题。"
                "只有一个正确答案，干扰项应能识别常见误解。输出 json。"
            ),
            "json_example": {
                "stem": "题干",
                "options": [
                    {"key": "A", "content": "选项 A"},
                    {"key": "B", "content": "选项 B"},
                    {"key": "C", "content": "选项 C"},
                    {"key": "D", "content": "选项 D"},
                ],
                "correct_option_key": "A",
                "explanation": "答案解析",
            },
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={
                        "model": self.model,
                        "messages": [
                            {
                                "role": "system",
                                "content": "你是课堂形成性评价设计器，只返回有效 json。",
                            },
                            {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
                        ],
                        "response_format": {"type": "json_object"},
                        "max_tokens": self.max_output_tokens,
                        "temperature": 0.2,
                    },
                )
            response.raise_for_status()
            payload = response.json()
            draft = QuizDraft.model_validate_json(payload["choices"][0]["message"]["content"])
            usage = payload.get("usage") or {}
            return draft, {
                "prompt_tokens": int(usage.get("prompt_tokens") or 0),
                "completion_tokens": int(usage.get("completion_tokens") or 0),
            }
        except (
            httpx.HTTPError,
            KeyError,
            IndexError,
            TypeError,
            ValueError,
            ValidationError,
        ) as exc:
            raise DeepSeekError(type(exc).__name__) from exc
