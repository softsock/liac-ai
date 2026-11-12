"""Verified text template and optional, strictly local Nemotron token counting."""

from hashlib import sha256
from pathlib import Path

from vtuber.context import ChatMessage


# NVIDIA tokenizer_config.json, text-only expansion with enable_thinking=False,
# conversational_mode=True. Raw /v1/completions applies no second chat template.
SPOKEN_INSTRUCTION = ("You are having a spoken conversation with the user. Respond as briefly as possible "
                      "while still addressing their questions fully.")
CONTROL_MARKERS = ("<|", "<turn|>", "<channel|>", "<tool_call|>", "<tool_response|>",
                   "<think>", "</think>", "<bos>", "<eos>")


def render_nemotron(messages: tuple[ChatMessage, ...]) -> str:
    if not messages or messages[0].role != "system" or messages[-1].role != "user":
        raise ValueError("Require initial identity and final user input")
    rendered = []
    for index, message in enumerate(messages):
        if index and message.role == "system":
            raise ValueError("Only one initial system message is supported")
        content = message.content.strip() if index == 0 else message.content
        # Keep literal delimiters as quoted data, including in failed-turn history.
        for marker in CONTROL_MARKERS:
            content = content.replace(marker, "\\u003c" + marker[1:])
        if index == 0 and content != SPOKEN_INSTRUCTION:
            content += "\n\n" + SPOKEN_INSTRUCTION
        role = "model" if message.role == "assistant" else message.role
        continuation = index > 0 and message.role == messages[index - 1].role == "assistant"
        continues = index + 1 < len(messages) and message.role == messages[index + 1].role == "assistant"
        rendered.append(("" if continuation else f"<|turn>{role}\n") + content +
                        ("" if continues else "<turn|>\n"))
    rendered.append("<|turn>model\n")
    return "".join(rendered)


class NemotronTokenCounter:
    fingerprint = "cc8d3a0ce36466ccc1278bf987df5f71db1719b9ca6b4118264f45cb627bfe0f"
    method = "NVIDIA tokenizer.json + rendered Gemma4 template + backend BOS"

    def __init__(self, path: Path) -> None:
        if sha256(path.read_bytes()).hexdigest() != self.fingerprint:
            raise ValueError("Nemotron tokenizer SHA-256 does not match the pinned asset")
        try:
            from tokenizers import Tokenizer
        except ImportError as error:
            raise ValueError("Install liac-ai[nemotron] for local token counting") from error
        self.tokenizer = Tokenizer.from_file(str(path))
        for token, expected in (("<bos>", 2), ("<eos>", 1), ("<|turn>", 105), ("<turn|>", 106)):
            if self.tokenizer.token_to_id(token) != expected:
                raise ValueError("Unexpected Nemotron special token IDs")
        self.tokenizer.no_truncation()
        self.tokenizer.no_padding()

    def __call__(self, messages: tuple[ChatMessage, ...]) -> int:
        # The pinned tokenizer adds no BOS; the verified GGUF backend adds one.
        return len(self.tokenizer.encode(render_nemotron(messages), add_special_tokens=False).ids) + 1
