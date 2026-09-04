This specification outlines the technical requirements, schema design, and execution architecture for **`mineduc-curriculum-db`**, an open-source scraper and dataset builder that extracts Chilean MINEDUC standards from `curriculumnacional.cl` into a structured, lightweight JSON database optimized for local-first web applications and LLM context injection.

---

### 1. Specification Overview

* **Repository Goal**: Scrape, structure, validate, and export 100% of MINEDUC *Objetivos de Aprendizaje* (OAs), evaluation indicators (*Indicadores*), skills (*Habilidades*), attitudes (*Actitudes*), and transversal goals (*OATs*) across 1° Básico through 4° Medio.
* **Target Output**: Single or split static `.json` files, validated against a JSON Schema.
* **Primary Consumers**: Local-first web apps (IndexedDB, SQLite-WASM), LLM prompt builders, and curriculum-mapping software.
* **License**: MIT License (Code) / Public Domain (Dataset).

---

### 2. Canonical JSON Schema Definition

```typescript
interface MineducCurriculumDB {
  metadata: {
    scraped_at: string; // ISO-8601
    source_url: string;
    total_oas: number;
    schema_version: string; // e.g. "1.0.0"
  };
  levels: Record<string, LevelData>;
}

interface LevelData {
  level_id: string; // e.g., "3_4_medio"
  level_name: string; // "3° y 4° Medio"
  subjects: Record<string, SubjectData>;
}

interface SubjectData {
  subject_id: string; // e.g., "geometria_3d"
  subject_name: string; // "Geometría 3D"
  track: "plan_comun" | "plan_diferenciado_hc" | "plan_diferenciado_tp";
  learning_objectives: Objective[];
  transversal_objectives?: TransversalObjective[];
}

interface Objective {
  oa_id: string; // Global canonical ID: "CL_MAT_34M_GEO_OA01"
  oa_number: number; // 1
  category: "conocimiento" | "habilidad" | "actitud";
  strand_eje?: string; // e.g., "Geometría"
  statement: string; // Raw legal text
  indicators?: string[]; // Granular performance indicators
  skills_oah?: string[]; // Mapped OAH codes
  keywords?: string[]; // Extracted search tags
}

interface TransversalObjective {
  oat_id: string; // e.g., "CL_OAT_DIM_COGNITIVA_06"
  dimension: string; // "Cognitiva-Intelectual", "Afectiva", etc.
  statement: string;
}

```

---

### 3. System Architecture & Pipeline

```
[ curriculumnacional.cl ] 
       │
       ▼ (Crawler & Rate Limiter: 1.5s delay)
[ DOM Parser / HTML Extraction ] ────► [ Fallback: PDF Parsing (fitz/pdfplumber) ]
       │
       ▼
[ Data Normalizer & Tag Generator ]
       │
       ▼
[ Schema & Integrity Validator ] (Asserts OA count per level)
       │
       ├──► output/mineduc_curriculum_full.json
       └──► output/mineduc_curriculum_sqlite.db

```

#### Module Specifications

| Module | Tech Stack | Responsibility |
| --- | --- | --- |
| **Scraper Core** | Python, `httpx`, `selectolax` | Navigates level/subject hierarchies on `curriculumnacional.cl`, fetching raw HTML pages using polite rate limits (1.5s delay). |
| **Extractor** | `BeautifulSoup4` or `pydantic` | Parses DOM selectors (`.oa-title`, `.indicadores-list`, `.eje-header`), preserving exact text string matches. |
| **Normalizer** | Custom Python Engine | Generates deterministic global IDs (e.g., `CL_MAT_34M_GEO_OA01`), strips whitespace, and extracts keyword arrays. |
| **Validator** | `jsonschema`, `pytest` | Runs assertion checks to verify no OAs are empty, missing text, or dropped during parsing. |

---

### 4. CLI Interface Design

The tool will expose a simple command-line interface:

```bash
# Install dependencies
pip install mineduc-scraper

# Scrape all high school standards (7° Básico to 4° Medio)
mineduc-scraper scrape --levels 7B,8B,1M,2M,3M,4M --output ./data/curriculum.json

# Run coverage audit & validation against generated file
mineduc-scraper validate --file ./data/curriculum.json

# Export a lightweight version (OAs only, no detailed indicators) for client-side LLM context
mineduc-scraper export-slim --file ./data/curriculum.json --output ./data/curriculum_slim.json

```

---

### 5. In-Browser / LLM Integration Pattern

The output JSON file is designed to be loaded directly into client-side web apps for offline indexing or RAG workflows:

```javascript
// Browser / Web App Integration Example
import curriculumDB from './curriculum_slim.json';

// Query OAs for a specific subject module
export function getSubjectOAs(levelId, subjectId) {
  return curriculumDB.levels[levelId]?.subjects[subjectId]?.learning_objectives || [];
}

// Generate context block for LLM prompts
export function buildLLMContext(levelId, subjectId) {
  const oas = getSubjectOAs(levelId, subjectId);
  return oas.map(oa => `[${oa.oa_id}] ${oa.statement}`).join('\n');
}

```