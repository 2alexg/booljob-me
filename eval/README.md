# eval/

Offline evaluation only (design doc §5.A, tasks S1-17 and S1-18).

- Holds the LLM-generated **synthetic** Hebrew CVs and the embedding-model comparison.
- **Never load anything from this directory into Supabase, Storage, or any deployed environment.**
- Embeddings computed here stay local to `eval/`.
