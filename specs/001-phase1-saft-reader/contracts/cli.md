# Contract: Phase 1 reader command line

Phase 1 has no network API; its interfaces are a command and a Python function.

## Command

```
python phase-1/saft_reader.py <saft.xml> [-o <output.json>]
```

| Argument | Default | Meaning |
|---|---|---|
| `<saft.xml>` | required | Norwegian SAF-T Financial XML file |
| `-o, --output` | `phase-1/saft_data.json` | Where to write the reference file |

| Exit code | Meaning | Output file |
|---|---|---|
| `0` | Success (warnings, if any, are in `summary.warnings`) | Written atomically |
| `1` | File unreadable or not well-formed XML | Not written; existing file untouched |
| `2` | Not a Norwegian SAF-T file (root element or namespace) | Not written; existing file untouched |

On success, a one-line human summary goes to stdout, e.g.
`saft_data.json: 9 accounts, 4 VAT codes, 6 suppliers, 3 mapped / 3 unknown`.
On error, a single line `error: <message>` goes to stderr.

## Python API (for later phases and tests)

```python
from saft_reader import read_saft, write_saft_data, SaftReaderError

data: dict = read_saft("samples/saft_sample.xml")          # raises SaftReaderError(exit_code, msg)
write_saft_data(data, "phase-1/saft_data.json")            # atomic write
```

`read_saft` returns a dict matching [saft_data.schema.json](saft_data.schema.json). It performs no
network access and calls no LLM (FR-015).
