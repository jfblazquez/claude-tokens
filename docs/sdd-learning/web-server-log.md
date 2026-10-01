# Log de aprendizaje SDD — feature web-server

Registro del proceso SDD (requirements → design → tasks → código + tests) para la feature de soporte web de
`claude-tokens`. **No es un artefacto SDD**: no lo lee ningún agente como spec. Sirve para revisar después el
proceso y adaptarlo a Spec Kit.

Por cada prompt se guarda: el texto literal, lo que aportó a la spec, las preguntas hechas al usuario (con la
recomendación dada y si se respondió), los supuestos tomados sin preguntar y las decisiones. La sección
*Retrospectiva* se rellena al final para detectar respuestas (o silencios) que llevaron a un sitio equivocado o
dejaron detalles sin cubrir.

Estados de una pregunta: `respondida` · `aceptó recomendación` · `sin respuesta` · `respondida implícitamente`.

**Sesión de Claude Code:** `12705f59-8c42-4e70-9995-c14a7cd9ac98` (proyecto `claude-tokens`).

## Coste por fase

Medido con `python3 claude_tokens.py <session-id>` al cerrar cada fase; el delta es lo consumido en esa fase.

| Fase | Prompts | Tokens acumulados | Coste acumulado | Delta coste |
|------|---------|-------------------|-----------------|-------------|
| Preparación + entrevista | P1–P3 (Q1–Q18) | 7.448.334 | $4.82 | $4.82 |
| requirements.md | P3 (tras Q18) – P4 | 9.177.523 | $5.67 | $0.85 |
| design.md | P4 (tras aprobar requirements) – P5 | 11.594.287 | $6.93 | $1.26 |
| Prototipo visual | P6–P7 | 15.222.282 | $9.28 | $2.35 |
| tasks.md (+ revisión de riesgos) | P7 (tras Q24) – P9 | 20.093.268 | $11.03 | $1.75 |
| Código + tests (T0–T17, T18 parcial) | P9–P10 | 67.012.849 (incluye 3 subagentes) | $25.46 | $14.43 (coordinador ≈ $7.04; Core $1.39, Server $2.03, UI $3.97) |

## Índice de decisiones

| ID | Decisión | Origen | Fase |
|----|----------|--------|------|
| D-001 | Hacer SDD sin framework, con el formato de Kiro (requirements.md / design.md / tasks.md + EARS) | P3 | Preparación |
| D-002 | Mantener un log de aprendizaje separado de los artefactos SDD | P3 | Preparación |
| D-003 | Ubicación: specs en `specs/web-server/`, log en `docs/sdd-learning/`, glosario en `CONTEXT.md`, ADRs en `docs/adr/`; todo versionado | P3 · Q1 | Preparación |
| D-004 | El log registra el ID de sesión y el coste por fase medido con la propia herramienta | P3 · Q2 | Preparación |
| D-005 | El servidor ofrece una API JSON (mismos datos que `--json`) y una UI web que la consume | P3 · Q3 | Requisitos |
| D-006 | Término canónico "Conversation" (JSONL principal + subagentes); "session" queda en _Avoid_ | P3 · Q4 | Glosario |
| D-007 | Alcance v1: listado, informe de uso, totales **y** vistas de contenido (last-response, bash, files) | P3 · Q5 | Requisitos |
| D-008 | Acceso: solo 127.0.0.1, sin autenticación; acceso remoto con túnel SSH; exponer a la red queda fuera de alcance | P3 · Q6 | Requisitos |
| D-009 | Solo librería estándar en Python; JS de navegador por CDN permitido; sin build (ADR 0001) | P3 · Q7 | Arquitectura |
| D-010 | NFR de frescura: datos actuales en cada petición; primera carga de totales ≤ ~5 s, siguientes < 1 s si no hay cambios | P3 · Q8 | Requisitos |
| D-011 | Arranque con `--serve [--port]` en el mismo script, reutilizando las opciones globales | P3 · Q9 | Requisitos |
| D-012 | UI v1 enriquecida: paridad con la consola + ordenación/filtrado + navegación + gráficos | P3 · Q10 | Requisitos |
| D-013 | Gráficos v1: coste diario (cálculo nuevo), reparto por modelo, coste por project, actividad diaria + herramientas/skills | P3 · Q11 | Requisitos |
| D-014 | "Day" = día natural UTC en CLI y web, etiquetado "UTC" | P3 · Q12 | Glosario |
| D-015 | El coste diario se calcula en el núcleo y sale en `--totals --json` y en la API; la salida de texto de `--totals` no cambia | P3 · Q13 | Requisitos |
| D-016 | Las vistas bash/files incluyen los subagentes (con su origen) en CLI y web; last-response sigue siendo solo del log principal | P3 · Q14 | Requisitos |
| D-017 | Last-response en la UI: Markdown completo (marked) saneado (DOMPurify) y **resaltado de sintaxis en bloques de código** | P3 · Q15 | Requisitos |
| D-018 | Tests: unittest stdlib, fixtures JSONL sintéticas, integración HTTP con el servidor real; UI con checklist manual | P3 · Q16 | Requisitos |
| D-019 | UI: botón Refrescar + hora de la última carga + interruptor de auto-refresco opcional | P3 · Q17 | Requisitos |
| D-020 | Seguridad obligatoria: ids solo con formato UUID dentro de la carpeta de projects (anti path traversal/glob), validación de la cabecera Host (anti DNS rebinding), escapado + SRI (anti XSS), solo GET | P3 · Q18 | Requisitos |
| D-021 | Supuestos por defecto: puerto 8765 y error si está ocupado; UI en inglés; auto-refresco 30 s desactivado por defecto; id ambiguo → 409; README actualizado | P3 · Q18 | Requisitos |
| D-022 | Fuera de alcance v1: red/autenticación, HTTPS, varios usuarios, escrituras, zona horaria configurable, e2e de navegador, exportar | P3 · Q18 | Requisitos |
| D-023 | R7.3: una entrada por fichero con conteos agregados de todas las fuentes y la lista de fuentes | P4 | Requisitos |
| D-024 | R6.4: registros sin timestamp en un bucket "undated" | P4 | Requisitos |
| D-025 | R9.2/R9.3: umbrales de rendimiento verificados manualmente; los tests solo comprueban que no se re-parsean logs sin cambios | P4 | Requisitos |
| D-026 | requirements.md aprobado | P4 | Requisitos |
| D-027 | `--serve` admite solo `--port` + opciones de configuración (`--projects-dir`, `--pricing`, `--cold-summary-output`, `--context-window`); el resto es error. R1.4 se mantiene | P5 · Q19 | Requisitos |
| D-028 | JSON de `--bash`/`--files` con campos nuevos (`source`, `timestamp`, `sources`) y orden cronológico; el formato JSON no está cerrado | P5 | Diseño |
| D-029 | Dividir el PoC en el paquete `ctokens/` con lo nuevo en módulos separados; antes, tests de caracterización (R10.7) | P5 · Q20 | Diseño |
| D-030 | Chart.js aceptado; nuevo R11 de diseño visual: color estable por modelo, claro/oscuro, tokens CSS, números tabulares, estados de carga/error, ≥ 768 px | P5 · Q21 | Requisitos |
| D-031 | design.md aprobado con las respuestas de la revisión integradas | P5 | Diseño |
| D-032 | Fase de prototipo visual entre design y tasks (`specs/web-server/prototype/ui-mock.html`) | P6 | Prototipo |
| D-033 | §8.4: dentro de una familia, la versión más nueva lleva el color base y las anteriores, tintes más claros | P7 · Q22 | Diseño |
| D-034 | Prototipo aprobado tal cual como referencia visual (pantallas, estados, temas, textos) | P7 · Q23 | Prototipo |
| D-035 | El prototipo se queda en `specs/web-server/prototype/` en main (no en rama desechable) | P7 · Q24 | Prototipo |
| D-036 | Commits autorizados: uno por tarea (TV1); T3 con un commit por módulo movido (TV2) | P8 | Tareas |
| D-037 | K-1: goldens estables (entorno fijado, `<FIXTURES>`, encabezado de la ayuda normalizado) | P8 | Riesgos |
| D-038 | K-2: cobertura de la caracterización ≥ 80 % de líneas con `trace` | P8 · Q25–Q26 | Riesgos |
| D-039 | K-3: librerías del navegador incluidas en el repo (ADR 0002); CSP solo `'self'`; R2.8 enmendado | P8 · Q27 | Riesgos |
| D-040 | K-4 cerrado con evidencia (Chart.js solo usa CSSOM); K-5 aceptado (0 avisos en 725 logs); K-6 mitigado; K-7 aceptado | P8 · Q28 | Riesgos |
| D-041 | tasks.md aprobado; empieza la implementación (T0…) | P9 | Tareas |
| D-042 | Bug encontrado en T1: `--totals` solo cuenta el 21 % de las llamadas a herramientas. Se corrige en esta feature (T5b, R5.5, R7.7) | P9 · Q29 | Implementación |
| D-043 | Implementación en paralelo: esta sesión coordina; agentes Core (T4–T7), Server (T8–T12) y UI (T13–T16) en worktrees aislados, con ficheros asignados en exclusiva; sin preguntas al usuario | P10 | Implementación |

---

## P1 — 2026-10-01 — Planteamiento y evaluación de frameworks

**Prompt (literal):**

> Quiero preparar una nueva feature para dar soporte web a esta herramienta. Un proceso server que pueda dar la
> información que se está mostrando ahora en consola. Quiero hacer un flujo sdd con
> requirements.md-design.md-tasks.md-codigo+test. Algo similar a este proceso
> https://claude.ai/artifact/GJu35ea23uwxENcatVx3vd. Antes de empezar debes saber que no
> es un flujo al que estoy muy acostumbrado. Creo que me vendría bien unsar un framework, open source y grauito, y
> que sea sencillo de empezar a usar, vamos a valorar opciones de framework, o directamente ver si trabajamos sin el

**Valor generado para SDD:**
- Alcance inicial de la feature: un proceso servidor que exponga lo que hoy muestra la consola.
- Proceso de referencia identificado: la guía enlazada describe el flujo de Kiro (requirements / design / tasks)
  con requisitos en EARS y revisión humana antes de codificar.
- Comparativa de frameworks: Spec Kit, OpenSpec, Kiro (descartado por no ser open source), BMAD y sin framework.
- Recomendación: sin framework para esta feature; Spec Kit para el monorepo más adelante.

**Preguntas al usuario:**

| # | Pregunta | Recomendación | Respuesta | Estado |
|---|----------|---------------|-----------|--------|
| — | ¿Sin framework y empiezo con `requirements.md`, o probar Spec Kit / OpenSpec ya? | Sin framework | Contestada en P3 | respondida (en P3) |

**Supuestos sin preguntar:**
- "Lo que se muestra en consola" = los modos documentados en el README (selector de conversaciones, informe de una
  conversación, `--totals`). No se revisaron entonces los modos sin documentar (`--last-response`, `--bash`,
  `--files`).
- El entorno no limita la elección del framework (comprobado: Node 24, uv, Python 3.12).

**Retrospectiva:** _pendiente_

---

## P2 — 2026-10-01 — Comparativa con GSD Core

**Prompt (literal):**

> Y comparando con gsd core?

**Valor generado para SDD:**
- GSD Core analizado (fork comunitario de "Get Shit Done"): es un orquestador de contexto con subagentes y no
  produce un design.md revisable. Descartado para esta feature por coste en tokens, poca visibilidad del proceso y
  dudas de confianza sobre el proyecto.
- La recomendación no cambia.

**Preguntas al usuario:**

| # | Pregunta | Recomendación | Respuesta | Estado |
|---|----------|---------------|-----------|--------|
| — | ¿Empiezo con el borrador de `requirements.md`? | Sí | Contestada en P3 (antes, entrevista) | respondida (en P3) |

**Supuestos sin preguntar:**
- "gsd core" = `open-gsd/gsd-core`, continuación de `gsd-build/get-shit-done`.

**Retrospectiva:** _pendiente_

---

## P3 — 2026-10-01 — Decisión sin framework + log de aprendizaje + entrevista

**Prompt (literal):**

> /grill-with-docs vamos sin framework, además de los ficheros que vamos a crear md, quiero guardar un fichero con
> las decisiones que se van tomando para aprender del proceso, no será usado para SDD, más bien como archivo de
> aprendizaje para luego adaptar el flujo a speckit. Quiero que guardes cada prompt que hagamos, lo que genera ese
> prompt de valor para SDD , que preguntas se hacen al usuario y cuales se responden o no, luego queremos ver si por
> alguna respuesta (o no contestación) se llego al sitio equivocado o no se cubrió algún detalle.

**Valor generado para SDD:**
- D-001, D-002 y D-003 (ver índice).
- Arranca una entrevista (grilling + modelado de dominio) antes de escribir `requirements.md`: una pregunta cada
  vez, con recomendación, y glosario en `CONTEXT.md` a medida que se fijan términos.

**Preguntas al usuario:**

| # | Pregunta | Recomendación | Respuesta | Estado |
|---|----------|---------------|-----------|--------|
| Q1 | ¿Dónde viven los artefactos SDD y el log? | A: `specs/web-server/` + `docs/sdd-learning/`, todo en git | A | aceptó recomendación |
| Q2 | ¿Formato del log? | A: formato propuesto + ID de sesión + coste por fase | A | aceptó recomendación |
| Q3 | ¿Qué ofrece el servidor: API, UI o ambas? | A: API JSON + UI web | A | aceptó recomendación |
| Q4 | ¿Término para la unidad analizada: Conversation o Session? | A: Conversation | A | aceptó recomendación |
| Q5 | ¿Qué vistas de la consola entran en v1? | Listado + informe + totales; contenido en v2 | Las cuatro, contenido incluido | respondida (difiere de la recomendación) |
| Q6 | ¿Quién accede al servidor? | A: solo localhost, sin auth, túnel SSH | A | aceptó recomendación |
| Q7 | ¿La parte web mantiene cero dependencias? | A: solo stdlib + ADR | A | aceptó recomendación |
| Q8 | ¿Frescura y tiempo de respuesta? | A: siempre fresco, primera carga lenta, siguientes < 1 s | A | aceptó recomendación |
| Q9 | ¿Cómo se lanza el servidor? | A: `--serve` en el mismo script | A | aceptó recomendación |
| Q10 | ¿Nivel de UX de la UI v1? | A: paridad + ordenación + navegación, sin gráficos | C: enriquecida con gráficos | respondida (difiere de la recomendación) |
| Q11 | ¿Qué gráficos entran en v1? | Coste diario + reparto por modelo + coste por project | Los cuatro (incluye actividad y herramientas) | respondida (amplía la recomendación) |
| Q12 | ¿Qué es un "día" para los gráficos? | A: UTC en todas partes, etiquetado | A | aceptó recomendación |
| Q13 | ¿El coste diario sale también en el texto de `--totals`? | A: solo en `--json` (por D-005) | A | aceptó recomendación |
| Q14 | ¿bash/files deben incluir los subagentes? | A: sí, en CLI y web, marcando el origen | A | aceptó recomendación |
| Q15 | ¿Cómo se pinta el Markdown de last-response? | A: marked + DOMPurify por CDN | A + resaltado de sintaxis | respondida (añade un detalle no ofrecido) |
| Q16 | ¿Estrategia de tests? | A: unittest stdlib + checklist manual de UI | A | aceptó recomendación |
| Q17 | ¿La UI se refresca sola? | A: botón + hora visible, sin sondeo | B: + auto-refresco opcional | respondida (difiere de la recomendación) |
| Q18 | ¿Confirmas seguridad, supuestos por defecto y fuera de alcance? | Confirmar | Confirmado | aceptó recomendación |

**Tras Q18 — borrador de `specs/web-server/requirements.md`** (R1–R10, EARS, trazado a D-xxx, con 3 preguntas
abiertas para la revisión).

Supuestos y correcciones al redactar:
- Specs en inglés, como el código, el README y `CONTEXT.md`. **No se preguntó.**
- Verificado que los 387 conversation ids de primer nivel son UUID, así que la validación de R2.4 no excluye
  ninguno.
- **Autocorrección R2.2:** la primera versión exigía `Host: localhost:<puerto del servidor>`; un túnel a otro
  puerto local (`ssh -L 9000:localhost:8765`) habría dado 403. Ahora se valida solo el nombre del host.
- **Autocorrección R1.4:** `--project` global chocaba con el filtro por petición (R3.3/R5.2); se quitó de R1.4.
- Detalles no cubiertos en la entrevista que han salido al redactar (en la sección *Open questions*): ficheros
  tocados por varias fuentes (R7.3), registros sin timestamp en el coste diario (R6.4) y cómo verificar los umbrales
  de rendimiento (R9). Lección: la redacción en EARS fuerza casos límite que la entrevista no detectó.
- Los timestamps de la API y de la UI van en UTC (coherente con D-014). No se preguntó.

**Supuestos sin preguntar:**
- El log se escribe en español, como la conversación.
- Las preguntas de la entrevista se numeran de forma global (Q1, Q2…) para referenciarlas en la retrospectiva.
- "Project" = el `cwd` real que guarda el log (`project_path_of`), con el nombre codificado de la carpeta como
  respaldo. Se tomó del código sin preguntar. Riesgo: si el `cwd` cambia dentro de una conversación, solo cuenta el
  primero.
- El glosario `CONTEXT.md` se escribe en inglés (como el código y el README); el log, en español.
- Q6 se reordenó por la respuesta a Q5: al entrar las vistas de contenido, el modelo de acceso pasó a ser crítico.
  El orden de las preguntas lo marca la propia conversación.
- Q8 se apoyó en una medición real, no en una suposición: 521 MB / 725 JSONL, `--totals` 4,2 s, listado 0,16 s
  (2026-10-01). Los umbrales del NFR salen de ahí.
- **Error de la recomendación en Q10:** la opción C mencionaba "coste por día" como si existiera, pero el código solo
  cuenta respuestas por día (`daily`). Se detectó al revisar el código antes de Q11 y se avisó al usuario. Lección:
  comprobar en el código lo que describe una opción *antes* de ofrecerla.
- **Contradicción glosario ↔ código detectada antes de Q14:** "Conversation" incluye los subagentes, pero
  `--bash`/`--files`/`--last-response` solo leían el log principal. Salió al contrastar el glosario con `main()`.
  Sin el glosario no se habría detectado. Consecuencia: la feature web incluye también una corrección del CLI.
- Q17 no fijó ni el intervalo ni el estado inicial del auto-refresco. Supuesto: 30 s y **desactivado por defecto**
  (confirmado en Q18).
- **Hallazgos de seguridad sin preguntar (presentados en bloque en Q18):** `resolve_conversation` acepta rutas de
  fichero arbitrarias e interpola el id en un `glob`; si la API lo usara tal cual habría path traversal. A eso se
  suman DNS rebinding y XSS. Se confirmaron en una sola pregunta de "confirmar todo". Riesgo para la retrospectiva:
  una confirmación en bloque puede esconder un punto que el usuario no leyó con detalle.
- Coste: la propia medición con la herramienta incrementa el coste de la sesión (cada llamada añade tokens). El
  JSON y el texto, medidos con segundos de diferencia, no coinciden exactamente.
- **Patrón observado:** en las preguntas de selección múltiple (Q5, Q11) el usuario marcó todas las opciones. Las
  preguntas "elige varias" tienden a ampliar el alcance. Revisar en la retrospectiva si v1 quedó demasiado grande.

**Retrospectiva:** _pendiente_

---

## P4 — 2026-10-01 — Revisión y aprobación de requirements.md

**Prompt (literal):**

> Revisado requirements.md y acorde. Puntos:
> 7.3: una fila para el agregado
> 6.4 un bucket sin fecha
> 9.2 9.3 se verificará manualmente

**Valor generado para SDD:**
- requirements.md aprobado (D-026). Las tres preguntas abiertas se resolvieron e integraron en R7.3, R6.4 y R9.2/R9.3
  (D-023 a D-025). La sección *Open questions* pasa a *Resolved during review*.
- Arranca la fase de design.md.

**Preguntas al usuario:**

| # | Pregunta | Recomendación | Respuesta | Estado |
|---|----------|---------------|-----------|--------|
| OQ1 | R7.3: ¿una fila por fichero o por (fichero, fuente)? | Una por fichero, con conteos agregados y lista de fuentes | Una fila, agregada | aceptó recomendación |
| OQ2 | R6.4: ¿bucket "undated" o excluir? | Bucket "undated" | Bucket sin fecha | aceptó recomendación |
| OQ3 | R9.2/R9.3: ¿verificación manual? | Manual + test de "no re-parsear" | Manual | aceptó recomendación |
| — | Specs en inglés (supuesto avisado en el resumen de P3) | Inglés | No comentado | sin respuesta (se mantiene inglés) |

**Supuestos sin preguntar:**
- "Revisado y acorde" se toma como aprobación de todo el documento, incluido lo que no se comentó (p. ej. los
  códigos HTTP 403/404/405/409, el puerto 8765 y el idioma inglés).

**Tras la aprobación — borrador de `specs/web-server/design.md`** (§1–§10 + 4 puntos de revisión RV1–RV4).

Hechos verificados antes de diseñar (no se preguntaron):
- El `python3` del sistema es 3.9.21, así que el objetivo es 3.9+ (`ThreadingHTTPServer`, `Path.is_relative_to`).
- `http.server` responde 501 a los métodos sin `do_X`, pero R2.3 pide 405; el diseño lo resuelve con
  `__getattr__`. Sin leer el código de la stdlib, el test de "método arbitrario → 405" habría fallado en la
  implementación.
- `accumulate_file` muta acumuladores compartidos y no se puede cachear; se rediseña como `file_stats` pura.
- El CLI no tiene salida JSON para el listado, así que la forma JSON de R3 la define el diseño (`conversation_rows`).

Decisiones de diseño tomadas por el asistente (pendientes de la revisión del usuario):
- Separar ficheros: `claude_tokens_web.py` + `web/` (RV1).
- Orden cronológico entre fuentes en `--bash` y campos JSON nuevos (RV2). Ni R7.2 ("in order") ni la entrevista
  fijaron el orden; es un hueco de requisitos que se ha rellenado en el diseño.
- Chart.js (RV3); `--project` con `--serve` es un error (RV4).
- Extras de defensa en profundidad no pedidos en los requisitos: CSP, `nosniff`, `no-referrer`, comprobación de
  symlinks con `is_relative_to`.
- Top 15 en los gráficos de projects y herramientas, igual que el CLI.

**Retrospectiva:** _pendiente_

---

## P5 — 2026-10-01 — Revisión de design.md

**Prompt (literal):**

> RV1 : claude_tokens.py nació como poc por lo tanto es viable separar su comportamiento en partes y añadir
> funcionalidad nueva en ficheros separados, de hecho es recomendable para no terminar con ficheros grandes
> RV2: Es una decisión correcta, el formato json no está cerrado y puede incluir campos nuevos
> RV3: Es viable usar librerias externas como Chart.js para generar los gráficos, da seguridad, facilidad de uso y
> permite centrarse más en la usabilidad y un diseño visual coherente, moderno y atractivo.
> RV4: Es correcto, --serve sirve para habilitar el servidor, no admite otros parametros que no sea port
>
> El diseño es adecuado

**Valor generado para SDD:**
- RV2 y RV3 aceptados. RV3 añade una expectativa nueva sobre la UI ("coherente, moderno y atractivo") que no está
  en los requisitos y no es verificable tal cual.
- RV1 aceptado, y además abre la puerta a dividir el código existente, no solo a poner lo nuevo en ficheros nuevos.
- RV4 aceptado con una regla más estricta que la del diseño: "--serve no admite otros parámetros que no sea port".
  **Contradice R1.4 (aprobado)**, que aplica `--projects-dir`, `--pricing`, `--cold-summary-output` y
  `--context-window` al servidor.

**Preguntas al usuario:**

| # | Pregunta | Recomendación | Respuesta | Estado |
|---|----------|---------------|-----------|--------|
| RV1 | ¿Separar en varios ficheros? | Sí (servidor + `web/` aparte) | Sí, y dividir también el PoC | respondida (amplía la recomendación) |
| RV2 | ¿Campos JSON nuevos y orden cronológico? | Sí | Sí, el JSON no está cerrado | aceptó recomendación |
| RV3 | ¿Chart.js? | Sí | Sí + expectativa de diseño visual | respondida (añade un requisito implícito) |
| RV4 | ¿`--project` con `--serve` es error? | Sí | Sí, y "solo admite --port" | respondida (contradice R1.4) |
| Q19 | ¿Qué opciones acepta `--serve`? (resolver la contradicción con R1.4) | A: `--port` + configuración | A | aceptó recomendación |
| Q20 | ¿Dividir el código existente en esta feature? | A: paquete, con tests de caracterización primero | A | aceptó recomendación |
| Q21 | ¿Criterios concretos de "coherente, moderno y atractivo"? | A: escritorio + claro/oscuro | A | aceptó recomendación |

**Supuestos sin preguntar:**
- Nombre del paquete `ctokens/` (no puede ser `claude_tokens/` por el choque con `claude_tokens.py`). Solo
  apareció en el preview de Q20; no se discutió aparte.
- Mapa de funciones a módulos, el renombrado `text` → `report_text` y la dirección de dependencias (§2 del
  diseño).
- Tests de caracterización con `TZ=UTC` y mtimes fijos: el selector usa `datetime.fromtimestamp` (hora local), así
  que sin eso los goldens dependerían de la máquina.
- Paleta de 8 colores con huecos fijos por familia de modelo (§8.4).
- design.md se marca como aprobado aunque §2, §8.4 y §9 se reescribieron **después** de "El diseño es adecuado".
  Esos apartados recogen decisiones del usuario (Q20, Q21), pero el usuario no ha leído ese texto concreto.

**Observaciones:**
- RV4 mostró por qué hay que contrastar cada respuesta con lo ya aprobado. "Solo admite --port" se escribió
  pensando en las opciones de modo, pero leído al pie de la letra habría eliminado `--pricing` y `--projects-dir`
  y roto R1.4.
- RV3 mostró que una respuesta de revisión puede traer un requisito nuevo sin presentarlo como tal ("diseño visual
  coherente, moderno y atractivo"). Se convirtió en R11 con criterios verificables.
- RV1 amplió el alcance otra vez (ahora también hay que refactorizar el PoC). Se mitigó ordenando el trabajo: los
  tests de caracterización van primero.
- Q21 se planteó a propósito como selección única por el patrón de selección múltiple observado en P3.

**Retrospectiva:** _pendiente_

---

## P6 — 2026-10-01 — Prototipo visual de cada pantalla (antes de tasks.md)

**Prompt (literal):**

> Leídas las nuevas decisiones, en principio correctas.  Antes de seguir quiero que se genere un prototipado mock
> de cada pantalla  para revisar visualmente lo que se espera que salga como salida en el navegador

**Valor generado para SDD:**
- Confirmación de §2, §8.4 y §9 del diseño (el "aprobado" de P5 queda respaldado).
- Fase nueva que no estaba en el flujo inicial: **prototipo visual entre design.md y tasks.md**. Fichero
  `specs/web-server/prototype/ui-mock.html`, publicado como artifact privado
  (https://claude.ai/artifact/NQf4HWCt4JZ2ohV8zT9UFk). Incluye las 6 pantallas de §8.1 (listado, informe de uso,
  última respuesta, Bash, ficheros y totales con los 5 gráficos), los estados normal/cargando/vacío/error y los temas
  sistema/claro/oscuro. La navegación es real: fila → informe → pestañas.
- Los datos del mock se calculan con los mismos precios y la misma fórmula que `claude_tokens.py`. Se verificó que
  la suma del coste diario es igual al total ($125.8598), como pide R6.3.

**Preguntas al usuario:**

| # | Pregunta | Recomendación | Respuesta | Estado |
|---|----------|---------------|-----------|--------|
| Q22 | Dos modelos de la misma familia (sonnet-5-5 y sonnet-5-6) tendrían el mismo color con §8.4: ¿regla de tonos por versión? | La versión más nueva lleva el color base; las anteriores, tonos más claros | Adoptar (respondida en P7) | aceptó recomendación |

**Supuestos sin preguntar:**
- La skill de prototipo pide por defecto **3 variantes radicalmente distintas**. El usuario pidió ver "lo que se
  espera que salga", así que se hizo **una sola versión fiel al diseño** de cada pantalla. Si hacen falta
  alternativas, se añaden como variantes.
- Ubicación `specs/web-server/prototype/`, junto al diseño. La skill recomienda guardar el prototipo en una rama
  desechable fuera de main. **Pendiente de decidir** al cerrar la revisión.
- Datos ficticios: projects `/home/dev/...` y conversation ids del README. No hay datos reales del usuario.
- Diferencias entre el mock y el producto real que vienen del entorno del artifact: el CSS de highlight.js va
  inline (el CSP del artifact solo admite scripts del CDN) y no hay SRI. El producto usará las hojas del CDN con SRI
  (§8.5).
- Textos de error, de estados vacíos y de carga redactados por el asistente; no estaban en el diseño.

**Hallazgos del prototipado:**
- **Hueco de diseño (§8.4):** la regla "un color fijo por familia" no distingue dos versiones de la misma familia.
  Solo apareció al pintar datos realistas → Q22.
- **Bug detectado por la comprobación de sintaxis:** el Markdown de ejemplo contenía `</script>` dentro de una
  cadena JS, lo que cierra la etiqueta `<script>` en el HTML y rompe la página. Lección para la implementación: el
  producto real recibe el contenido por `fetch`/JSON y nunca lo incrusta en el HTML; conviene mantenerlo así y
  añadirlo a la checklist.
- Para el informe de uso hubo que decidir qué cifras resumir arriba: coste, tokens, scopes y % servido desde caché.
  El diseño no lo fijaba.

**Retrospectiva:** _pendiente_

---

## P7 — 2026-10-01 — Respuesta a Q22

**Prompt (literal):**

> Para la pregunta Q22 , adopta en 8.4 la decisión de un tono más claro para las anteriores

**Valor generado para SDD:**
- §8.4 de design.md recoge la regla de color por versión dentro de una familia (D-033), con el prototipo como
  referencia.

**Preguntas al usuario:**

| # | Pregunta | Recomendación | Respuesta | Estado |
|---|----------|---------------|-----------|--------|
| — | Revisión visual del resto del prototipo (se pidió responder junto con Q22) | — | No comentada en el prompt | sin respuesta → se preguntó en Q23 |
| Q23 | ¿Prototipo aprobado tal cual como referencia? | Aprobado tal cual | Aprobado tal cual | aceptó recomendación |
| Q24 | ¿El prototipo va a una rama desechable o se queda en `specs/` en main? | A: rama desechable | B: en `specs/` en main | respondida (difiere de la recomendación) |

**Supuestos sin preguntar:**
- Los porcentajes del tinte (38 %, luego 55 %) se toman del prototipo y se copian al diseño sin preguntar.

**Tras Q23/Q24 — borrador de `specs/web-server/tasks.md`** (T0–T18 en 7 fases, checklist manual M1–M13,
trazabilidad R→T, riesgos abiertos y 2 puntos de revisión TV1–TV2).

Decisiones del asistente al planificar (pendientes de la revisión):
- Orden: red de seguridad (fixtures + caracterización) → división en paquete → cambios del núcleo → servidor → UI →
  docs/verificación. Lo marca D-029.
- Los goldens solo pueden cambiar en T6 (`daily`) y T7 (fuentes en bash/files); cualquier otro cambio es una
  regresión.
- Tests en Python 3.9 **y** 3.12 (los dos están instalados). No se preguntó.
- La lección del `</script>` del prototipo pasa a un fixture (respuesta con `<script>`) y a M3.
- La checklist manual sale de §9 del diseño, de lo revisado en el prototipo y de R9.2/R9.3 (D-025).
- TV1 pregunta explícitamente si se autorizan commits por tarea: la regla general es no hacer commit sin que el
  usuario lo pida.

**Retrospectiva:** _pendiente_

---

## P8 — 2026-10-01 — TV1/TV2 y revisión de riesgos abiertos

**Prompt (literal):**

> TV1: Autorizado a realizar commit por tarea
> TV2:  un commit por modulo
>
> Vamos a analizar los riegos aun abiertos para dejar todo cerrado, como procedemos

**Valor generado para SDD:**
- TV1/TV2 aplicados en tasks.md (D-036).
- Método de cierre de riesgos: cada riesgo se verifica, se dan opciones y una recomendación, el usuario decide, y
  el riesgo queda **cerrado / mitigado / aceptado**. Resultado: una sección *Risk register* en tasks.md (K-1…K-7).
  Se usan IDs `K-` para no confundirlos con los requisitos `R`.
- **Riesgos nuevos detectados al revisar** (no estaban en la lista del borrador):
  - K-1, goldens inestables, verificado con hechos: la ayuda de `argparse` dice `optional arguments:` en 3.9 y
    `options:` en 3.12; el JSON incluye rutas temporales; el ancho de la ayuda depende de `COLUMNS`. Sin esto, la
    red de seguridad de T2 habría fallado en una de las dos versiones de Python que exige el propio plan.
  - K-7, el prototipo en main (consecuencia de D-035).
- Cambios en documentos ya aprobados: R2.8 (requirements), §2/§5.2/§5.3/§8.5 (design), ADR 0001 matizado y ADR
  0002 nuevo.

**Preguntas al usuario:**

| # | Pregunta | Recomendación | Respuesta | Estado |
|---|----------|---------------|-----------|--------|
| TV1 | ¿Commits por tarea autorizados? | — | Autorizado | respondida |
| TV2 | ¿T3 en un commit o uno por módulo? | — (dos alternativas) | Uno por módulo | respondida |
| — | K-1, K-4, K-6 y K-7 propuestos sin pregunta ("si no ves nada que objetar") | Mitigar / cerrar / cerrar / aceptar | Sin objeción | respondida implícitamente |
| Q25 | K-2: ¿criterio de cobertura de la caracterización? | A: todas las funciones ejecutadas | B: umbral de líneas | respondida (difiere de la recomendación) |
| Q26 | ¿Qué umbral? | 85 % | 80 % | respondida (difiere de la recomendación) |
| Q27 | K-3: ¿CDN + SRI, librerías en el repo o ambos? | B: en el repo | B | aceptó recomendación |
| Q28 | K-5: ¿avisos de stderr? | A: aceptar | A | aceptó recomendación |

**Supuestos sin preguntar:**
- Para cerrar K-4 se comprobó el código de Chart.js 4.4.1 (`grep` de `createElement("style")` y de
  `setAttribute("style")`: 0 coincidencias). La versión final se fija en T13, así que la comprobación habrá que
  repetirla si cambia → queda cubierta por M13.
- `tools/vendor.py` y el formato de `VERSIONS.txt` los define el asistente.
- K-5 se decidió con una medición real (0 avisos en 725 logs), no con una estimación.
- tasks.md no se ha aprobado de forma explícita: el usuario respondió a TV1/TV2 y pasó a los riesgos.

**Observaciones:**
- Revisar los riesgos destapó un problema que habría roto la primera tarea de código (K-1). Lección para Spec Kit:
  hacer la revisión de riesgos **antes** de aprobar tasks.md, no después.
- R-3 llevó a enmendar un requisito y un ADR ya aprobados. El ADR original no se reescribió; se añadió ADR 0002, así
  que el motivo del cambio queda trazado.

**Retrospectiva:** _pendiente_

---

## P9 — 2026-10-01 — Aprobación de tasks.md e inicio de la implementación

**Prompt (literal):**

> tasks.md aprobado.

**Valor generado para SDD:**
- tasks.md aprobado (D-041). Se cierran todas las fases de especificación y empieza código + tests.

**Preguntas al usuario:**

| # | Pregunta | Recomendación | Respuesta | Estado |
|---|----------|---------------|-----------|--------|
| Q29 | Bug de recuento de herramientas/skills en `--totals`: ¿corregir en esta feature, en otra, o antes de empezar? | A: en esta feature, en T5b, después de la caracterización | A | aceptó recomendación |

**Supuestos sin preguntar:**
- "Aprobado" + TV1 se interpretan como autorización para avanzar tarea a tarea con un commit por tarea, informando
  del progreso, sin pedir aprobación entre tareas.

**Hallazgo durante T1 (antes de escribir código):** para que los fixtures reprodujeran la forma real de los logs se
inspeccionaron los eventos reales (solo claves). Una respuesta de la API se guarda como **un evento por bloque de
contenido, todos con el mismo `message.id`**. `accumulate_file` deduplica por `message.id`, que es correcto para los
tokens, pero de paso descarta los `tool_use` de los eventos siguientes. Datos reales: 24.726 llamadas únicas y
5.252 contadas (21 %); Bash 22.150 → 4.473. Además, 94 bloques aparecen repetidos con el mismo id. **Ninguna fase
de especificación lo detectó**: requirements y design daban por buena la salida de `--totals` como "la verdad" que
la web debía replicar (R5.1). Lección: antes de exigir paridad con un comportamiento existente, validar ese
comportamiento contra datos reales.

**Progreso de la implementación** (incluye el trabajo de P10):

| Tarea | Commit | Resultado | Notas / desviaciones |
|-------|--------|-----------|----------------------|
| T0 | `58a09ed` | Rama `feature/web-server` + specs, glosario, ADRs y log versionados | — |
| T1 | `f5a3e2b` | `tests/fixtures.py`: 5 conversaciones, 2 projects, 2 subagentes, respuestas partidas en varios eventos, bloque repetido, registro sin timestamp, modelo sin precio y modelo con precio estimado, línea mal formada, id ambiguo, conversación sin respuestas | Durante T1 se encontró el bug D-042 (Q29) |
| T2 | `96aceff` | 35 casos de caracterización (`tests/characterization.py`), goldens generados con el script **sin modificar**, en verde en 3.9 y 3.12. Cobertura con `trace`: **91,0 %** de 710 líneas (umbral 80 %) | Ver detalle de cobertura abajo |
| T3 | `a5ea41f`…`bea8a02` (7 commits, uno por módulo) | `claude_tokens.py` es ahora un punto de entrada de 8 líneas; el código vive en `ctokens/{pricing,logs,catalog,reports,content,text,cli}.py`, movido con un script `ast` que copia los cuerpos intactos. Caracterización en verde en 3.9 y 3.12 tras **cada** commit. Selector interactivo y render ANSI comparados con la versión original en una pseudo-TTY (`script`): 5 secuencias de paginación + 4 de selección + Markdown con color, **idénticas** | Desviación de §2: **ciclo de imports** en el mapa del diseño (logs → text → content → logs). Se corrigió: `short` pasa a `logs` y los `show_*` a `cli`; §2 enmendado. La caracterización cazó dos errores del script de división: la llamada `text(data)` sin renombrar y el `--help` con el docstring del módulo `cli` |
| T4–T7 (agente Core) | `c5b0a44`, `3e73196`, `1304f9b`, `5fe08bd`, `e8026e9` (fusionados con fast-forward) | 27 tests en verde en 3.9 y 3.12. Goldens cambiados solo donde se permitía: T5b herramientas 4 → 9 (tokens y coste idénticos); T6 `daily` solo en `totals_json` (suma diaria = total: 0.188846); T7 bash 2 → 4 entradas, files 1 → 2 filas. Cobertura de la caracterización: logs 96,8 %, reports 97,0 %, content 93,7 % | Decisiones del agente: glob `subagents/*.jsonl` en vez de `agent-*.jsonl` (§3.1), para coincidir con el código existente; un día en que todos los modelos van sin precio vale 0.0, no null; las entradas por día no llevan `price_estimated`; `timestamp` en bash es el texto original del log; `touched_files` devuelve siempre las tres cuentas. Incidencia de orquestación: el worktree del agente arrancó en un commit antiguo (`6f1d61e`) y el agente lo detectó y avanzó a `bb42e76` antes de empezar |
| T8–T12 (agente Server) | `c43a1ec`, `c11d5be`, `919fa57`, `7ebbe74`, merge `cd13aec`, `fc47ad2` (fast-forward) | 84 tests en verde en 3.9 y 3.12. Prueba con un servidor real: 200 en la lista y en bash, 409 con el id ambiguo, 404 con `..%2F..%2Fetc%2Fpasswd` y con una ruta desconocida, 403 con `Host: evil.example`, 200 con `Host: localhost:9000` (túnel), 405 con DELETE; `/api/totals` da `tool_calls` 9 y `daily` con el bucket undated al final. Medido por el agente en la carpeta real (528 MB): `/api/totals` tarda 4,0 s en frío y 0,05 s con caché (R9.2 ≤ 5 s y R9.3 < 1 s) | Decisiones del agente: la lista devuelve `{"projects_dir", "conversations": [...]}` en vez de una lista (para el estado vacío de R3.6); hooks `project_of=`/`title_of=` en vez de un único `meta=`; `allow_reuse_port = False` explícito (en 3.12 dos servidores podrían compartir el puerto y se rompería R1.5); la caché copia en profundidad los `parse_log` porque `report()` los muta; `find_conversation` devuelve la ruta tal como sale del glob, para que `source` coincida byte a byte con el CLI. Cambiaron 7 goldens de error además de `help`, porque la línea de uso de argparse incluye ahora `[--serve] [--port PORT]`. Huecos conocidos, sin bloqueo: `project_path_of` no pasa por la caché en `scan_totals`, y un log borrado a mitad de un escaneo da 500 en esa petición. Coordinación: avisé al agente UI del cambio de forma de la lista |
| T13–T16 (agente UI) | `dae61e2`, `b522850`, `fef93de`, `d2b076a`, merge `6274bbc`, `a75bc2d` (fast-forward) | 92 tests en verde en 3.9 y 3.12; `node --check` OK; ninguna URL absoluta en index/app.js/app.css. Librerías incluidas en el repo: Chart.js 4.5.1, marked 18.0.14, DOMPurify 3.4.16 y highlight.js 11.11.2 (temas atom-one light/dark), con sha256 en `VERSIONS.txt`. Chart.js 4.5.1 vuelve a cumplir K-4 (sin `<style>` ni `setAttribute("style")`), y ahora lo comprueba un test permanente | **Pendiente:** los textos de licencia (`vendor/LICENSES/`). El clasificador de permisos le denegó al agente la descarga desde raw.githubusercontent.com y el coordinador **no** la repite para no saltarse esa denegación; R2.8 queda incompleto hasta que el usuario ejecute `python3 tools/vendor.py`. Decisiones del agente: el filtro de la lista se aplica en el cliente; la cabecera del informe pide también `/api/conversations` para mostrar título/project/fecha; el selector de tema del prototipo no se ha llevado al producto; DOMPurify no se pudo ejercitar en node → M3 necesita un navegador. Incidencia de orquestación: el worktree también arrancó en `6f1d61e` (los 3 agentes lo detectaron y corrigieron solos) |
| T17 (coordinador) | `099904a` | README: `--serve` y opciones, túnel SSH, rutas de la API, `daily`, recuento por `tool_use` id, subagentes en `--bash`/`--files`, sección de desarrollo y tests | — |
| T18 (coordinador, parte automatizable) | — | Sobre la carpeta real (387 conversaciones): **M12** `/api/totals` 4,03 s en frío, 0,047 s y 0,049 s con caché ✔; `/api/totals` = `--totals --json` en conversations, subagents, total_tokens, tool_calls y coste ✔; suma diaria = total ✔ (23 días); lista API = selector (387) ✔ (M1, datos); estáticos 200 con su content type y `VERSIONS.txt` 404 ✔; CSP exacta ✔ (M13, cabecera); `tool_calls` reales ahora 25.092 (antes 5.252) | Pendiente para el usuario, con navegador: M1 (ordenación/filtro), M2–M10 visual, M11 (túnel a otro puerto local), M13 (consola sin errores ni violaciones CSP; pestaña Network) |

Cobertura de T2: las 64 líneas sin ejecutar y su motivo.
- Solo con TTY (se comprueban a mano en T3): 431–460, el bucle interactivo de `pick_conversation`; 676–690,
  `render_markdown` con color.
- Ramas defensivas que los fixtures no ejercitan: 48/52 (ventana de contexto sin dato o > 1M), 63 (líneas en
  blanco), 75/77 (contenido de usuario como lista o dict), 89 (sin tarea), 120 (uso todo a cero), 209 (familia sin
  ningún modelo con precio; inalcanzable con la tabla integrada), 359 (log sin `cwd`), 373 (log > 128 KB en
  `session_title`), 375/383 (errores de E/S o de JSON en el título), 395/525 (entrada que no es carpeta en
  projects), 555 (modelo con 0 tokens), 699/702/707 (contenido del asistente como str o no-lista).
- Inalcanzable en la práctica: 832 (una ruta ya resuelta que deja de ser un fichero).
- Hallazgos de T2: `trace --no-report` no guarda los recuentos (se descubrió al montar el script de cobertura);
  el error de precios inválidos del CLI sale en español ("archivo de precios inválido") mientras el resto está en
  inglés. Se fija tal cual y no se cambia en esta feature.

**Retrospectiva:** _pendiente_

---

## P10 — 2026-10-01 — Paralelizar con agentes (mensaje enviado durante T3)

**Prompt (literal):**

> Verifica que parte del trabajo se puede realizar con varios agentes, lanzalos y usa esta sesión como
> coordinadora, mandando mensajes para comprobar el estado y si necesitan datos de otras sesiones, el objetivo es
> terminar las tareas sin preguntas al usuario

**Valor generado para SDD:**
- Análisis de dependencias del plan para decidir qué se puede paralelizar (D-043):
  - **T3 en serie** y hecho por el coordinador: todo lo demás edita los módulos que crea.
  - Después, tres pistas en paralelo, cada una en su worktree:
    - **Core**: T4, T5, T5b, T6, T7.
    - **Server**: T8–T12. T8 se movió aquí porque `find_conversation`/`conversation_rows` las necesita el
      servidor y no tocan ficheros de Core.
    - **UI**: T13–T16.
  - El coordinador: fusiona las ramas, pasa datos entre pistas, mantiene el log y hace T17 (README) y la parte
    automatizable de T18.
- Contratos fijados en los prompts de los agentes para que puedan trabajar sin esperarse:
  - Firmas exactas: `discover(main, parse=parse_log)`, `file_stats` con sus claves y `scan_totals(stats=)`.
  - Formas JSON de `daily`, `bash_commands` y `files`, y el mapa fijo de ficheros estáticos.
  - Propiedad exclusiva de cada fichero. `cli.py` se reparte: los `show_*` son de Core y argparse/`main` de
    Server.
- Dependencia entre pistas que se gestiona con mensajes: T12 (caché) necesita `file_stats`/`discover(parse=)` de
  Core T5. Server hace primero T8–T11 y espera la señal del coordinador.

**Preguntas al usuario:** ninguna (petición explícita: "sin preguntas al usuario").

**Supuestos sin preguntar:**
- Hay comprobaciones de T18 que necesitan un navegador y ojos humanos (M3, M5–M8, M10, M13 visual). Ningún agente
  las puede cerrar; quedarán documentadas como pendientes para el usuario en lugar de darlas por hechas.
- Las desviaciones que encuentren los agentes no se preguntan: se deciden según la intención de la spec y se
  anotan aquí al fusionar.
- Los agentes no modifican specs, docs ni el log; las enmiendas las aplica el coordinador.

**Retrospectiva:** _pendiente_

---

## Retrospectiva final

_Borrador preparado por el coordinador con los hechos del log. Las conclusiones las decide el usuario._

**1. Respuestas o silencios que llevaron a un sitio equivocado o a retrabajo**

| Origen | Qué pasó | Coste | Detectado en |
|--------|----------|-------|--------------|
| Q10 (recomendación del asistente) | La opción C ofrecía "coste por día" como si existiera; no existía | Requisito nuevo R6 y cálculo nuevo | Antes de Q11, revisando el código |
| RV4 (respuesta del usuario) | "--serve no admite otros parámetros que no sea port" contradecía R1.4, ya aprobado | 1 pregunta (Q19) | Al cruzar la respuesta con lo aprobado |
| P4 "revisado y acorde" | Aprobación en bloque; el idioma inglés de las specs nunca se confirmó | Nulo hasta ahora | — |
| Q18 (confirmación en bloque) | Seguridad, supuestos y alcance confirmados con un solo "sí" | Nulo hasta ahora; riesgo de que algo no se leyera | — |
| Q5/Q11 (selección múltiple) | El usuario marcó todo: vistas de contenido y 5 gráficos | La UI es la pista más cara ($3.97, 13,7 M tokens) | Patrón anotado en P3 |
| Q24 (difiere de la recomendación) | El prototipo se queda en main | Riesgo K-7 aceptado | P8 |

**2. Detalles que no cubrieron requirements/design/tasks**

| Hueco | Dónde salió | Cómo se resolvió |
|-------|-------------|------------------|
| Bug previo: `--totals` contaba el 21 % de las llamadas a herramientas | T1, al imitar la forma real de los logs | D-042, R5.5/R7.7, T5b |
| Orden de `--bash` entre fuentes | Diseño (RV2) | Cronológico |
| Color de dos versiones de una misma familia | Prototipo (Q22) | Tinte por versión, D-033 |
| `http.server` responde 501 y no 405 | Diseño, al leer la stdlib | `__getattr__` |
| Túnel a otro puerto local rechazado por R2.2 | Autorrevisión del borrador de requisitos | Validar solo el nombre del host |
| Goldens inestables entre 3.9 y 3.12 (`argparse`, rutas temporales, `COLUMNS`) | Revisión de riesgos (K-1) | Entorno fijado y normalización |
| Ciclo de imports en el mapa de módulos | T3 | §2 enmendado |
| `</script>` dentro de JS rompe el HTML | Prototipo, comprobación de sintaxis | Fixture + M3 |
| Forma JSON de la lista (`projects_dir`) | Implementación (Server) | Mensaje del coordinador a UI |
| Descarga de licencias denegada por permisos | Implementación (UI) | Pendiente del usuario |

**3. Candidatos para adaptar el flujo a Spec Kit**

- Validar contra datos reales cualquier comportamiento existente que la spec tome como "verdad" (paridad R5.1), antes
  de aprobar los requisitos. Es lo que habría encontrado el bug de D-042 en la fase 1 y no en T1.
- Revisar los riesgos **antes** de aprobar tasks.md (K-1 habría roto T2).
- Evitar las confirmaciones en bloque (Q18, "revisado y acorde"): pedir confirmación por puntos o por sección.
- Usar preguntas de opción única para las decisiones de alcance.
- Añadir una fase de prototipo visual entre plan y tasks: en este flujo salió a petición del usuario y encontró un
  hueco de diseño.
- Contrastar siempre las respuestas de revisión con lo ya aprobado (RV4).
- En la orquestación con agentes: fijar contratos de interfaz en los prompts y asignar ficheros en exclusiva
  funcionó (0 conflictos en 3 fusiones). Pero los worktrees arrancaron en un commit antiguo; verificar la base de
  cada agente antes de que empiece.
- Coste: especificar (P1–P9) costó $11.03 y especificar + prototipo un 43 % del total; implementar con 3 agentes en
  paralelo, $14.43.
