# claude-router-poc

Harness mínimo estilo Claude Code con **intelligent model routing** local.

Invocás `bin/claude "<prompt>"` y antes de ejecutar nada, una llamada barata a
Haiku clasifica el prompt con **structured outputs** (JSON schema, no parseo de
texto libre) y decide tres cosas:

| campo    | valores                              | qué controla                      |
|----------|--------------------------------------|-----------------------------------|
| `tier`   | `haiku` / `sonnet` / `opus`          | qué modelo ejecuta                |
| `effort` | `low` / `medium` / `high` / `xhigh`  | profundidad de razonamiento       |
| `fast`   | `true` / `false`                     | fast mode (2.5x velocidad, 2x costo) |

Toda la lógica de ruteo vive in-house: es un `enum` en un schema y un system
prompt de 20 líneas. No hay third-party harness en el camino de la data.

## Setup

```sh
python3 -m venv .venv && .venv/bin/pip install anthropic
export ANTHROPIC_API_KEY=sk-ant-...
```

## Uso

Output real de tres corridas, de menor a mayor dificultad:

```sh
$ ./bin/claude "renombrá la variable x a userId en este snippet: const x = 1; console.log(x);"
┌ router → claude-haiku-4-5
└ Renombrado mecánico de variable en snippet simple, sin riesgo. No requiere
  reasoning profundo.
· 70 in / 21 out · ~$0.0012 (ruteo incluido)

$ ./bin/claude "escribí tests de pytest para una función suma(a, b), incluyendo casos borde"
┌ router → claude-sonnet-5 · effort=low
└ Implementación de tests unitarios para una función simple con casos borde bien
  especificados. Sonnet es suficiente; no requiere razonamiento profundo ni
  cambios multi-archivo.

$ ./bin/claude "diseñá la estrategia para migrar un monolito Django a event-driven con SQS"
┌ router → claude-opus-5 · effort=high
└ Diseño de arquitectura complejo que requiere decisiones de alto impacto sobre
  desacoplamiento, consistencia de datos y migración incremental de un sistema en
  producción. Necesita razonamiento profundo sobre tradeoffs.
· 97 in / 1055 out · ~$0.0280 (ruteo incluido)
```

Los tres tiers salieron bien a la primera, y el `effort` se movió solo: `low` para
los tests, `high` para la arquitectura. Ninguna de las tres corridas pidió fast
mode, que es lo correcto — ninguna tenía a alguien esperando del otro lado.

Al final imprime tokens y costo estimado — incluyendo el del ruteo, que es la
pregunta honesta: el clasificador cuesta ~$0.0003 por prompt, así que se paga
solo la primera vez que evita mandar un `git status` a Opus.

## Archivos

```
bin/claude          entrypoint
router/policy.py    schema de ruteo + system prompt del clasificador + pricing
router/run.py       arma los params por tier y ejecuta con streaming
```

## Detalles que importan

- **El schema es el contrato.** `output_config.format` con `enum` cerrado: el
  router no puede devolver un modelo que no existe. Sin regex, sin `if "opus" in
  respuesta`.
- **Cada tier acepta params distintos.** `effort` no existe en Haiku 4.5 (tira
  400). `speed: "fast"` sólo corre en Opus 5 / 4.8, vive en el endpoint beta y
  necesita el flag `fast-mode-2026-02-01`. `_build_params()` arma cada request
  según el tier elegido.
- **Prompt caching en el clasificador.** El system prompt del router nunca
  cambia, así que va con `cache_control` y a partir de la segunda llamada se lee
  a ~0.1x.
- **Sesgo al modelo barato.** Ante la duda el router baja de tier, salvo cuando
  el costo de equivocarse es alto (prod, borrar datos, arquitectura).

## Qué le falta para no ser PoC

Sin conversación multi-turno (cada invocación es one-shot), sin tools, sin
re-ruteo a mitad de tarea. El punto es mostrar que la capa de decisión son 100
líneas y un enum, no un harness entero.
