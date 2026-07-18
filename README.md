# RentDirect

Server-based RentDirect marketplace built with Django REST Framework, ECS Fargate, RDS PostgreSQL, Redis/ElastiCache, S3, and CloudFront.

## Repository Structure

```text
rentdirect/
├── apps/
│   ├── api/              # Django backend
│   ├── web/              # Vite + React frontend
│   └── worker/           # Reserved for background jobs
├── packages/
│   ├── config/           # Shared configuration package placeholder
│   ├── types/            # Shared type contracts placeholder
│   ├── ui/               # Shared UI package placeholder
│   └── utils/            # Shared utilities package placeholder
├── infra/
│   ├── kubernetes/       # Reserved for future cluster manifests
│   ├── scripts/          # Deploy, bootstrap, migration, and secret helpers
│   └── terraform/        # Terraform root module, envs, and reusable modules
├── docs/
├── .github/
├── package.json
├── turbo.json
└── README.md
```

## Local Development

```bash
docker compose up --build
```

- Frontend: <http://localhost:3600>
- API: <http://localhost:8600/api/v1>
- Health: <http://localhost:8600/api/health/ready>

## Production Shape

- `api.rentdirect.homes` routes to an ALB-backed ECS service.
- `rentdirect.homes` and `development.rentdirect.homes` serve the Vite build from private S3 through CloudFront OAC.
- Media files are stored in a private S3 bucket and served through a dedicated CloudFront media distribution.
- RDS and Redis live in private subnets and accept traffic only from ECS tasks.
