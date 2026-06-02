# packages/config

Runtime YAML config, model catalog data, seed defaults, sample policies,
and JSON Schemas derived from Pydantic settings models. The backend ships
the same Pydantic classes; this package publishes them as machine-readable
schemas so operators and the frontend can validate config without a
running FastAPI process.

## Layout

```
config/
├── app_config.yml                  # product knobs loaded by app.core.app_config
├── llm/
│   └── catalog.yml                 # OpenRouter model routes and caps
├── seeds/
│   └── rubric_rules.yml            # starter priority rubric
├── samples/
│   └── user_preferences.sample.json
└── schemas/
    ├── user_preferences.schema.json
    ├── connected_account.schema.json
    └── rubric_rule.schema.json
```

`app_config.yml` and `llm/catalog.yml` are loaded at backend boot. Lambda
runtimes fail fast when either file is missing or malformed; local and test
runs fall back to `app_config` model defaults but never fall back for the
LLM catalog.
