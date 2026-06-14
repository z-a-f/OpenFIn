# Future Work

## Deferred API layer

`f ask` and `f plan` stay out of the base CLI until the provider and spend model are
explicitly chosen. The intended shape is:

- build prompts from `f context` profiles and topic search
- cache summaries by source-file hash so unchanged context is not re-summarized
- log each API call with model, token counts, estimated cost, and task/profile context
- keep all base commands local-only; API calls happen only through explicit API commands

## Local AI housekeeping

Phase 2 keeps dedup deterministic for reliability and speed. Later adapters can add
semantic help behind the same proposal-only boundary:

- Ollama adapter for local summarization and dedup when `ollama` is installed
- llama.cpp command adapter for quantized local models
- no automatic task mutation from model output; model suggestions must still be confirmed

## Cofounder memory sync

`f assign` records ownership locally. Authorized-subset sync is deferred until the
collaboration workflow is clearer, likely as a profile-based export/import bundle
before any networked sync.
