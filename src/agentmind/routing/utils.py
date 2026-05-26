"""路由模块共享工具函数。"""


def extract_response_path(raw_output: str, response_path: str) -> str:
    """从 JSON 输出中按路径提取字段值。

    如 response_path="payloads.0.text" 从 {"payloads":[{"text":"..."}]}
    中提取实际文本。不匹配或解析失败时返回原字符串。
    """
    if not response_path or not raw_output.strip().startswith("{"):
        return raw_output
    try:
        import json
        parsed = json.loads(raw_output)
        val = parsed
        for k in response_path.split("."):
            if isinstance(val, list) and k.isdigit():
                val = val[int(k)]
            elif isinstance(val, dict):
                val = val.get(k)
            else:
                return raw_output
        return str(val) if val is not None else raw_output
    except Exception:
        return raw_output
