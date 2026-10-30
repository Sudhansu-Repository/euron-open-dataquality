# Local stack against real AWS

`make up-aws` runs the same containers as `make up`, but the API, the scan worker and the
migrations use a real KMS key and S3 bucket instead of Floci. Postgres, Redis, Mailpit, the
demo source databases and the web app stay local. Use it to check the AWS code paths with
your own account.

```bash
cd infra/terraform/envs/aws-dev && terraform apply -target=module.kms -target=module.storage   # or use your own key and bucket
cd -
cp deploy/compose/.env.aws.example deploy/compose/.env.aws    # fill in OBJECTS_BUCKET and KMS_KEY_ID from terraform output
make up-aws
```

`deploy/compose/.env.aws` holds `AWS_REGION`, optionally `AWS_PROFILE`, `OBJECTS_BUCKET` and
`KMS_KEY_ID`; it is git-ignored. Credentials come from your AWS CLI profile, mounted
read-only into the containers that call AWS (api, worker, migrate); nothing in the
repository holds a static key. The overlay sets `DATAQUALITY_CLOUD=aws`, `STORAGE=s3` and
`KEY_MODE=kms`.

What changes: uploaded files, pushed batches and SQLite databases are written to and read
from S3 (SSE-KMS), and source passwords, REST headers, Slack and webhook URLs and the AI key
are sealed with KMS `Encrypt` with an encryption context bound to their row. Alert mail
still goes to Mailpit. Everything else behaves exactly as in `make up`.

Sealed values are tied to the key that sealed them: data created under `make up` (sealed by
Floci's KMS or the local key) cannot be opened under `make up-aws`, and the reverse. Run
`make down` between the two, or re-enter connection passwords.
