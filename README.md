A Python script used to transfer backups stored on the CrunchyBridge S3 Bucket to AspirEDU's S3 Bucket.


## Contributing

Install pre-commit hooks:

```bash
pre-commit install
```

Install dependencies

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Updating Python dependencies

```bash
source venv/bin/activate
pip-compile --upgrade
```
