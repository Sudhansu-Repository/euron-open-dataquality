# `email` module

Amazon SES for alert mail: a domain identity with Easy DKIM (records in Route53 when a zone is given, otherwise in the `dkim_records` output), a configuration set with TLS required, reputation metrics, bounce and complaint suppression, and a CloudWatch event destination. `send_policy_json` lets the api and the scan worker send only as `from_address` and only through this identity. New accounts start in the SES sandbox: request production access before alerting recipients outside verified addresses.

## Inputs

| Name | Description | Type | Default |
|---|---|---|---|
| `name_prefix` | Prefix for every resource name. | `string` | required |
| `domain` | Domain mail is sent from (an SES domain identity), e.g. dq.example.com. | `string` | required |
| `from_address` | The only From address the api and worker may send as, e.g. alerts@dq.example.com. | `string` | required |
| `route53_zone_id` | Hosted zone that receives the DKIM records. Null: create them yourself (dkim_records output). | `string` | `null` |

## Outputs

| Name | Description |
|---|---|
| `identity_arn` | SES domain identity ARN. |
| `configuration_set_name` | SES configuration set every message goes through (bounce and complaint metrics). |
| `send_policy_json` | IAM policy for the api task role: send only as from_address, only through this identity. |
| `dkim_records` | DKIM CNAMEs to publish when no Route53 zone is given: name => value. |
