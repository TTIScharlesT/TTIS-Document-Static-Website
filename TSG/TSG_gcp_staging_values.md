# GCP staging values

Date captured: 2026-06-20

These values define the staging target for integrating TSG License Manager into the existing GCP-hosted Virtual Business Solution.

## Core GCP resources

| Value | Setting |
|---|---|
| GCP project ID | `ttis-ai` |
| Region | `us-central1` |
| Artifact Registry repository | `tsg-platform` |
| Artifact image | `tsg-license-manager` |
| Cloud Run service | `tsg-license-manager-staging` |
| Cloud SQL instance | `tsg-license-manager-staging` |
| Cloud SQL database | `tsg_license_manager` |
| Cloud SQL user | `tsg_app` |
| Staging base URL | `https://license-staging.tti-solutions.com` |
| Allowed hosts | `license-staging.tti-solutions.com,docguard-ai-staging.tti-solutions.com,pursuite-staging.tti-solutions.com` |

## Product portal values

| Product | Runtime product ID | Portal URL | Notes |
|---|---|---|---|
| DocGuard AI | `docguard_ai` | `https://docguard-ai-staging.tti-solutions.com` | Commercial product name. The former `sanitize_*` / Sanitize Suite naming was a development codename and is retired. Hostname normalized from the invalid `https://DocGuard AI-staging.tti-solutions.com`; DNS hostnames cannot contain spaces. |
| Pursuite | `pursuite_crm` | `https://pursuite-staging.tti-solutions.com` | Aligns with the existing seeded product ID for Pursuite. |

## Image path

```text
us-central1-docker.pkg.dev/ttis-ai/tsg-platform/tsg-license-manager:0.2.0-rc.1
```

## Cloud SQL connection name

```text
ttis-ai:us-central1:tsg-license-manager-staging
```

## Secret Manager names

| Environment variable | Secret Manager name |
|---|---|
| `DATABASE_URL` | `tsg-license-manager-staging-database-url` |
| `TSG_AUTH_SECRET` | `tsg-license-manager-staging-auth-secret` |
| `TSG_LICENSE_SIGNING_SECRET` | `tsg-license-manager-staging-license-signing-secret` |
| `TSG_CLIENT_API_SECRET` | `tsg-license-manager-staging-client-api-secret` |
| `STRIPE_WEBHOOK_SECRET` | `tsg-license-manager-staging-stripe-webhook-secret` |
| `SMTP_PASSWORD` | `tsg-license-manager-staging-smtp-password` |

## Open decisions

1. Confirm whether product portal hostnames route directly to the License Manager service or through the existing Virtual Business Solution ingress.
2. Confirm the SMTP provider and non-secret SMTP host/user/from settings for staging.
3. Confirm the Stripe test-mode webhook endpoint and secret for staging.

## Retired development codename

`sanitize_suite`, `sanitize_suite_pro`, `Sanitize Suite`, and `SSP` were development codenames. They should not appear in customer-facing staging evidence for DocGuard AI. If backward compatibility is needed for existing local/dev data, map retired IDs to `docguard_ai` during migration rather than exposing the old names in portals or documentation.
