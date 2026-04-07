# Batch Target File Format

Use pipe-separated lines:

```text
target|phone1,phone2|username1,username2
```

Rules:

- Empty lines are ignored.
- Lines starting with `#` are ignored.
- Phones and usernames are optional.
- Missing columns are allowed (parser auto-fills blanks).

## Examples

```text
Example Target A|+380501112233,+380671112233|example_a,example.a
Example Target B|+4748650767|example_b
Example Target C||example_c
Example Target D||
```

## Run Command

```bash
python src/run_discovery.py \
  --targets-file examples/targets.txt \
  --mode fast-lane \
  --verify \
  --output runs/exports/html/dossiers/batch_fast.html
```
