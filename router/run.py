"""Ejecuta el prompt en el modelo que eligió la capa de ruteo."""

from __future__ import annotations

import sys

import anthropic

from .policy import Route, cost, decide

AGENT_SYSTEM = (
    "Eres un asistente de ingeniería de software. Respondes directo, sin preámbulo. "
    "Si el pedido es de código, entregas código."
)

DIM, BOLD, RESET = "\033[2m", "\033[1m", "\033[0m"


def _build_params(route: Route, prompt: str) -> dict:
    params = {
        "model": route.model,
        "max_tokens": 32000,
        "system": AGENT_SYSTEM,
        "messages": [{"role": "user", "content": prompt}],
    }
    if route.effort:  # haiku-4-5 no acepta effort
        params["output_config"] = {"effort": route.effort}
    if route.fast:
        params["speed"] = "fast"
        params["betas"] = ["fast-mode-2026-02-01"]
    return params


def main(argv: list[str]) -> int:
    prompt = " ".join(argv).strip() or sys.stdin.read().strip()
    if not prompt:
        print("uso: claude <prompt>", file=sys.stderr)
        return 2

    client = anthropic.Anthropic()

    route = decide(client, prompt)
    tag = f"{route.model}{' +fast' if route.fast else ''}{f' · effort={route.effort}' if route.effort else ''}"
    print(f"{DIM}┌ router → {BOLD}{tag}{RESET}", file=sys.stderr)
    print(f"{DIM}└ {route.reason}{RESET}\n", file=sys.stderr)

    params = _build_params(route, prompt)
    # fast mode vive en el endpoint beta; el resto usa el normal
    stream = (client.beta.messages if route.fast else client.messages).stream(**params)

    with stream as s:
        for text in s.text_stream:
            print(text, end="", flush=True)
        final = s.get_final_message()
    print()

    total = cost(route.price_key, final.usage) + cost("claude-haiku-4-5", route.router_usage)
    print(
        f"\n{DIM}· {final.usage.input_tokens} in / {final.usage.output_tokens} out"
        f" · ~${total:.4f} (ruteo incluido){RESET}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
