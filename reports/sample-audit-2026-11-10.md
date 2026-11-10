# Code.Hub site audit

Run: `20261110T114648439705Z`. Crawl finished at 2026-11-10T11:47:32.555731+00:00 (UTC).

## Coverage

| Measure | Result |
| --- | ---: |
| Sitemap URLs | 518 |
| Sitemap documents read (including indexes) | 29 |
| Sitemap inventory complete | True |
| Page URLs attempted | 15 |
| Sample crawl | True |
| Link discovery enabled | False |
| Accepted canonical documents | 15 |
| Documents eligible for retrieval | 6 |
| Chunks | 71 |
| HTTP/extraction errors | 0 |
| Skipped responses | 0 |
| Remaining crawl queue | 0 |
| Observed internal links outside sitemaps | 10 |

Coverage is limited to the configured public HTML scope and URLs visible in this run. A drained queue does not prove that every page on the website was found. PDFs, external domains, authenticated pages and JavaScript-rendered content are excluded.

## Sitemap categories

| Category | URLs |
| --- | ---: |
| category | 8 |
| course | 46 |
| course_ai_enablement | 2 |
| course_audience | 4 |
| course_catalogue | 3 |
| course_category | 19 |
| course_certification_body | 3 |
| course_delivery_format | 1 |
| course_difficulty | 3 |
| course_language | 2 |
| course_product_type | 2 |
| course_status | 2 |
| course_technology | 27 |
| course_training_type | 5 |
| job | 60 |
| job_employment_type | 2 |
| job_industry | 12 |
| job_language | 2 |
| job_location | 3 |
| job_position_type | 2 |
| job_role_category | 37 |
| job_seniority | 7 |
| job_tech_stack | 199 |
| job_working_model | 3 |
| page | 54 |
| post | 7 |
| training | 2 |
| training_catalogue | 2 |

Category counts may overlap when a URL belongs to multiple sitemaps.

## Quality review

- Thin documents: 4.
- Unstructured extraction fallbacks: 0.
- Taxonomy pages remain in the audit and link graph, but produce no retrieval chunks.
- Animated Bricks counters use explicit source targets instead of placeholder zeros.
- Chunk lengths are whitespace word counts, not embedding-model token counts.

### Source metadata warnings

- https://codehub.gr/job/po-525-lead-ml-engineer/
  - Salary unit conflicts with visible monthly amount: jsonld[0].baseSalary.value.unitText
- https://codehub.gr/training/aws-discovery-day-cloud-practitioner/
  - Invalid source date at jsonld[0].startDate: 0207-20-26
  - Invalid source date at jsonld[0].endDate: 0207-20-26
  - Scheduled event conflicts with visible Completed label: jsonld[0].eventStatus

Source values are preserved. Warnings need review; no silent date, status or salary correction is applied.

## Errors and exclusions

No recorded sitemap or page-fetch errors.

## Reproducibility

- Extractor: `html-v2`.
- Chunker: `sections-v1`.
- Corpus hash: `02e784df009be2b7bed549a92b045aff996a4a045ef05907b336233f3d50ce22`.
- Local artifacts include source HTML, inventory, document versions and chunks.
- Raw HTML and extracted website content are not included in this repository.

Embeddings, BM25, hybrid retrieval, reranking and answer generation are separate milestones; this report does not establish their quality.

Sources: [robots.txt](https://codehub.gr/robots.txt), [sitemaps](https://codehub.gr/sitemaps.xml), [website](https://codehub.gr/).
