---
id: EDP-RM-001
title: Document management guide
version: 1.0.0
status: review
entity: Ediphor Limited
author: Emilian Świtalski
created: 2026-04-17T00:00:00.000Z
updated: 2026-04-17T00:00:00.000Z
sign: false
address: Niddry Lodge, 51 Holland St, London W8 7JB, UK
logo: ediphor.svg
---


# Document management guide

How to write and maintain documents rendered by PDFMarQ.

## Frontmatter

Every document starts with a YAML block between `---` markers. This block controls the header on page 1 and the mini-header on continuation pages. All fields are optional.

```yaml
---
id: EDP-RM-042                                           # document code (unique)
title: General reference manual                          # main title
version: 2.1.3                                           # version (no "v" prefix)
status: approved                                         # draft/review/approved/deprecated/archived
entity: Ediphor Limited                                  # organization, firm
address: Niddry Lodge, 51 Holland St, London W8 7JB, UK  # address
logo: ./ediphor.svg                                      # relative to this file (.svg/.png/.jpg)
author: Emilian Świtalski                                # person responsible for this version
created: 2024-09-15                                      # first written (YYYY-MM-DD, set once, never change)
updated: 2026-03-22                                      # last content change (YYYY-MM-DD)
sign: true                                               # adds signature line at the end
---
```

## Statuses

| Status       | Color     | Meaning                                                       |
| ------------ | --------- | ------------------------------------------------------------- |
| `draft`      | blue-grey | Work in progress. Content is incomplete or unreviewed.        |
| `review`     | amber     | Content is complete and waiting for approval.                 |
| `approved`   | green     | Officially accepted. This is the current, binding version.    |
| `deprecated` | red       | Still accessible but no longer recommended. Being phased out. |
| `archived`   | violet    | Historical record only. Not valid for current use.            |

Typical flow: `draft` → `review` → `approved` → `deprecated` → `archived`. Not every document goes through all stages.

Only one version of a document should be `approved` at a time. When approving a new version, the previous one should move to `deprecated` or `archived`.

## Versioning

Format: **MAJOR.MINOR.PATCH** _(e.g. `2.1.3`)_.

- **MAJOR**: document fundamentally rewritten, old references may no longer apply
- **MINOR**: sections added, removed, or significantly reworked
- **PATCH**: typos, wording improvements, formatting fixes that don't affect meaning

When incrementing MAJOR, reset MINOR and PATCH to zero. When incrementing MINOR, reset PATCH to zero. First release is `1.0.0`. Use `0.x.x` only for early drafts before first review.

Do not add a `v` prefix in the frontmatter. Write `version: 2.1.3`, not `version: v2.1.3`. The renderer displays the number as-is.

## Rules

Changing the status _(e.g. `review` → `approved`)_ does **not** require updating `version` or `updated`. Status reflects an administrative decision, not a change to content.

Update the `updated` date when you change content: rewrite text, fix factual errors, add or remove sections. Do not update it for status changes, meaningless typos, formatting adjustments, or `author` field changes.

The `created` date is set once when the document is first written. Never change it, even across major version bumps.

The `sign` field adds a dashed signature line with space for a handwritten signature at the end of the document. Use for documents that require physical sign-off. Leave out for informational documents.

## Document ID convention

Recommended format: `[UNIT]-[TYPE]-[NUMBER]`

- **UNIT**: company, department, or project code _(e.g. `EDP`)_
- **TYPE**: document type abbreviation _(e.g. `PRD`, `FW`, `RM`)_
- **NUMBER**: sequential number, zero-padded _(e.g. `001`, `042`)_

The ID appears in the header on every page. Keep it short enough to fit next to the title in the mini-header.