# Batch runner for generative pipelines

This harness lets you launch grouped requests to all generative functions, capture detailed JSONL traces, and summarize runs for post-analysis.

## Files
- configs/batch_example.yaml – template config for a batch.
- tools/run_batch.py – async runner that executes cases and writes per-run JSONL + meta.
- tools/summarize_run.py – produces markdown summaries (and optional comparison).
- reports/runs/ – default location for outputs (created automatically).

## Quick start
1) Edit configs/batch_example.yaml or create your own config.
2) Run the batch:
   - python tools/run_batch.py --config configs/batch_example.yaml
   - Optional: --run-id my_run --limit 3 --dry-run
3) Summarize results:
   - python tools/summarize_run.py --run-id <generated_run_id>
   - Compare two runs: python tools/summarize_run.py --run-id runA --compare runB

## Config essentials
- run.max_concurrency – number of concurrent tasks.
- run.timeout_sec – per-task timeout; 0 disables timeout.
- run.retries / run.backoff_sec – transient retry policy.
- run.collect_events – attach pipeline events if handler supports event_callback.
- run.keep_full_context – if false, trims ctx.data to run.result_keys.
- cases[].handler – "pipeline.lesson", "pipeline.diagnostic", "internal.echo", or import path "module:function".
- cases[].variants – list of param overrides; each becomes a variant.
- cases[].repeat – repeat count per variant (default 1).
- cases[].params – base kwargs passed to the handler.
 - eval.evaluator – optional callable to compute quality scores per record.
 - metrics.extractor – optional callable to compute tokens_in/out and extra metrics.

## Outputs per run
- reports/runs/<run_id>.jsonl – one JSON object per executed case.
- reports/runs/<run_id>.errors.jsonl – only error records, one per line.
- reports/runs/<run_id>.csv – flat table for quick inspection (case, status, latency).
- reports/runs/<run_id>_agg.csv – grouped aggregates by `run.group_keys`.
- reports/runs/<run_id>.parquet – full records (if pandas/pyarrow available).
- reports/runs/<run_id>.meta.json – summary (counts, latency percentiles, errors).
- reports/runs/<run_id>_summary.md – human-readable report from summarize_run.py.
- reports/runs/<run_id>_summary.csv – flat CSV summary.
- reports/runs/<run_id>_dashboard.html – interactive charts (Plotly if installed).

## Record schema (JSONL)
- run_id, case_id, base_id, variant, attempt, handler, status
- started_at / ended_at (ISO), latency_ms
- params (as passed), result (trimmed if configured), events (if collected)
- eval_scores (from evaluator or built-ins)
- error (if any), tokens_in / tokens_out (from metrics extractor), metrics (extra fields)

## Quality Metrics Evaluation
The `eval` section in config enables optional quality scoring (BLEU, ROUGE-L, exact match) if gold/reference outputs are provided.

**Available evaluators:**
- `tools.evaluators:basic_heuristics` – scores presence/length of common output fields (default).
- `tools.evaluators:with_quality_metrics` – computes BLEU, ROUGE-L, and exact match scores if gold reference(s) provided in case spec.

**Example config with gold references:**
```yaml
cases:
  - id: "lesson-1"
    handler: "pipeline.lesson"
    params: {target_lang: "en", cefr_level: "A2"}
    gold_reference: "Expected lesson content here..."  # or
    gold_references: ["Reference 1", "Reference 2"]   # multiple valid alternatives
    
eval:
  evaluator: "tools.evaluators:with_quality_metrics"
  params: {}
```

**Quality metrics explained:**
- **BLEU**: Precision-based n-gram overlap with reference (0-1). Higher is better. Good for fluency and coherence.
- **ROUGE-L**: Longest common subsequence recall (0-1). Captures semantic preservation.
- **Exact Match**: Normalized token-level exact match (0 or 1). Only 1.0 if perfectly matching reference.

**Output in JSONL `eval_scores`:**
```json
{
  "bleu": 0.244,
  "rouge_l": 0.061,
  "exact_match": 0.0,
  "metrics": {
    "num_references": 1,
    "hypothesis_length": 56,
    "reference_length": 134
  }
}
```

**Implementing a custom evaluator:**
```python
def my_evaluator(spec, result_payload, events, cfg):
    # spec: case spec with optional gold_reference/gold_references
    # result_payload: handler's result dict
    # events: list of pipeline events
    # cfg: eval.params from config
    return {
        "custom_score_1": <float>,
        "custom_score_2": <float>,
    }
```

## Notes
- Built-in handlers: pipeline.lesson, pipeline.diagnostic, internal.echo (for tests).
- For custom handlers, set cases[].handler to "pkg.module:function"; the runner will import and call it. If it accepts event_callback, it will be wired automatically.
- Optional evaluator: set `eval.evaluator` to a callable like `tools.evaluators:basic_heuristics` to compute `eval_scores`.
- Optional metrics extractor: set `metrics.extractor` to a callable like `tools.metrics:real_tokens` to fill `tokens_in/out` and populate optional `metrics` field.
- JSONL is append-only per run; each run_id writes a fresh file (existing file is overwritten).

## Dashboard & Visualization
The summarizer generates an interactive HTML dashboard with charts:
- **Latency distribution**: histogram of request times per case
- **Status per handler**: grouped bar chart (OK/Error counts)
- **Token burn**: per-handler token consumption (input vs output)
- **Cost-speed tradeoff**: scatter plot of output tokens vs latency

Requires: `pandas` and `plotly` for interactive charts. Falls back to minimal HTML if unavailable.
