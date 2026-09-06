# mineduc-curriculum-db

Scraper and dataset builder that turns the Chilean national curriculum published on
[curriculumnacional.cl](https://www.curriculumnacional.cl) into a structured, searchable
JSON database — instead of a pile of PDFs.

It collects **Objetivos de Aprendizaje (OA)**, **Objetivos de Aprendizaje de Habilidad (OAH)**,
**Objetivos de Aprendizaje de Actitud (OAA)** and **Objetivos de Aprendizaje Transversales (OAT)**
from Sala Cuna through 4° Medio, including the Técnico-Profesional specialities, EPJA and
Lengua y Cultura de los Pueblos Originarios — plus everything the **Programas de Estudio**
add on top: the **Indicadores de Evaluación** for each objective, and for the Técnico-Profesional
specialities the **módulos** with their **Aprendizajes Esperados** and **Criterios de Evaluación**.
Those live only inside PDFs on the site, so the pipeline reads them out of the PDFs.

- **Code**: MIT (`LICENSE`)
- **Dataset**: official MINEDUC legal text, re-published with attribution; project-added
  structure dedicated to the public domain (`LICENSE-DATA`)

---

## Quick start

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
```

```bash
mineduc-scraper scrape     -o data/mineduc_curriculum_full.json
mineduc-scraper indicators -f data/mineduc_curriculum_full.json --pdf-cache .cache/pdfs
mineduc-scraper tp-modules -f data/mineduc_curriculum_full.json --pdf-cache .cache/pdfs
mineduc-scraper augment    -f data/mineduc_curriculum_full.json --pdf-cache .cache/pdfs
mineduc-scraper coverage   -f data/mineduc_curriculum_full.json --embed
mineduc-scraper export-manifest -f data/mineduc_curriculum_full.json -o data/manifest.json
```

To browse what you just built, serve the repository and open it —
see [Browser navigator](#browser-navigator):

```bash
python3 -m http.server 8765
```

The first command crawls every level (~364 pages, ~10 minutes at the default 1.5 s delay).
The second and third read the Programa de Estudio PDFs — about 220 files and ~800 MB the first
time, so give them an hour. Each command prints a coverage report.

> **Where the PDFs go.** `--pdf-cache .cache/pdfs` is a **hidden directory** (the leading dot),
> so Finder and a plain `ls` will not show it — use `ls -a`, or `open .cache/pdfs`, or press
> **Cmd + Shift + .** in Finder. It is also in `.gitignore`, so it will not appear in
> `git status` either: 824 MB of ministry PDFs are a rebuild cache, not part of the dataset.
> Keep it and every later run needs zero network; delete it and the next run re-downloads
> everything. Any path works if the leading dot is a nuisance — `--pdf-cache pdf-cache`. To scrape only secondary school, matching the example in `SPEC.md`:

```bash
mineduc-scraper scrape --levels 7B,8B,1M,2M,3M,4M -o ./data/curriculum.json
```

Re-runs are cheap if you keep a cache — the second run does no network I/O at all:

```bash
mineduc-scraper scrape --cache .cache -o data/mineduc_curriculum_full.json
```

## CLI

| Command | What it does |
| --- | --- |
| `scrape` | Crawl the site and write the full JSON dataset (plus optional slim / SQLite / per-level outputs) |
| `indicators --file F` | Download the Programa de Estudio PDFs and attach each objective's *Indicadores de Evaluación* |
| `tp-modules --file F` | Attach the Técnico-Profesional *módulos*, *Aprendizajes Esperados* and *Criterios de Evaluación* |
| `augment --file F` | Complete the dataset: EPJA objectives from the *Bases Curriculares* PDF, the Religión finding, reviewed corrections, provenance and curriculum status |
| `coverage --file F` | Build the coverage report from the official source inventory |
| `validate --file F` | Re-run JSON Schema validation and the integrity audit on an existing file |
| `export-slim --file F -o G` | OAs only, single-line statements — for browser bundles and LLM context (`--with-indicators` to keep them) |
| `export-manifest --file F -o G` | Small manifest identifying a build, for the browser navigator's version check |
| `export-sqlite --file F -o G` | SQLite build with an FTS5 full-text index |
| `export-markdown --file F -o DIR` | The curriculum as Markdown documents, grouped to fit a 50-source notebook (NotebookLM and similar) |
| `split --file F -o DIR` | One JSON file per level plus an `index.json` manifest, for lazy client-side loading |
| `levels` | List the tokens accepted by `--levels` |
| `query TEXT --file F` | Grep the dataset from the shell — handy for spot-checking a scrape |

Useful `scrape` flags:

```
--levels 7B,8B,1M,2M,3M,4M   # tokens 1B..8B, 1M..4M, SC/NM/NT, E1B..E2M
--levels SECUNDARIA          # group aliases: ALL, PARV, BASICA, MEDIA, EPJA, SECUNDARIA
--delay 1.5                  # seconds between requests (politeness budget)
--cache .cache               # cache HTML on disk; re-runs skip the network
--slim / --sqlite / --split  # write extra output formats in the same pass
--limit 5                    # stop after N pages (smoke test)
--compact                    # minified JSON
```

Everything writes a coverage report and exits non-zero if any integrity check fails, so it
drops straight into CI.

## Output shape

```jsonc
{
  "metadata": {
    "scraped_at": "2026-09-04T12:00:00+00:00",
    "source_url": "https://www.curriculumnacional.cl",
    "built_at": "2026-09-05T16:16:15+00:00",
    "schema_version": "2.0.0",
    "total_oas": 4261,
    "total_by_category": { "actitud": 643, "conocimiento": 3267, "habilidad": 351 },
    "coverage_notes": ["..."],
    "failed_pages": []
  },
  "levels": {
    "1_medio": {
      "level_id": "1_medio",
      "level_name": "1° Medio",
      "subjects": {
        "matematica": {
          "subject_id": "matematica",
          "subject_name": "Matemática",
          "track": "plan_comun",
          "curriculum_base": "7o-basico-2o-medio",
          "source_url": "https://www.curriculumnacional.cl/curriculum/7o-basico-2o-medio/matematica/1-medio",
          "documents": [
            { "doc_type": "Programa de estudio", "title": "Programa de Estudio Matemática 1° medio", "url": "..." }
          ],
          "learning_objectives": [
            {
              "oa_id": "CL_MAT_1M_NMRS_OA01",
              "oa_number": 1,
              "category": "conocimiento",
              "code": "MA1M OA 01",
              "code_slug": "ma1m-oa-01",
              "strand_eje": "Números",
              "strand_kind": "Eje",
              "statement": "Calcular operaciones con números racionales en forma simbólica.",
              "keywords": ["calcular", "operaciones", "números", "racionales", "simbólica"],
              "prioritized": true,
              "prioritization": {
                "programme": "Priorización Curricular", "period": "2023-2025",
                "status": "historico", "source_url": "..."
              },
              "curriculum_status": "vigente",
              "status_source": { "url": "...", "note": "...", "verified_on": "2026-09-05" },
              "provenance": {
                "source_url": "https://www.curriculumnacional.cl/.../ma1m-oa-01",
                "source_type": "html_curriculum_page",
                "curriculum_base": "7o-basico-2o-medio",
                "retrieved_at": "2026-09-04T14:12:49+00:00",
                "extraction_method": "selectolax: div.items-wrapper > ..."
              },
              "source_url": "https://www.curriculumnacional.cl/.../ma1m-oa-01",
              "indicators": [
                "Identifican el tipo de número, racional, entero y natural, y las operaciones involucradas.",
                "Realizan operaciones mixtas con números racionales, respetando la jerarquía de las operaciones."
              ],
              "indicators_scope": "objective",
              "indicators_source": ["https://www.curriculumnacional.cl/sites/.../articles-34359_programa.pdf"]
            }
          ]
        }
      }
    }
  },
  "transversal_objectives": {
    "7o-basico-2o-medio": [
      {
        "oat_id": "CL_OAT_7BA2M_FISICA_01",
        "oat_number": 1,
        "code": "OAT 1",
        "dimension": "Dimensión física",
        "statement": "Favorecer el desarrollo físico personal y el autocuidado, ...",
        "curriculum_base": "7o-basico-2o-medio"
      }
    ]
  }
}
```

The canonical schema lives at [`src/mineduc_scraper/schema/mineduc_curriculum.schema.json`](src/mineduc_scraper/schema/mineduc_curriculum.schema.json)
(JSON Schema 2020-12) and is enforced on every run.

### Identifiers

Two ids per objective, because both are load-bearing:

- **`code`** — the official MINEDUC code exactly as printed in the *Bases Curriculares*
  (`MA1M OA 01`, `AR-AVAM-3y4-OAC-01`, `OA 01 LV NM`). This is what teachers, textbooks and
  ministry documents actually cite. `code_slug` is its URL form, matching the site's own paths.
- **`oa_id`** — a deterministic global id in the shape `CL_<SUBJECT>_<LEVEL>_<STRAND>_<OA><NN>`,
  e.g. `CL_MAT_1M_NMRS_OA01`. Stable across runs, unique across the whole dataset, and safe as a
  primary key.

  The subject token comes from a frozen map (`taxonomy.SUBJECT_ABBREV`) covering all 122 subject
  slugs the site publishes, verified injective by the test suite. Freezing it matters: derived
  initials collide (*Electricidad* / *Electrónica*, and the three *Mecánica Industrial* menciones),
  and anything computed from "the subjects in this run" would change when you scrape a different
  `--levels` subset. A subject added to the site after the freeze falls through to a derived token
  plus a stable slug fingerprint, so it cannot collide either. Build-time uniqueness is still
  asserted; a residual collision would be disambiguated with a `__2` suffix and reported in
  `metadata.id_collisions` (currently empty).

`prioritized` marks objectives flagged as part of the *Priorización Curricular* on the site. It
is **not** a present-tense property: it records membership of the priorización published for
**2023–2025**, so every flagged objective also carries a `prioritization` object naming that
programme, its period and its historical status. The boolean is kept for backward compatibility;
read `prioritization` instead, and never render it as a bare "Priorizado".

`provenance` identifies the exact source each record was extracted from — URL, source type,
document and page for a PDF, retrieval date, curriculum base and extraction method — so any
record can be re-fetched and re-verified. `curriculum_status` is one of `vigente`, `propuesta`,
`en_implementacion`, `historico` or `desconocido`, and is **never** inferred from a page being
reachable: anything other than `desconocido` carries a `status_source` naming the official
document that says so. That is why the site's own "Inglés (Propuesta)" subject is `propuesta`
rather than inheriting its base's `vigente`.

## Using the dataset

```javascript
import curriculumDB from './mineduc_curriculum_slim.json';

export function getSubjectOAs(levelId, subjectId) {
  return curriculumDB.levels[levelId]?.subjects[subjectId]?.learning_objectives || [];
}

// Context block for an LLM prompt
export function buildLLMContext(levelId, subjectId) {
  return getSubjectOAs(levelId, subjectId)
    .map((oa) => `[${oa.code}] ${oa.statement}`)
    .join('\n');
}
```

`examples/curriculum.js` has ready-made helpers (indexing by id and official code, accent-
insensitive search, LLM context blocks); `examples/queries.sql` is a cookbook for the SQLite build.

For larger apps, `split` gives you one file per level so the browser only downloads the grade in
use — `index.json` lists each level's `file`, subjects and objective count, so you can render the
pickers before fetching anything. `export-sqlite` gives you an FTS5 index that works under
SQLite-WASM:

```sql
SELECT o.code, o.subject_id, o.statement
FROM objectives_fts f
JOIN objectives o USING (oa_id)
WHERE objectives_fts MATCH 'fotosintesis'
  AND o.level_id = '1_medio';
```

The FTS index is built with `unicode61 remove_diacritics 2`, so `celula` matches `célula`.

## How it works

```
/curriculum/ambitos-y-asignaturas          (the site's own master index)
        │
        ▼  PoliteClient: 1.5 s between requests, retry w/ backoff, optional disk cache
   364 × /curriculum/<base>/<subject>/<grade>
        │
        ▼  selectolax: div.items-wrapper > div.item-wrapper > span.oa-title / .number-title
   RawObjective records  ──┐
                           ├─►  Normalizer: canonical ids, oa_number, keyword tags
   JSON:API paragraph/oat ─┘
        │
        ▼  jsonschema + integrity audit (empty text, duplicate ids, per-base OAT counts)
   data/mineduc_curriculum_full.json
   data/mineduc_curriculum_slim.json
   data/mineduc_curriculum.db
   data/by_level/<level_id>.json
```

Two details worth knowing:

**Discovery is not hardcoded.** The crawl frontier comes from the site's own
`/curriculum/ambitos-y-asignaturas` index, so a new subject or speciality is picked up without
a code change. Unknown grade slugs are reported rather than silently dropped.

**OATs come from the JSON:API, OAs do not.** The site runs Drupal 10 with JSON:API enabled at
`/jsonapi`. Transversal objectives are readable there as a clean
`curriculum_base → paragraph/dimension → paragraph/oat` tree, so that is where they are read
from. Learning objectives, however, are *not* usable over the API: anonymous access to
`cn_learning_objective` exposes only the `code` field and hides the statement, so the OAs are
parsed from HTML. The API's entity counts are still kept in the validator as an independent
coverage cross-check.

## What's in the dataset

A full run on 2026-09-04 produced:

| | |
| --- | --- |
| Levels | 21 (Sala Cuna → 4° Medio, plus EPJA) |
| Curriculum offerings (level × subject) | 372, across **129 distinct subjects** |
| Objectives | **4261** — 3267 conocimiento, 351 habilidad, 643 actitud |
| of which EPJA | 156 (5 from HTML, 151 from the *Bases Curriculares EPJA 2024*) |
| Distinct official codes | 3151 (a 3°/4° Medio OA is published under both grades) |
| Transversal objectives (OAT) | 74 across 3 curriculum bases |
| Flagged for *Priorización Curricular* | 942 |
| **Indicadores de Evaluación** | **13 705**, on 1586 objectives, from 217 Programa PDFs |
| **TP módulos** | **379**, with 1244 Aprendizajes Esperados and **5024 Criterios de Evaluación** |
| Full JSON / slim JSON / SQLite | 9.0 MB / 2.0 MB / 13.3 MB |

Only the two JSON files are committed; the SQLite build and the per-level split are derived and
regenerated with one command each (see `.gitignore`). The slim variant leaves indicators out by
default (`--with-indicators` includes them, at 3.5 MB).

Objectives per level, and the count MINEDUC's own JSON:API reports for its curriculum
entities, are printed by `validate` on every run.

Objectives are kept in the order the source page publishes them, grouped by strand. The site
is almost always in curriculum order, but not universally (one EPJA page lists OA05 before
OA04), so sort by `oa_number` if you need a guaranteed order.

## Coverage and known gaps

Run `mineduc-scraper validate --file <dataset>` at any time for the current picture.

**27 curriculum offerings carry no objectives, and every one of them says why.**
`coverage` classifies all 372 expected offerings against the ministry's own inventory:

| | |
| --- | --- |
| 345 | objectives ingested |
| 14 | objectives defined for a combined EPJA level, and published there |
| 13 | the ministry publishes no objectives for them, with a verified reason |
| **0** | **no objectives and no verified reason** — i.e. no unresolved parser gap |

The last row is the only one that would be a defect here, and it is empty. The 13 are the twelve
*Religión* offerings and EPJA *Ciencias Naturales* Nivel 1 Básica; see below.

### EPJA

The EPJA objectives come from the **Bases Curriculares EPJA 2024**, which the ministry publishes
only as a PDF. `bases_pdf.py` is a third ingestion engine for exactly that: a *Base Curricular*
defines objectives in running prose, one section per (asignatura, ciclo, nivel), and pushing it
through the *Programa de Estudio* indicator parser — a different document type, read
geometrically for indicator columns — would have found nothing and reported a source gap that is
not there.

The site publishes one EPJA page with objectives in HTML (Lenguaje y Comunicación, Nivel 1 de
Educación Básica). Those five records are **kept as the HTML engine produced them**; the PDF is
used to verify them and then stands aside, because structured HTML beats a PDF whenever both
exist. All five agree with the Bases character for character, which is the strongest check
available on the PDF reader and is asserted in the test suite.

**The Bases' level model is preserved.** Formación General asignaturas are defined per
(ciclo, nivel). Formación Instrumental and Formación Diferenciada Humanístico-Científica
asignaturas are defined once for *"Educación Media, Nivel 1 y 2"* — one block — while the site
navigates them under a Nivel 1 page and a Nivel 2 page. Those go into a combined `epja_media`
level whose objectives carry `level_scope: ["epja_n1_media", "epja_n2_media"]`, rather than being
duplicated into both site levels or forced into one of them. The site pages they came from record
`objectives_in_level`, so an empty page does not read as a coverage hole.

### Religión

Religión carries **no objectives, and that is a property of the source rather than a parsing gap.**
It is not part of the national *Bases Curriculares*: it is governed by **Decreto N° 924 (1983)**,
which permits the teaching of any credo (art. 4) and establishes that Religión is taught according
to programmes *"aprobados por el Ministerio de Educación Pública, a propuesta de la autoridad
religiosa correspondiente"* (art. 6). So there is no single national Religión curriculum — there is
one approved programme per confession — and those programmes are not published on
curriculumnacional.cl. A JSON:API query across the site's whole resource collection for titles
containing "Religi" returns teaching materials, historical readings and the decreto itself, and no
programme or base for the subject.

Each Religión subject therefore records a `programme_model` (`por_credo`, approved per confession,
not published here) and a `no_objectives_reason` citing the decreto. Different confessions'
programmes are **not** merged into one artificial subject, and no objectives are invented.

**Six subjects are reachable by two routes.** Lengua y Cultura de los Pueblos Originarios is
published both under 1° a 6° Básico and under its own curriculum base, where the page renders no
objectives. The populated route wins; the other is recorded in the subject's `alias_urls` and in
`metadata.duplicate_routes`.

**`transversal_objectives` sits at the top level, not on each subject.** `SPEC.md` puts
`transversal_objectives?` inside `SubjectData`. OATs are defined once per *curriculum base*, not
per subject, so nesting them there would duplicate the same 74 statements across ~360 subjects.
They are keyed by curriculum base instead; resolve them via `SubjectData.curriculum_base`.

**3° and 4° Medio are separate levels, with the plan in `track`.** `SPEC.md` shows a merged
`3_4_medio` level. The site publishes 3° and 4° Medio as distinct pages with distinct subject
offerings, so they are kept as `3_medio` and `4_medio`, and Formación General vs. Humanista-
Científico vs. Técnico-Profesional is carried by `track`
(`plan_comun` / `plan_diferenciado_hc` / `plan_diferenciado_tp`), which is what that field is for.

**`skills_oah` is not populated.** The mapping from a content OA to the specific OAH codes it
develops is not published in machine-readable form; the site lists both sets per subject without
linking them. Skills are captured as first-class objectives with `category: "habilidad"`.

**1586 of 4261 objectives carry indicators.** Where the other 2524 stand, exactly:

| | |
| --- | --- |
| 952 | The Programa covers the subject but does not tabulate *this* objective — overwhelmingly attitudes (467) and skills (263). Matemática 1° medio, for instance, publishes indicators for its 15 OAs and 6 OAAs and none for its 15 OAHs. |
| 746 | Técnico-Profesional. Those Programas publish no per-objective indicators at all; the equivalent material is in `modules` instead. |
| 615 | The subject has a Programa, but no indicator table could be read from it. **Part of this is still a parser gap, not a source gap** — see below. |
| 211 | The subject has no Programa de Estudio on the site at all. |

By category: 1411/3116 conocimiento, 111/643 actitud, 64/351 habilidad. `validate` prints the
totals every run so the gap stays visible rather than implied.

The 615 bucket is the honest soft spot. Each new Programa layout found so far has been a distinct
bullet glyph or marker form, and each fix moved a large block of objectives at once — recognising
`OA 1 Comprensión auditiva` as a marker turned Inglés 5° and 6° básico from 0 to 447 and 455
indicators; a lone `>` bullet turned Educación Tecnológica 1° medio from 0 to 81. Some of the
remaining 615 are genuinely indicator-free Programas, and some are layouts nobody has looked at
yet. To triage the rest, compare `metadata.indicators.pdfs_read` against the subjects with a
Programa and no coverage.

**221 table rows were read but not attached, and all 221 are kept.** Their objective statement did
not match any published statement closely enough to trust — mostly activity pages whose numbered
steps parse like objective codes, and skill-level rows in subjects that publish no skills.
`metadata.indicators.rejected_rows` holds each one in full: the source PDF and page, the printed
code, the statement, the similarity score, the closest objective, and **the indicator text
itself** (938 indicators in total, 265 KB). Nothing read out of a PDF is discarded without a
record. Lowering the threshold to absorb them would attach a *habilidad*'s indicators to a
*conocimiento* objective, so the threshold stays where it is and the rows stay visible instead.

**30 TP subjects have no módulos.** The mención pages for Agropecuaria, Construcción,
Gastronomía, Mecánica Industrial and Atención de Enfermería cite no Programa de Estudio at all on
the site, so there is nothing to read. Where a Programa *is* shared between a speciality and its
menciones, it labels each módulo's year but not its mención; those subjects are flagged with
`modules_shared_programme` rather than having the split guessed for them.

## What the Programas de Estudio add

`scrape` reads the *Bases Curriculares* — the objectives themselves — from HTML. The
*Programas de Estudio* are the ministry's companion documents, published only as PDFs, and they
carry two things the Bases do not.

### Indicadores de Evaluación (`indicators`)

Observable, evaluable descriptions of what achieving an objective looks like. `indicators` runs
the PDF pass and attaches them, with `indicators_source` recording the PDF each one came from.

**The join is verified by statement, not by code.** This matters more than it sounds: the
1° a 6° Básico Programas were published under an earlier decree and number their objectives
differently from the Bases the site publishes today. "OA 12" in the Matemática 1° básico Programa
is `MA01 OA 14` on the site. Joining on the printed code would have mis-assigned a large share of
the Básico indicators, silently. So each table row is matched to the objective whose *published
statement* it reproduces (character 5-grams over NFKD-folded text, which survives the ligatures
and line-wrap hyphens PDF extraction leaves behind), and the printed code is used only to break
ties. Rows that match nothing are dropped and counted in
`metadata.indicators.rows_rejected_low_similarity`; renumbered rows are counted in
`rows_renumbered`.

`indicators_scope` says how precisely an indicator is attributed:

- `objective` — the Programa pairs this objective with its own indicator set.
- `unit` — it comes from a 2021 3° y 4° Medio *Actividad de Evaluación*, where one indicator set
  evaluates a group of objectives together. Splitting those by position would invent precision
  the source does not have, so the whole set is attributed to every objective it names.
- `mixed` — both.

Four Programa layouts are handled, because MINEDUC has published four. They are told apart by
their column captions and read geometrically — reading order alone cannot separate the columns,
since an objective's own sub-bullets use the same bullet glyph as the indicators. Two traps are
worth knowing about: both Básico layouts illustrate the table format with a **shrunken facsimile
of another grade's Programa**, which parses perfectly and would contribute the wrong grade's
indicators (it is excluded by font size), and activity pages number their steps `4.`, `2.` —
indistinguishable from an inline objective code except that activity pages carry no column
caption.

### Técnico-Profesional módulos (`modules`)

The TP Programas publish **no per-objective indicators at all**. They organise each speciality
into *módulos*, and each módulo declares the speciality objectives it addresses, a set of
**Aprendizajes Esperados**, and for each of those the **Criterios de Evaluación** plus the
*Objetivos de Aprendizaje Genéricos* (OAG) it develops. Criterios play the role indicators play
elsewhere, but they hang off an Aprendizaje Esperado rather than off an objective — so
`tp-modules` stores them as their own structure on the subject instead of flattening them into
`indicators`, where they would be mislabelled:

```jsonc
"modules": [
  {
    "module_number": 1,
    "module_name": "INSTALACIÓN DE MOTORES ELÉCTRICOS Y EQUIPOS DE CALEFACCIÓN",
    "hours": 152,
    "grade": "Tercero medio",
    "objective_codes": ["OA 4"],
    "objective_ids": ["CL_ELC_3M_OA04"],
    "expected_learnings": [
      {
        "number": 1,
        "statement": "Instala motores eléctricos en baja tensión, de acuerdo a los requerimientos...",
        "criteria": ["1.1 Analiza manuales y diagramas técnicos para establecer procedimientos..."],
        "generic_objectives": ["B", "I", "K"]
      }
    ]
  }
]
```

The three columns are told apart by their numbering rather than by geometry — the column
positions shift from page to page, but `1.` is always an Aprendizaje Esperado and `1.1` always
one of its Criterios. `objective_ids` is resolved by statement, for the same reason the
indicator join is.

## What ships in the repo

The built dataset is committed, in every format, so a consumer can fetch one file instead of
installing Python and re-scraping:

| File | Size | For |
| --- | --- | --- |
| `data/mineduc_curriculum_full.json` | 9.0 MB | everything: objectives, indicators, TP módulos, OATs, provenance |
| `data/mineduc_curriculum_slim.json` | 2.0 MB | objectives only, single-line statements — browser bundles, LLM context |
| `data/mineduc_curriculum.db` | 13.3 MB | SQLite with FTS5 over statements *and* indicators — see [examples/queries.sql](examples/queries.sql) |
| `data/by_level/*.json` | 9.0 MB | one file per level plus `index.json`, for loading a single grade |
| `data/markdown/*.md` | 5.2 MB | 43 subject documents plus an index, for tools that take Markdown rather than JSON |
| `data/manifest.json` | <1 KB | build identity (`scraped_at` and totals) for version checks |

They are all derived from the full JSON and can be rebuilt from it without touching the network:

```bash
mineduc-scraper export-sqlite   -f data/mineduc_curriculum_full.json -o data/mineduc_curriculum.db
mineduc-scraper export-slim     -f data/mineduc_curriculum_full.json -o data/mineduc_curriculum_slim.json
mineduc-scraper split           -f data/mineduc_curriculum_full.json -o data/by_level
mineduc-scraper export-markdown -f data/mineduc_curriculum_full.json -o data/markdown
mineduc-scraper export-manifest -f data/mineduc_curriculum_full.json -o data/manifest.json
```

Two consequences worth knowing. These are binary or wholesale-rewritten files, so each rebuild
adds its full size to git history rather than a diff — roughly 22 MB per regeneration. And the
SQLite build must be regenerated whenever the JSON changes, or the two disagree silently; the
`export-*` commands above are the whole recipe.

### What is *not* committed

The **Programa de Estudio PDFs** (~820 MB, 217 files) are source material, not output. They live
in `.cache/pdfs`, which is gitignored, and `--pdf-cache` rebuilds them from
curriculumnacional.cl. They do not belong in git: they are 24× the size of everything else in
the repo combined, and a GitHub Pages site may be no larger than 1 GB — publishing from the
repository root would have spent 76% of that budget on source PDFs. If you want them archived
for reproducibility, a GitHub Release asset (2 GB per file, and it does not affect clone size)
or Git LFS is the right home, not the git object store.

## Markdown build (for NotebookLM and similar)

`data/markdown/` holds the same curriculum as **43 Markdown documents plus an index**. It exists
because the tools people want to ask questions of this data with — NotebookLM in particular — do
not accept JSON, and cap a notebook at **50 sources**. A single 14 MB JSON file fails both tests.

The binding constraint is the file *count*, not the size: the whole curriculum is about 536 000
words and one source holds roughly 500 000, so documents can be generous as long as there are few
enough. The grouping lands at 43, leaving 7 sources spare:

| | |
| --- | --- |
| 23 | **Plan Común y Formación General** — one file per subject, spanning every level it is taught in. Grade-suffixed names (`Matemática 3º Medio`) fold onto the subject, which is a mechanical read of the published name. |
| 15 | **Técnico-Profesional** — one file per *sector económico*. Those 15 sectors are MINEDUC's own grouping, read from the site's master index and stored on each subject as `tp_sector`, not invented by the exporter. |
| 3 | **Educación Parvularia**, **EPJA**, and the **Formación Diferenciada HC** electives — one file each. |
| 1 | `00_indice.md`, a table of every document with its counts. |

Each objective is written with its official code, eje, complete statement (**including the
subordinate list**, where it has one), evaluation indicators, curriculum status, the Priorización
2023–2025 marker where it applies, any correction that was applied, and **the exact source it was
extracted from** — so an answer traced back through a notebook lands on a real page or PDF page.
Técnico-Profesional documents carry the módulos with their Aprendizajes Esperados and all 5 024
Criterios de Evaluación. A subject with no objectives explains *why* rather than rendering empty,
so Religión reads as the documented property of the source that it is.

```bash
mineduc-scraper export-markdown -f data/mineduc_curriculum_full.json -o data/markdown
```

The command reports whether the result fits the 50-source budget, so a future curriculum expansion
that pushes it over is visible rather than discovered when an upload is refused.

## Browser navigator

`index.html` at the repository root is a self-contained navigator over the dataset — no build
step, no framework, no dependencies. It is meant to be served from GitHub Pages straight out of
the repo, reading `data/` from the same origin.

### Run it locally

```bash
python3 -m http.server 8765
```

Then open <http://localhost:8765/>.

> It has to be **served over HTTP**. Opening `index.html` by double-clicking will not work:
> Chrome blocks `fetch()` on `file://`, so the page cannot read a sibling `.json`. The app says
> so explicitly rather than failing silently. While developing, note that `python3 -m
> http.server` sends no cache headers, so a hard reload (**Cmd/Ctrl + Shift + R**) may be needed
> after editing `assets/`.

### Publish it on GitHub Pages

Settings → Pages → *Deploy from a branch*, branch `main`, folder `/ (root)`. Nothing else to
configure: `.nojekyll` is committed so Pages serves the files as they are, and every path in the
app is relative, so it works from a project subpath like `https://<user>.github.io/<repo>/`.

These files must stay committed for the app to work — they are what it fetches:

| | |
| --- | --- |
| `data/mineduc_curriculum_full.json` | the dataset, 9.0 MB, which Pages gzips to ~1.3 MB |
| `data/manifest.json` | 698 bytes, the version probe (see below) |

`data/by_level/` and `data/*.db` are gitignored and are *not* used by the app — regenerate them
locally with `split` and `export-sqlite` when you want them.

### How data loading works

The dataset is fetched once and then kept in **IndexedDB**, so a repeat visit costs nothing and
the app keeps working offline. IndexedDB is not there for capacity — 9 MB is nothing against a
desktop quota — it is there to avoid re-downloading and to survive going offline.

The freshness check is what `data/manifest.json` is for: a few hundred bytes carrying the build's
`scraped_at`, so the app can answer "is my copy current?" without downloading 1.3 MB to find
out. Cached copy matches the manifest → load from IndexedDB. Differs → download and re-store.
Manifest unreachable and a cached copy exists → serve it and say so. Storage blocked (private
mode, cleared site data) → fall back to a plain fetch every time, no error.

Regenerate the manifest whenever you rebuild the dataset:

```bash
mineduc-scraper export-manifest -f data/mineduc_curriculum_full.json -o data/manifest.json \
  --slim data/mineduc_curriculum_slim.json
```

### What it does

- **Search** across all 4261 statements *and* all 13 705 indicators, accent-insensitively —
  `celula` finds *célula*, `fotosintesis` finds *fotosíntesis*. A plain inverted index with
  prefix expansion, built in about a fifth of a second; an official code (`MA1M OA 01`) ranks
  above a statement match, which ranks above an indicator-only match.
- **Filters** on level, subject, eje/núcleo, objective type, plan, priorización curricular, and
  "has indicators". Subject and eje lists rebuild from what the other filters leave reachable, so
  you cannot land on an empty combination. Levels with no HTML objectives are shown but disabled,
  with the reason on hover, rather than quietly missing.
- **Every view is a link.** Filters, query and selection live in the URL hash. A bare fragment is
  a deep link by official code — `#ma1m-oa-01` — which lands on the objective *in context*.
- **Indicators inline**, labelled with their scope: whether the Programa publishes them for that
  objective or for a group of objectives jointly. That distinction is in the data and matters for
  how much weight to put on them.
- **Técnico-Profesional drill-down**: módulo → aprendizaje esperado → criterios de evaluación,
  with the módulos addressing the current objective opened by default.
- **Progression**: the same objective in the other grade, and the same eje and number at other
  levels — the "how does this strand develop" question the PDFs make nearly impossible.
- **Selection basket** with export to Markdown, plain text, an LLM prompt block, CSV or JSON.
  Persists in `localStorage`.
- Light/dark following the system with a manual override, keyboard shortcuts (`/` to search,
  `Esc` to dismiss), and a single-column layout with foldable filters on a phone.

### Layout

```
index.html            app shell
assets/app.js         wiring, rendering, URL state
assets/index.js       flattening, accent folding, inverted index, highlighting
assets/store.js       fetch + IndexedDB + manifest version probe
assets/export.js      the export formats (pure functions)
assets/export.test.js node --test assets/export.test.js
assets/app.css        styles
.nojekyll             tell Pages to serve the files verbatim
```

## Development

```bash
pip install -e '.[dev]'
pytest
```

```bash
python -m pytest              # scraper: extraction, normalization, schema, exports
node --test assets/export.test.js   # navigator: the export formats
```

The test suite runs entirely offline. HTML extraction is tested against trimmed copies of real
pages in `tests/fixtures/` — one per markup variant (standard subject with
ejes/habilidades/actitudes, a TP speciality with no strands, a Parvularia page using *núcleos*,
and a PDF-only EPJA page). PDF extraction is tested against `tests/fixtures/pdf_pages/`, which
holds the text blocks and true coordinates captured from one real page of each Programa layout;
the parsers consume exactly that, so the real geometry is exercised without shipping 10 MB PDFs.
Together they cover extraction, id/number/keyword normalization, the statement-verified join
(including the renumbering case and a rejected mis-parse), the schema, the integrity audit's
failure modes, and every export format.

## Politeness

The default crawl makes one request every 1.5 seconds from a single connection, identifies
itself in the `User-Agent`, retries with exponential backoff, and touches no path disallowed by
[robots.txt](https://www.curriculumnacional.cl/robots.txt) (in particular it never hits
`/search/` or the faceted `?f[...]` URLs). Use `--cache` while developing so you fetch each page
once. Please don't lower `--delay` for bulk runs.
