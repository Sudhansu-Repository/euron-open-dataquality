# Deploy to AWS

The Terraform in `infra/terraform/` builds a production deployment. The maintainers develop
against the local emulator: the AWS environments pass `terraform validate`, tflint and
checkov, and the full `aws-dev` environment is planned, applied, re-planned and destroyed
against Floci in the gates (`make tf-aws-on-floci`). Applying it to a real account is your
step; read the plan before you apply.

## What it builds

| Module | Resources |
| --- | --- |
| `network` | VPC across two or three availability zones, public and private subnets, NAT (one shared or one per zone), an S3 gateway endpoint, optional interface endpoints, encrypted flow logs |
| `database` | RDS PostgreSQL 16 in private subnets, encrypted with the KMS key, TLS enforced, the master password in Secrets Manager |
| `cache` | ElastiCache (Valkey by default) for rate limits and the dashboard cache, TLS and an AUTH token. Nothing in it is the only copy of anything |
| `storage` | The objects bucket (uploaded files and versions, pushed batches, SQLite databases), SSE-KMS, versioning, public access blocked, TLS only |
| `kms` | One customer-managed key with rotation: seals stored credentials (encryption context `dataquality:record`) and encrypts the bucket, RDS, ElastiCache, Secrets Manager and logs |
| `secrets` | Secrets Manager entries injected into the containers: `SESSION_SECRET`, `API_KEY_PEPPER`, and `DATABASE_URL` and `REDIS_URL` |
| `ecr` | Repositories for the `api` image (also the worker, migrate and seed) and the `web` image |
| `email` | An SES domain identity with DKIM for alert mail, and a policy that lets the api and worker send only as the configured address |
| `service` | ECS Fargate services for `api`, `worker` and `web` behind one ALB with HTTPS and WAF, plus a `migrate` task definition for one-off commands. The worker gets ephemeral storage for scan temp files |
| `observability` | CloudWatch log groups, metric filters on the worker's logs (scans, failed scans, re-queued scans, worker errors), alarms to an SNS topic, a dashboard |

The application settings come from the environment the `aws-dev` and `aws-prod` environments
pass to the service module: `ENVIRONMENT=production`, `DATAQUALITY_CLOUD=aws`,
`KEY_MODE=kms`, `STORAGE=s3`, `MAIL_BACKEND=ses`, `COOKIE_SECURE=true`, `CORS_ORIGINS` and
`PUBLIC_URL` from your host name, and `FORWARDED_ALLOW_IPS` set to the VPC range. Extra
non-secret settings go in `api_extra_environment` (for example `WORKER_CONCURRENCY` or
`DUCKDB_MEMORY_LIMIT`; see [configuration.md](configuration.md)).

## Network reach to your databases

The api (connection tests, previews) and the worker (scans) open connections to the
databases you register. By default they may reach any address on the database ports; set
`source_cidrs` in `terraform.tfvars` to the networks your databases are in. Databases in
another VPC need peering, a transit gateway or a private link to this VPC. A self-hosted AI
model inside your network is allowed with `ai_egress`.

## Before you start

- Terraform 1.16 (or Docker: the Makefile runs the pinned image), Docker with buildx, the
  AWS CLI with credentials for the target account.
- A domain, an ACM certificate for the host name in the same region, and ideally a Route53
  hosted zone.
- SES out of the sandbox for alerts to unverified recipients (request production access).

## Deploy

```bash
cd infra/terraform/envs/aws-dev
cp terraform.tfvars.example terraform.tfvars        # name prefix, host name, certificate, mail domain, image tag
cp backend.tf.example backend.tf                    # optional: remote state (S3 bucket and lock table)
cd -
make aws-deploy ENV=aws-dev TAG=0.1.0
```

`scripts/aws-deploy.sh` then:

1. applies the image registries (and the KMS key that encrypts them);
2. builds the `api` and `web` images for the cluster's architecture (ARM64) and pushes them;
3. applies everything else with that image tag;
4. runs the database migrations as a one-off ECS task;
5. waits for the api, worker and web services to become stable.

Create the first admin:

```bash
DATAQUALITY_ADMIN_PASSWORD='...' make aws-admin ENV=aws-dev EMAIL=you@example.com
```

Or open the site and sign up: the first account on a fresh instance becomes the admin, and
sign-up closes after it. `make aws-migrate ENV=...` runs migrations again after an upgrade;
`make aws-plan ENV=...` shows a plan.

## `aws-dev` and `aws-prod`

Both use the same modules. `aws-dev` is sized and configured to be cheap and disposable (one
NAT gateway, a single-AZ database with short backups and no deletion protection, one cache
node, one worker, short log retention). `aws-prod` spans three zones with a NAT gateway per
zone and interface endpoints, Multi-AZ RDS with 14 days of backups and deletion protection,
two cache nodes, two workers, and a year of log retention. Compare the two `main.tf` files
before you choose; both size the database pools so that every task's connections stay under
the database's limit.

## After deploying

- Point DNS at the load balancer if Terraform did not (the `load_balancer_dns_name` output).
- Add the DKIM records from the `dkim_records` output if you have no Route53 zone.
- Subscribe to the alarm topic (`alarm_email`).
- Keep the worker's `/metrics` inside the task; to scrape the API's `/metrics` from your
  Prometheus, list its address in `metrics_allowed_cidrs`.
- Read [operations.md](operations.md) for backups, scaling and upgrades, and the operator
  checklist in [security.md](../architecture/security.md#operator-checklist).
