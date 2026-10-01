# Repetir la feature web-server con Spec Kit — plan del experimento

Objetivo: rehacer la misma feature (soporte web de `claude-tokens`) siguiendo el flujo de **Spec Kit**, partiendo del
commit previo a este trabajo, y comparar después los dos procesos. El flujo actual es SDD sin framework, en formato
Kiro (requirements → design → prototipo → tasks → código + tests) y está documentado en
[web-server-log.md](web-server-log.md). Al final hay que poder decidir cuál es más completo y aporta más valor, o si
alguno de los dos es demasiado simple o demasiado complejo.

Este documento es el plan de ejecución. Los resultados irán a otros dos ficheros: el log del experimento y la
evaluación (ver §6 y §7).

## 1. Roles

```
 Consola 1                                              Consola 2
 COORDINADOR  ◀──── mensajes entre sesiones ────▶  EJECUTOR
 sesión Claude Code en este repo                    sesión Claude Code en el worktree (3fb2a2f + Spec Kit)
 conoce: feature/web-server, specs, ADRs,           no ve nada de feature/web-server
 log, retrospectiva; hace de "usuario"              ejecuta /speckit-* e implementa
```

- **Coordinador:** una sesión de Claude Code abierta en este repo (`<repo>`).
  - Conoce el estado actual del proyecto: la rama `feature/web-server`, `specs/web-server/`, los ADRs, el log y su
    retrospectiva.
  - No implementa nada.
  - Prepara el entorno, lanza el ejecutor y le hace de **usuario**: responde a sus preguntas, revisa y aprueba sus
    documentos y lo reconduce cuando se desvía.
  - Escribe el log del experimento y la evaluación final.
- **Ejecutor:** una sesión de Claude Code **distinta**, en un worktree que parte del commit `3fb2a2f`.
  - Ejecuta los pasos de Spec Kit (`/speckit-*`) e implementa la feature.
  - No tiene acceso al contexto del coordinador ni a la rama `feature/web-server`.

### Por qué una sesión propia y no un subagente

1. **Las skills de Spec Kit se cargan desde el `.claude/` del directorio de trabajo.** Un subagente lanzado desde la
   sesión del coordinador trabaja con el `.claude/` del repo principal y no vería los comandos `/speckit-*` del
   worktree.
2. **Una sesión propia tiene su propio ID**, así que su coste se mide aparte con
   `python3 claude_tokens.py <session-id>`. Es el coste del proceso Spec Kit, sin el del coordinador.
3. **Aislamiento real:** el ejecutor no hereda nada de lo aprendido en la conversación original.

### Variante A (recomendada): dos consolas interactivas que se comunican por mensajes

- El usuario abre dos terminales (p. ej. dos ventanas de tmux):
  - **consola 1:** `claude` en este repo, que hace de coordinador;
  - **consola 2:** `claude` en `../claude-tokens-speckit`, que hace de ejecutor. Arranca **después** de la
    preparación de §2, para que cargue las skills de Spec Kit.
- Se comunican con los mensajes entre sesiones locales de Claude Code. Cada sesión ve a las demás con `ListAgents`
  (por nombre, p. ej. `<nombre-de-sesión>`) y les escribe con `SendMessage`. Comprobado el 2026-10-01: en esta máquina
  las sesiones interactivas en tmux aparecen en `ListAgents`.
- Ventajas:
  - el usuario ve las dos conversaciones en directo y puede intervenir;
  - el diálogo es de ida y vuelta (el ejecutor pregunta, espera la respuesta y sigue);
  - las peticiones de permiso salen en la consola del ejecutor, donde se ven.
- Coste: requiere tener las dos terminales abiertas durante todo el experimento. Las peticiones de permiso del
  ejecutor las aprueba el usuario, salvo que se arranque en modo auto.
- Nombres: al empezar, cada sesión ejecuta `ListAgents`, anota su propio nombre y el del otro, y lo deja escrito en
  el log del experimento.

### Variante B (desatendida): el coordinador lanza el ejecutor en modo headless

- `claude -p "<mensaje>" --output-format json --permission-mode <modo>` con `cwd` en el worktree; la respuesta JSON
  trae el `session_id`.
- Cada intercambio posterior es
  `claude -p --resume <session-id> "<respuesta del coordinador>" --output-format json`.
- Útil si el experimento tiene que correr sin nadie delante. Hay que fijar los permisos de antemano, y una denegación
  corta la llamada.

### Variante C (último recurso): subagente del coordinador

- Un subagente con `cwd` en el worktree que lee y sigue **a mano** los ficheros de comando de Spec Kit
  (`.claude/…/speckit-*`), porque no los tendrá cargados como skills.
- El coste se mide en `subagents/` de la sesión del coordinador.

## 2. Preparación del entorno (la hace el coordinador)

1. Crear el worktree **explícitamente** en el commit base. No usar `isolation: worktree`: en la ejecución original
   los tres worktrees arrancaron en un commit antiguo (`6f1d61e`).

   ```bash
   git worktree add ../claude-tokens-speckit -b speckit/web-server 3fb2a2f
   git -C ../claude-tokens-speckit log --oneline -1   # debe mostrar 3fb2a2f
   ```

2. Comprobar que el worktree **no contiene** `specs/`, `ctokens/`, `tests/`, `docs/` ni `CONTEXT.md`.
3. Instalar Spec Kit (requiere Python 3.11+: hay `python3.12` y `uv` 0.11.7):

   ```bash
   uv tool install specify-cli
   cd ../claude-tokens-speckit && specify init --help      # confirmar las opciones para un repo existente
   specify init --here --integration claude                # o el equivalente que muestre --help
   ```

4. Anotar la versión de Spec Kit, el commit base y la lista de comandos `/speckit-*` instalados.
5. Generar los prompts de cada fase con la skill **`speckit-prompts`**, pasándole como descripción de la feature
   **solo el prompt P1 literal** (modo ciego, §3). La skill ya usa los nombres actuales con guion
   (`/speckit-specify`…). Guardar los prompts generados en el log del experimento.
6. No hacer push de nada. El worktree es local.

## 3. Modo ciego y la "hoja de respuestas"

El experimento es **ciego**: el ejecutor solo recibe la petición original (P1). Lo que en el flujo actual se decidió o
se descubrió después, el coordinador **no lo adelanta**. Así se mide si Spec Kit lo encuentra por sí mismo.

La hoja de respuestas está en el índice de decisiones (D-001…D-043) y en las tablas de preguntas (Q1–Q29, RV, TV, OQ)
de [web-server-log.md](web-server-log.md).

### Reglas para responder a una pregunta del ejecutor

| Caso | Qué hace el coordinador | Etiqueta en el log |
|------|-------------------------|--------------------|
| La pregunta equivale a una decisión del usuario (p. ej. "¿solo localhost?" → D-008) | Responde **lo que respondió el usuario**, también cuando difería de la recomendación (Q5 todas las vistas, Q10 gráficos, Q17 auto-refresco, Q26 80 %…) | `hoja: D-xxx` |
| Pregunta sobre algo que aquí se **descubrió** después (el bug de recuento D-042, K-1, el 405 de `http.server`, el ciclo de imports, el color por versión) | No adelanta el hallazgo. Responde solo a lo que se pregunta, con la decisión que se tomó si la hubo | `hoja: D-xxx (descubierto por Spec Kit)` |
| Pregunta sin equivalente en el flujo actual | Responde según las preferencias que el usuario dejó claras (solo stdlib, Python 3.9+, reglas de commit y de comentarios, inglés en código y specs) | `inferida` |
| El ejecutor no pregunta algo que aquí sí se preguntó | No interviene en ese momento; lo anota para la evaluación | `no preguntado: Qxx` |

### Reglas al revisar un documento (spec, plan, checklist, tasks…)

| Divergencia frente a lo aprobado en el flujo actual | Acción |
|----------------------------------------------------|--------|
| De forma (estructura, nombres, formato de los criterios, idioma de las secciones) | Aceptar |
| De detalle técnico razonable (otra forma de la caché, otros nombres de módulo, otra ruta de la API) | Aceptar y anotarla para comparar |
| De **alcance o restricción** (faltan vistas o gráficos, añade autenticación, escucha fuera de 127.0.0.1, añade dependencias de Python, otra forma de arrancar que no sea `--serve`) | **Reconducir:** pedir el cambio citando la decisión del usuario ("el usuario decidió X porque Y") y no aprobar hasta que se corrija |
| Descubre algo que aquí no se vio | Aceptar si es correcto. Anotarlo como **ventaja de Spec Kit** |

Matiz sobre las decisiones que salieron de revisiones tardías, como incluir las librerías del navegador en el repo
(K-3 / ADR 0002): solo se aplican si el ejecutor llega al mismo punto (si plantea el riesgo del CDN, se responde
"incluirlas en el repo"). Si no lo plantea, no se impone; se anota como hueco.

### Intervenciones del usuario que hay que reproducir

En la ejecución original el usuario pidió cosas por iniciativa propia. Para que los dos escenarios sean comparables,
el coordinador las pide **en el mismo punto del proceso**:

| Original | En qué punto | Qué pide el coordinador |
|----------|--------------|-------------------------|
| P6 | Tras el plan, antes de tasks | "Antes de seguir, genera un prototipo visual de cada pantalla para revisarlo" |
| P8 | Tras tasks, antes de aprobarlas | "Analicemos los riesgos abiertos para dejarlo todo cerrado" (si `/speckit-analyze` o `/speckit-checklist` ya lo hicieron, se anota) |
| P10 | Al empezar la implementación | "Paraleliza lo que se pueda con varios agentes y termina sin preguntas" |

## 4. Fases y equivalencias

| # | Flujo actual | Spec Kit | El coordinador revisa contra |
|---|--------------|----------|------------------------------|
| 0 | Elección de framework (P1–P3) | — (fijado: Spec Kit) | — |
| 1 | Principios implícitos (CLAUDE.md, ADR 0001) | `/speckit-constitution` | Solo stdlib, Python 3.9+ en 3.9 y 3.12, sin comentarios obvios, commits de una línea sin trailers, `TODO JF:` |
| 2 | Entrevista Q1–Q18 + `requirements.md` (EARS) | `/speckit-specify` + `/speckit-clarify` | `specs/web-server/requirements.md` (R1–R11) y glosario `CONTEXT.md` |
| 3 | `design.md` + ADRs | `/speckit-plan` (plan, research, data-model, contracts, quickstart) | `specs/web-server/design.md`, ADR 0001/0002 |
| 4 | Prototipo (P6–P7) | Sin equivalente: lo pide el coordinador (§3) | `specs/web-server/prototype/ui-mock.html` |
| 5 | `tasks.md` + revisión de riesgos (P7–P8) | `/speckit-tasks`, `/speckit-checklist`, `/speckit-analyze` | `specs/web-server/tasks.md` (T0–T18, K-1…K-7) |
| 6 | Código + tests con 3 agentes (P9–P10) | `/speckit-implement` (+ `/speckit-converge` si aplica) | Comportamiento final (§7) |

Cada fase acaba con la **aprobación explícita del coordinador**, igual que el usuario aprobaba cada documento. No se
pasa a la fase siguiente sin ella.

## 5. Protocolo coordinador ↔ ejecutor

0. Canal: en la variante A, `SendMessage` entre las dos sesiones (por el nombre que da `ListAgents`). En la B,
   `claude -p --resume`. El contenido y las reglas son los mismos en ambas.
1. Cada mensaje al ejecutor es **una sola fase o una sola respuesta**, nunca varias.
2. El ejecutor termina cada turno enviando al coordinador uno de estos tres estados:
   - `PREGUNTAS:` una lista numerada;
   - `REVISIÓN:` las rutas de los documentos que hay que revisar;
   - `HECHO:` resumen y commits.

   Esto se le pide en el primer mensaje.
3. El coordinador responde siguiendo §3, y siempre registra en el log del experimento:
   - qué preguntó o entregó el ejecutor;
   - la respuesta y su etiqueta;
   - las divergencias encontradas.
4. Antes y después de cada fase, el coordinador mide el coste de la sesión del ejecutor.
5. Si el ejecutor se bloquea por permisos (como la descarga de licencias en la ejecución original), el coordinador
   **no** hace la acción por él: la anota como "pendiente del usuario" igual que entonces.
6. En la variante A, el ejecutor **no** lee ficheros fuera de su worktree, aunque estén en la misma máquina (en
   especial `../claude-tokens/`), y el coordinador no le envía ficheros de `feature/web-server`, solo respuestas.
   Una petición del ejecutor de ver "cómo se hizo antes" se rechaza y se anota.
7. Límite de seguridad: si el coste del ejecutor pasa del doble de la ejecución original ($25.46 → $50), el
   coordinador para y deja el estado documentado.

## 6. Qué se registra

- **`docs/sdd-learning/speckit-replay-log.md`** (lo escribe el coordinador), con el mismo formato que
  `web-server-log.md`:
  - por cada intercambio: el mensaje literal del coordinador, el valor para SDD y la tabla de preguntas con su
    columna de etiqueta (`hoja` / `inferida` / `reconducción` / `no preguntado`);
  - los supuestos del ejecutor;
  - el coste por fase;
  - el índice de divergencias.
- **Artefactos de Spec Kit:** en el worktree, rama `speckit/web-server`, commiteados por el ejecutor con las mismas
  reglas de commit.
- **IDs de sesión:** el del coordinador y el del ejecutor, para medir los costes por separado.

## 7. Evaluación final

Al terminar la implementación, el coordinador escribe `docs/sdd-learning/sdd-vs-speckit-evaluation.md`, y la
decisión la toma el usuario. Criterios, con la evidencia de cada uno en ambos procesos:

| # | Criterio | Cómo se mide | Evidencia en el flujo actual |
|---|----------|--------------|------------------------------|
| C1 | Completitud de la especificación | Requisitos verificables, casos límite, NFR y seguridad (path traversal, DNS rebinding, XSS, CSP) | requirements R1–R11 |
| C2 | Calidad de las preguntas | Cuántas de Q1–Q29 hizo Spec Kit, cuántas nuevas y útiles, y cuántas respondió el coordinador sin que se las hicieran | Tablas de preguntas del log |
| C3 | Hallazgos y en qué fase | Para cada fila de la tabla 2 de la retrospectiva (bug D-042, K-1, 405, túnel, ciclo de imports, `</script>`, color por versión…): ¿lo encontró y en qué fase? Cuanto antes, mejor | Retrospectiva §2 |
| C4 | Retrabajo | Enmiendas a documentos ya aprobados, goldens regenerados fuera de lo previsto, commits de corrección | Enmiendas R1.4, R2.8, R5.5, R7.7, §2, ADR 0002 |
| C5 | Trazabilidad | Requisito → diseño → tarea → test; decisiones con su motivo (ADRs) | Tablas de trazabilidad, índice D-xxx |
| C6 | Esfuerzo del usuario | Número de intervenciones del coordinador como usuario, reconducciones y aprobaciones | P1–P10, 29 preguntas |
| C7 | Coste | Tokens y $ por fase, medidos con `claude_tokens.py` | Tabla de coste por fase ($11.03 especificar + prototipo, $14.43 implementar) |
| C8 | Calidad del resultado | Tests en 3.9 y 3.12; checklist M1–M13; datos reales (≤ 5 s / < 1 s en totales, paridad con el CLI, 25.092 llamadas a herramientas); seguridad (403/404/405/409) | T18 en el log |
| C9 | Peso del proceso | Número y tamaño de los artefactos, ceremonias obligatorias, partes que no aportaron | Specs + log + prototipo |

Puntuación: de 1 a 5 por criterio y proceso, con una frase de justificación y un enlace a la evidencia. El documento
debe cerrar con una recomendación argumentada:
- **adoptar Spec Kit**;
- **mantener el flujo actual**;
- **un híbrido**, por ejemplo Spec Kit más la fase de prototipo y la validación del comportamiento existente con
  datos reales.

También debe indicar en qué tipo de feature conviene cada uno (un PoC pequeño frente a un componente del monorepo).

La comparación de C8 es **de caja negra**: los tests de `feature/web-server` dependen de los nombres de módulo de
`ctokens/` y no se pueden reutilizar tal cual. Se comparan el CLI (si Spec Kit lo mantiene), las rutas HTTP
equivalentes y la checklist manual.

## 8. Riesgos del experimento

| Riesgo | Mitigación |
|--------|------------|
| El coordinador filtra conocimiento (contaminación) | Reglas de §3; cada respuesta lleva etiqueta y se puede auditar en el log |
| El worktree arranca en otro commit | Crearlo a mano en `3fb2a2f` y comprobarlo (§2) |
| Las opciones de `specify init` o los nombres de los comandos han cambiado | Confirmar con `--help` y anotar la versión |
| Permisos en modo headless | `--permission-mode` adecuado; plan B con subagente (§1) |
| Comparación injusta por el orden: Spec Kit juega con ventaja porque el coordinador ya conoce las respuestas | Medir aparte las preguntas que el coordinador contestó sin que se las hicieran; puntuar C2/C3 solo por lo que Spec Kit preguntó o encontró por sí mismo |
| Coste desbocado | Límite de $50 en el ejecutor (§5) |
| Variante A: el ejecutor, en la misma máquina, puede leer `../claude-tokens/` (la rama con la solución) | Regla 6 de §5 en su prompt de arranque; el coordinador revisa en su transcripción que no lo haya hecho y, si lo hizo, lo anota como contaminación |
| Variante A: un mensaje llega cuando la otra sesión ya no está esperando, o una sesión se cierra | Cada mensaje lleva la fase y el número de intercambio; si una sesión se cierra, se reanuda con `claude --resume <id>` en la misma consola y se reenvía el último mensaje |

## 9. Prompts de arranque

### Coordinador (consola 1, en este repo)

> Eres el coordinador del experimento descrito en `docs/sdd-learning/speckit-replay-plan.md`. Lee entero ese plan,
> `docs/sdd-learning/web-server-log.md` (índice de decisiones, tablas de preguntas y retrospectiva),
> `specs/web-server/` y `docs/adr/`.
> 1. Prepara el entorno (§2).
> 2. Genera los prompts con la skill `speckit-prompts` a partir solo del prompt P1 literal.
> 3. Usa la variante A: cuando el usuario arranque el ejecutor en la consola 2, localízalo con `ListAgents`,
>    envíale el primer mensaje (P1 literal + el protocolo de §5) y llévalo fase a fase (§4, §5), respondiendo con
>    las reglas de §3. Si no aparece en `ListAgents`, usa la variante B.
> 4. Registra todo en `docs/sdd-learning/speckit-replay-log.md`.
> 5. Al terminar la implementación, escribe `docs/sdd-learning/sdd-vs-speckit-evaluation.md` (§7).
>
> No preguntes al usuario salvo que un bloqueo de permisos lo exija, y no hagas push.

### Ejecutor (consola 2, en `../claude-tokens-speckit`, después de la preparación de §2)

> Eres el ejecutor de un experimento de Spec Kit. Tu "usuario" es otra sesión de Claude Code, el coordinador;
> localízalo con `ListAgents` y comunícate con él solo por `SendMessage`.
> - Trabaja únicamente en este directorio; no leas nada fuera de él.
> - Sigue el flujo de Spec Kit con los comandos `/speckit-*` en el orden que te indique el coordinador, una fase cada
>   vez.
> - Termina cada fase enviándole `PREGUNTAS:`, `REVISIÓN:` (con las rutas de los documentos) o `HECHO:` (resumen y
>   commits), y espera su respuesta antes de continuar.
> - Commits: un commit por tarea, mensaje de una línea, sin trailers ni Co-Authored-By. No hagas push.
> - Si te bloquea un permiso, díselo al coordinador; no busques otra vía.
>
> Empieza enviándole un mensaje con tu nombre de sesión y la salida de `git log --oneline -1`.
