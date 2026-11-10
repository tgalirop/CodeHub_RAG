# Code.Hub site audit

Run: `20261110T115203386830Z`. Crawl finished at 2026-11-10T12:03:41.737216+00:00 (UTC).

## Coverage

| Measure | Result |
| --- | ---: |
| Sitemap URLs | 523 |
| Sitemap documents read (including indexes) | 29 |
| Sitemap inventory complete | True |
| Page URLs attempted | 546 |
| Sample crawl | False |
| Link discovery enabled | True |
| Accepted canonical documents | 542 |
| Documents eligible for retrieval | 167 |
| Chunks | 2356 |
| HTTP/extraction errors | 0 |
| Skipped responses | 4 |
| Remaining crawl queue | 0 |
| Observed internal links outside sitemaps | 23 |

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
| job | 61 |
| job_employment_type | 2 |
| job_industry | 12 |
| job_language | 2 |
| job_location | 3 |
| job_position_type | 2 |
| job_role_category | 37 |
| job_seniority | 7 |
| job_tech_stack | 203 |
| job_working_model | 3 |
| page | 54 |
| post | 7 |
| training | 2 |
| training_catalogue | 2 |

Category counts may overlap when a URL belongs to multiple sitemaps.

## Quality review

- Thin documents: 27.
- Unstructured extraction fallbacks: 0.
- Taxonomy pages remain in the audit and link graph, but produce no retrieval chunks.
- Animated Bricks counters use explicit source targets instead of placeholder zeros.
- Chunk lengths are whitespace word counts, not embedding-model token counts.

### Source metadata warnings

- https://codehub.gr/job/po-525-lead-ml-engineer/
  - Salary unit conflicts with visible monthly amount: jsonld[0].baseSalary.value.unitText
- https://codehub.gr/job/po-559-solution-architect-java/
  - Salary unit conflicts with visible monthly amount: jsonld[0].baseSalary.value.unitText
- https://codehub.gr/job/po-572-application-support-engineer/
  - Salary unit conflicts with visible monthly amount: jsonld[0].baseSalary.value.unitText
- https://codehub.gr/job/po-627-software-development-lead/
  - Salary unit conflicts with visible monthly amount: jsonld[0].baseSalary.value.unitText
- https://codehub.gr/job/po-696-sap-abap-developer/
  - Salary unit conflicts with visible monthly amount: jsonld[0].baseSalary.value.unitText
- https://codehub.gr/job/po-710-qa-engineer/
  - Salary unit conflicts with visible monthly amount: jsonld[0].baseSalary.value.unitText
- https://codehub.gr/job/po-753-erp-coordinator/
  - Salary unit conflicts with visible monthly amount: jsonld[0].baseSalary.value.unitText
- https://codehub.gr/job/po-760-cloud-engineer/
  - Salary unit conflicts with visible monthly amount: jsonld[0].baseSalary.value.unitText
- https://codehub.gr/job/po-763-head-of-data-ai/
  - Salary unit conflicts with visible monthly amount: jsonld[0].baseSalary.value.unitText
- https://codehub.gr/job/po-772-rpa-developer/
  - Salary unit conflicts with visible monthly amount: jsonld[0].baseSalary.value.unitText
- https://codehub.gr/job/po-778-ios-engineer/
  - Salary unit conflicts with visible monthly amount: jsonld[0].baseSalary.value.unitText
- https://codehub.gr/job/po-782-ai-architect/
  - Salary unit conflicts with visible monthly amount: jsonld[0].baseSalary.value.unitText
- https://codehub.gr/job/po-803-net-software-engineer/
  - Salary unit conflicts with visible monthly amount: jsonld[0].baseSalary.value.unitText
- https://codehub.gr/job/po-805-java-web-developer/
  - Salary unit conflicts with visible monthly amount: jsonld[0].baseSalary.value.unitText
- https://codehub.gr/job/po-806-project-manager/
  - Salary unit conflicts with visible monthly amount: jsonld[0].baseSalary.value.unitText
- Further affected documents: 45; see local crawl.json.

Source values are preserved. Warnings need review; no silent date, status or salary correction is applied.

## Errors and exclusions

No recorded sitemap or page-fetch errors.

Skipped responses:

- https://codehub.gr/services/find-talent/recruitment-services/recruitment-services-core/: duplicate_canonical
- https://codehub.gr/services/find-talent/recruitment-services/recruitment-services-lite/: duplicate_canonical
- https://codehub.gr/course_status/completed/: duplicate_canonical
- https://codehub.gr/course_status/open-for-registration/: duplicate_canonical

## Reproducibility

- Extractor: `html-v2`.
- Chunker: `sections-v1`.
- Corpus hash: `a415c513ecd83b576335dd4ea88f79e98ce9ce9671bf6c01ebd9fbd3108f4f19`.
- Local artifacts include source HTML, inventory, document versions and chunks.
- Raw HTML and extracted website content are not included in this repository.

Embeddings, BM25, hybrid retrieval, reranking and answer generation are separate milestones; this report does not establish their quality.

Sources: [robots.txt](https://codehub.gr/robots.txt), [sitemaps](https://codehub.gr/sitemaps.xml), [website](https://codehub.gr/).
