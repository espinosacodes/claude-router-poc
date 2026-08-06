"""Capa de ruteo: un modelo barato decide, de forma estructurada, qué modelo ejecuta."""

from __future__ import annotations

import json
from dataclasses import dataclass

import anthropic

ROUTER_MODEL = "claude-haiku-4-5"  # el clasificador siempre es el más barato

# tier -> (model_id, soporta_effort, soporta_fast)
TIERS = {
    "haiku": ("claude-haiku-4-5", False, False),
    "sonnet": ("claude-sonnet-5", True, False),
    "opus": ("claude-opus-5", True, True),
}

# USD por millón de tokens (input, output)
PRICING = {
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-sonnet-5": (3.00, 15.00),
    "claude-opus-5": (5.00, 25.00),
    "claude-opus-5:fast": (10.00, 50.00),
}

ROUTE_SCHEMA = {
    "type": "object",
    "properties": {
        "tier": {
            "type": "string",
            "enum": ["haiku", "sonnet", "opus"],
            "description": "Modelo que debe ejecutar la tarea.",
        },
        "effort": {
            "type": "string",
            "enum": ["low", "medium", "high", "xhigh"],
            "description": "Profundidad de razonamiento. Ignorado en haiku.",
        },
        "fast": {
            "type": "boolean",
            "description": "Fast mode: 2.5x velocidad al doble de costo. Solo tier opus.",
        },
        "reason": {
            "type": "string",
            "description": "Una frase justificando la decisión.",
        },
    },
    "required": ["tier", "effort", "fast", "reason"],
    "additionalProperties": False,
}

ROUTER_SYSTEM = """Eres la capa de ruteo de un harness de coding agent. Clasificas el prompt \
del usuario y eliges qué modelo Claude lo ejecuta. No resuelves la tarea.

Criterio:
- haiku: tareas mecánicas y de bajo riesgo. Parseo, extracción, clasificación, formateo,
  renombrar cosas, responder qué hace un archivo, comandos de shell de una línea.
- sonnet: ejecución de código bien especificada. Implementar una función descrita,
  escribir tests, refactors acotados a uno o dos archivos, fixes con causa raíz ya conocida.
- opus: ingeniería pesada. Diseño de arquitectura, planeación, debugging con causa
  desconocida, cambios multi-archivo, migraciones, code review profundo, decisiones
  con costo alto de error.

effort: 'low' para tareas cortas, 'medium' por defecto, 'high' o 'xhigh' para trabajo
agéntico y de codigo difícil. Ignorado si el tier es haiku.

fast: true solo si el tier es opus Y el usuario pide velocidad explícitamente o el
trabajo es interactivo y bloquea a una persona. Cuesta el doble; por defecto false.

Ante la duda entre dos tiers, elige el más barato salvo que el costo de equivocarse
sea alto (borrar datos, tocar producción, decisiones de arquitectura)."""


@dataclass
class Route:
    tier: str
    model: str
    effort: str
    fast: bool
    reason: str
    router_usage: object

    @property
    def price_key(self) -> str:
        return f"{self.model}:fast" if self.fast else self.model


def decide(client: anthropic.Anthropic, prompt: str) -> Route:
    """Una llamada a Haiku con structured output. Devuelve la ruta elegida."""
    response = client.messages.create(
        model=ROUTER_MODEL,
        max_tokens=512,
        system=[
            {
                "type": "text",
                "text": ROUTER_SYSTEM,
                "cache_control": {"type": "ephemeral"},  # el system prompt no cambia nunca
            }
        ],
        messages=[{"role": "user", "content": f"<prompt_a_rutear>\n{prompt}\n</prompt_a_rutear>"}],
        output_config={"format": {"type": "json_schema", "schema": ROUTE_SCHEMA}},
    )

    raw = next(b.text for b in response.content if b.type == "text")
    data = json.loads(raw)

    model, supports_effort, supports_fast = TIERS[data["tier"]]
    return Route(
        tier=data["tier"],
        model=model,
        effort=data["effort"] if supports_effort else "",
        fast=bool(data["fast"]) and supports_fast,
        reason=data["reason"],
        router_usage=response.usage,
    )


def cost(price_key: str, usage) -> float:
    inp, out = PRICING[price_key]
    cached = getattr(usage, "cache_read_input_tokens", 0) or 0
    written = getattr(usage, "cache_creation_input_tokens", 0) or 0
    return (
        usage.input_tokens * inp
        + cached * inp * 0.1
        + written * inp * 1.25
        + usage.output_tokens * out
    ) / 1_000_000
