import hashlib
import math
import re

MODEL_NAME = "questionpulse-zh-semantic-hash-v1"
DIMENSIONS = 256

CONCEPTS = {
    "递归出口": ("结束条件", "终止条件", "basecase", "停下来", "停止调用"),
    "递归栈": ("栈溢出", "调用栈", "栈空间", "recursiondepth", "爆栈"),
    "异步顺序": ("执行顺序", "事件循环", "微任务", "宏任务", "settimeout", "await顺序"),
    "异步异常": ("reject", "catch", "异常捕获", "请求失败", "promiseall报错"),
    "索引使用": ("走索引", "使用索引", "索引失效", "explain", "模糊查询"),
    "404": ("找不到页面", "资源不存在", "路由不存在", "状态码404"),
    "500": ("服务器错误", "未处理异常", "状态码500", "后端报错"),
}


def normalize(text: str) -> str:
    compact = re.sub(r"[\s，。！？、：；,.!?:;_'\"`]+", "", text.lower())
    for concept, aliases in CONCEPTS.items():
        if concept in compact or any(alias in compact for alias in aliases):
            compact += f"#{concept}#{concept}"
    return compact


def embed(text: str) -> list[float]:
    normalized = normalize(text)
    if not normalized:
        raise ValueError("empty_content")
    features = [
        normalized[index : index + size]
        for size in (1, 2, 3)
        for index in range(len(normalized) - size + 1)
    ]
    vector = [0.0] * DIMENSIONS
    for feature in features:
        digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
        index = int.from_bytes(digest, "big") % DIMENSIONS
        vector[index] += 1.0
    magnitude = math.sqrt(sum(value * value for value in vector))
    return [value / magnitude for value in vector]


def cosine(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right, strict=True))
