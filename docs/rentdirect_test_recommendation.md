# RentDirect Test Recommendation Document

**Date:** 2026-06-21  
**Project:** RentDirect Rental Marketplace  
**Goal:** Production-grade test coverage across backend, frontend, infrastructure, and security

---

## Table of Contents

1. [Backend Testing (Django API)](#1-backend-testing-django-api)
2. [Frontend Testing (React)](#2-frontend-testing-react)
3. [Integration/API Testing](#3-integration-api-testing)
4. [Performance & Stress Testing](#5-performance--stress-testing)
5. [Chaos Engineering](#6-chaos-engineering)
6. [Security Testing](#7-security-testing)
7. [Code Quality & Analysis](#8-code-quality--analysis)
8. [Monitoring & Observability](#9-monitoring--observability)
9. [Implementation Roadmap](#10-implementation-roadmap)

---

## 1. Backend Testing (Django API)

### 1.1 Unit Tests

**Purpose:** Test individual functions, methods, and model logic in isolation.

**Tools:** `pytest-django`, Django TestCase

**Implementation Steps:**

1. Install pytest and pytest-django:

   ```bash
   pip install pytest pytest-django pytest-cov
   ```

2. Create `apps/api/pytest.ini`:

   ```ini
   [pytest]
   DJANGO_SETTINGS_MODULE = config.settings.test
   python_files = test_*.py *_tests.py
   python_classes = Test*
   python_functions = test_*
   addopts = --cov=core --cov-report=html --cov-report=term-missing
   ```

3. Expand coverage for:
   - Model methods in `core/models.py`
   - Serializer validation in `core/serializers.py`
   - Pricing calculations in `core/pricing.py`
   - Security utilities in `core/security.py`
   - Tenant scoring in `core/tenant_scoring.py`

4. Target untested modules:
   - Views (viewsets, permissions)
   - Authentication backends
   - Middleware
   - Management commands

### 1.2 API Integration Tests

**Purpose:** Test HTTP endpoints with authentication and business logic.

**Tools:** `pytest-django`, `pytest-requests`, Django APIClient

**Implementation Steps:**

1. Create test file structure:

   ```
   apps/api/core/tests/
   ├── __init__.py
   ├── test_auth.py
   ├── test_listings.py
   ├── test_bookings.py
   ├── test_payments.py
   ├── test_verification.py
   ├── test_users.py
   ├── test_admin.py
   └── conftest.py
   ```

2. Implement authentication fixtures in `conftest.py`:

   ```python
   @pytest.fixture
   def api_client():
       return APIClient()
   
   @pytest.fixture
   def tenant_user(db):
       return AppUser.objects.create_user(
           email="tenant@test.com",
           password="testpass123",
           role=AppUser.Role.TENANT,
           email_verified=True
       )
   
   @pytest.fixture
   def landlord_user(db):
       return AppUser.objects.create_user(
           email="landlord@test.com",
           password="testpass123",
           role=AppUser.Role.LANDLORD,
           email_verified=True
       )
   ```

3. Test all endpoint categories:
   - `GET /api/v1/listings/search` - filter combinations
   - `POST /api/v1/listings` - validation, permissions
   - `POST /api/v1/bookings` - date validation, pricing
   - `POST /api/v1/payments` - amount limits, overpayment prevention
   - `PATCH /api/v1/bookings/{id}/rental-progress` - step ordering
   - `POST /api/v1/auth/register/verify` - OTP validation

### 1.3 Model Validation Tests

**Purpose:** Verify model constraints, clean methods, and signal handlers.

**Implementation Steps:**

1. Test model `save()` methods and property methods
2. Test custom managers and QuerySets
3. Test model-level validation:

   ```python
   def test_booking_cannot_overlap_active_booking(self):
       # Prevent double-booking same listing
       pass
   
   def test_listing_requires_verified_landlord(self):
       # Landlord must be verified to create listings
       pass
   ```

### 1.4 Authentication/Authorization Tests

**Purpose:** Validate JWT authentication, OTP, and role-based access controls.

**Implementation Steps:**

1. Test unverified user access restrictions
2. Test OTP attempt limiting (brute force prevention)
3. Test role-based endpoint access:
   - Tenant cannot access landlord-only endpoints
   - Landlord cannot modify another's listing
   - Admin-only endpoints blocked for regular users

### 1.5 Database Migration Tests

**Purpose:** Ensure migrations are reversible and consistent.

**Implementation Steps:**

1. Create `apps/api/core/tests/test_migrations.py`:

   ```python
   from django.test import TestCase
   from django.core.management import call_command
   
   class MigrationTests(TestCase):
       def test_all_migrations_run_successfully(self):
           call_command('migrate', 'core', verbosity=0)
   ```

2. Add migration validation in CI:

   ```yaml
   - name: Validate migrations
     run: docker compose run --rm api python manage.py migrate --check
   ```

---

## 2. Frontend Testing (React)

### 2.1 Unit Tests

**Purpose:** Test React components, hooks, and utility functions.

**Tools:** `vitest`, `@testing-library/react`, `@testing-library/jest-dom`

**Implementation Steps:**

1. Install testing dependencies:

   ```bash
   npm install -D vitest @testing-library/react @testing-library/jest-dom @vitest/coverage-v8
   ```

2. Create `apps/web/vitest.config.ts`:

   ```typescript
   import { defineConfig } from 'vitest'
   export default defineConfig({
     test: {
       environment: 'jsdom',
       setupFiles: ['./src/test/setup.ts'],
       coverage: {
         provider: 'v8',
         reporter: ['text', 'html', 'lcov'],
         thresholds: {
           branches: 80,
           functions: 80,
           lines: 80,
           statements: 80
         }
       }
     }
   })
   ```

3. Create `apps/web/src/test/setup.ts`:

   ```typescript
   import '@testing-library/jest-dom'
   // Mock matchMedia for responsive components
   window.matchMedia = window.matchMedia || (() => ({ matches: false, addListener: () => {}, removeListener: () => {} }))
   ```

4. Create test files:

   ```
   apps/web/src/test/
   ├── setup.ts
   ├── components/
   │   ├── SearchPage.test.tsx
   │   ├── ListingCard.test.tsx
   │   └── BookingForm.test.tsx
   ├── pages/
   │   ├── Home.test.tsx
   │   ├── Dashboard.test.tsx
   │   └── Profile.test.tsx
   └── utils/
       └── formatting.test.ts
   ```

5. Add npm scripts to `apps/web/package.json`:

   ```json
   {
     "scripts": {
       "test": "vitest",
       "test:coverage": "vitest run --coverage",
       "test:ci": "vitest run"
     }
   }
   ```

### 2.2 End-to-End (E2E) Tests

**Purpose:** Test complete user flows in real browsers.

**Tools:** `playwright` (free, Microsoft)

**Implementation Steps:**

1. Install Playwright:

   ```bash
   npm install -D @playwright/test
   npx playwright install-deps
   ```

2. Create `apps/web/playwright.config.ts`:

   ```typescript
   import { defineConfig } from '@playwright/test'
   
   export default defineConfig({
     testDir: './e2e',
     timeout: 30000,
     retries: 2,
     use: {
       baseURL: 'http://localhost:5173',
       trace: 'retain-on-failure',
       screenshot: 'only-on-failure'
     },
     webServer: {
       command: 'npm run dev:web',
       url: 'http://localhost:5173',
       reuseExistingServer: !process.env.CI
     }
   })
   ```

3. Create `apps/web/e2e/` test scenarios:
   - `tenant-registration-flow.spec.ts` - Registration → OTP → dashboard
   - `landlord-listing-creation.spec.ts` - Verification → create listing
   - `booking-and-payment-flow.spec.ts` - Search → book → payment
   - `rental-progress-tracking.spec.ts` - Progress step updates

4. Implement test data management:

   ```typescript
   // e2e/fixtures/demo-users.ts
   export const DEMO_USERS = {
     tenant: { email: 'tenant@demo.com', password: 'demo123' },
     landlord: { email: 'landlord@demo.com', password: 'demo123' }
   }
   ```

### 2.3 Component Tests

**Purpose:** Verify component rendering, state changes, and user interactions.

**Implementation Steps:**

1. Test form validation components:

   ```tsx
   // src/components/__tests__/SearchForm.test.tsx
   test('validates required fields on search form', async () => {
     render(<SearchForm />)
     // Test validation behavior
   })
   ```

2. Test listing components with mock data:

   ```tsx
   test('renders listing card with all amenities', () => {
     const listing = mockListing({ amenities: ['gym', 'parking'] })
     render(<ListingCard listing={listing} />)
     expect(screen.getByText('gym')).toBeInTheDocument()
   })
   ```

### 2.4 Accessibility Tests

**Purpose:** Ensure WCAG 2.1 AA compliance.

**Tools:** `axe-core`, `@axe-core/react`

**Implementation Steps:**

1. Install axe-core:

   ```bash
   npm install -D @axe-core/playwright
   ```

2. Add accessibility tests in Playwright:

   ```typescript
   test('homepage is accessible', async ({ page }) => {
     await page.goto('/')
     const accessibilityScanResults = await new AxeBuilder({ page }).analyze()
     expect(accessibilityScanResults.violations).toEqual([])
   })
   ```

### 2.5 Performance Audits

**Purpose:** Monitor frontend performance metrics.

**Tools:** `lighthouse` CLI

**Implementation Steps:**

1. Install Lighthouse:

   ```bash
   npm install -D lighthouse
   ```

2. Add performance test in `package.json`:

   ```json
   {
     "scripts": {
       "lh:ci": "lhci autorun",
       "lh:collect": "lhci collect --url=http://localhost:5173"
     }
   }
   ```

3. Configure `.lighthouserc.json`:

   ```json
   {
     "ci": {
       "collect": { "numberOfRuns": 3 },
       "assert": {
         "assertions": {
           "first-contentful-paint": ["error", {"maxNumericValue": 1500}],
           "interactive": ["error", {"maxNumericValue": 3000}]
         }
       }
     }
   }
   ```

---

## 3. Integration/API Testing

### 3.1 Contract Testing

**Purpose:** Validate API conforms to expected contract schema.

**Tools:** `schemathesis` (free OSS)

**Implementation Steps:**

1. Install schemathesis:

   ```bash
   pip install schemathesis
   ```

2. Generate OpenAPI schema endpoint in Django:

   ```python
   # apps/api/config/urls.py
   from drf_spectacular.views import SpectacularAPIView
   
   urlpatterns = [
       path('api/schema/', SpectacularAPIView.as_view()),
   ]
   ```

3. Create `tests/contract/test_api_contract.py`:

   ```python
   import schemathesis
   from hypothesis import settings
   
   schema = schemathesis.from_uri("http://localhost:8000/api/schema/")
   
   @schema.hooks.validate()
   @settings(max_examples=100)
   def test_all_endpoints(status_code, case):
       response = case.call()
       assert status_code in (200, 201, 400, 403, 404)
   ```

### 3.2 Authentication Integration Tests

**Purpose:** Test JWT cookie handling, refresh flow, session invalidation.

**Implementation Steps:**

1. Test token expiration and refresh
2. Test cookie attributes (HttpOnly, Secure, SameSite)
3. Test concurrent sessions
4. Test logout clears cookies properly

### 3.3 Payment Integration Tests

**Purpose:** Test payment flow with mocked provider.

**Implementation Steps:**

1. Mock Flutterwave webhook endpoint
2. Test successful payment webhook handling
3. Test failed payment webhook
4. Test duplicate webhook idempotency
5. Test webhook signature verification bypass in dev vs enforced in prod

---

## 5. Performance & Stress Testing

### 5.1 Load Testing

**Purpose:** Simulate concurrent users and measure response times.

**Tools:** `k6` (free OSS)

**Implementation Steps:**

1. Install k6:

   ```bash
   brew install k6
   ```

2. Create `tests/performance/api-load-test.js`:

   ```javascript
   import http from 'k6/http'
   import { check, sleep } from 'k6'
   
   export const options = {
     stages: [
       { duration: '5m', target: 100 },  // Ramp to 100 users
       { duration: '10m', target: 100 }, // Stay at 100
       { duration: '5m', target: 0 },      // Ramp down
     ],
     thresholds: {
       http_req_duration: ['p(95)<500'],
       http_req_failed: ['rate<0.01']
     }
   }
   
   export default function() {
     const res = http.get('http://api.rentdirect.homes/api/v1/listings/search?city=Lagos')
     check(res, { 'status is 200': (r) => r.status === 200 })
     sleep(1)
   }
   ```

3. Create specific test scenarios:
   - `listing-search-load.js` - Search API under load
   - `user-login-load.js` - Auth endpoint stress
   - `booking-flow-load.js` - Booking creation flow

### 5.2 Stress Testing

**Purpose:** Find breaking point and resource exhaustion.

**Tools:** `locust` (free OSS)

**Implementation Steps:**

1. Install locust:

   ```bash
   pip install locust
   ```

2. Create `tests/performance/locustfile.py`:

   ```python
   from locust import HttpUser, task, between
   
   class RentalUser(HttpUser):
       wait_time = between(1, 3)
       
       @task(3)
       def search_listings(self):
           self.client.get("/api/v1/listings/search?city=Lagos")
       
       @task(1)
       def view_listing(self):
           self.client.get("/api/v1/listings/1")
   ```

3. Run stress tests:

   ```bash
   locust -f tests/performance/locustfile.py --headless -u 500 -r 50
   ```

### 5.3 Spike Testing

**Purpose:** Test system behavior under sudden traffic spikes.

**Tools:** `k6` or `vegeta` (free)

**Implementation Steps:**

1. Create spike test scenario:

   ```javascript
   export const options = {
     stages: [
       { duration: '1m', target: 10 },
       { duration: '10s', target: 500 },  // Spike to 500 in 10s
       { duration: '1m', target: 500 },
       { duration: '10s', target: 10 },
     ]
   }
   ```

### 5.4 Soak Testing

**Purpose:** Detect memory leaks and resource exhaustion over time.

**Tools:** `k6` with long duration

**Implementation Steps:**

1. Create 24-hour soak test:

   ```javascript
   export const options = {
     stages: [
       { duration: '1h', target: 50 },
       { duration: '22h', target: 50 },  // Run for 22 hours
       { duration: '1h', target: 0 }
     ]
   }
   ```

2. Monitor container metrics during test:
   - Memory usage growth
   - Database connection count
   - Cache hit/miss ratio

### 5.5 Database Performance Testing

**Purpose:** Validate database performance under load.

**Tools:** `pgbench` (PostgreSQL built-in)

**Implementation Steps:**

1. Initialize pgbench:

   ```bash
   pgbench -i -s 10 rentdirect
   ```

2. Run benchmark:

   ```bash
   pgbench -c 10 -j 2 -t 1000 -T 60 rentdirect
   ```

3. Test specific queries:
   - Listing search with filters
   - Booking date range queries
   - Tenant screening summary queries

---

## 6. Chaos Engineering

### 6.1 Service Failure Testing

**Purpose:** Validate system resilience to component failures.

**Tools:** `chaos-mesh` (free OSS), `chaos-daemon`

**Implementation Steps:**

1. Deploy chaos-mesh in dev/staging Kubernetes
2. Create chaos experiments:

   ```yaml
   apiVersion: chaos-mesh.org/v1alpha1
   kind: PodChaos
   metadata:
     name: api-pod-failure
   spec:
     action: pod-failure
     mode: one
     selector:
       labelSelectors:
         app: api
     duration: "30s"
   ```

3. Run tests:
   - Kill 1 API container (should auto-recover)
   - Kill database connection (should fail gracefully)
   - Simulate network partition

### 6.2 Network Chaos Testing

**Purpose:** Test behavior under network latency/packet loss.

**Tools:** `toxiproxy` (free OSS)

**Implementation Steps:**

1. Add toxiproxy in docker-compose for testing:

   ```yaml
   toxiproxy:
     image: shopify/toxiproxy
     ports:
       - "8474:8474"
       - "5433:5432"
   ```

2. Test scenarios:
   - 500ms latency to database
   - 10% packet loss to Redis
   - Connection reset during payment flow

### 6.3 Load + Chaos Combination

**Purpose:** Combine traffic load with failure injection.

**Implementation Steps:**

1. Run k6 load test while injecting pod failures
2. Monitor:
   - Error rates during failures
   - Recovery time
   - Request queue buildup

---

## 7. Security Testing

### 7.1 Dynamic Application Security Testing (DAST)

**Purpose:** Scan running application for vulnerabilities.

**Tools:** `OWASP ZAP` (free)

**Implementation Steps:**

1. Install ZAP:

   ```bash
   brew install zaproxy
   ```

2. Automated scan in CI:

   ```yaml
   - name: OWASP ZAP scan
     run: |
       zap-baseline.py -t http://localhost:8000/api/v1 -r zap-report.html
   ```

3. Authenticated scans with JWT tokens

### 7.2 Penetration Testing

**Purpose:** Automated vuln scanning with security templates.

**Tools:** `nuclei` (free)

**Implementation Steps:**

1. Install nuclei:

   ```bash
   brew install nuclei
   ```

2. Run scans:

   ```bash
   nuclei -u https://api.rentdirect.homes -t cves,tech-detect,exposures
   ```

3. Target specific endpoints:
   - `/api/v1/auth/*` - Auth brute force templates
   - `/admin/*` - Admin panel exposure
   - `/api/v1/payments/*` - Payment endpoint testing

### 7.3 Secret Scanning

**Purpose:** Detect hardcoded credentials and secrets.

**Tools:** `gitleaks` (free OSS)

**Implementation Steps:**

1. Install gitleaks:

   ```bash
   brew install gitleaks
   ```

2. Add pre-commit hook:

   ```yaml
   # .pre-commit-config.yaml
   - repo: https://github.com/gitleaks/gitleaks
     rev: v8.18.2
     hooks:
       - id: gitleaks
   ```

3. Run in CI:

   ```bash
   gitleaks detect --source . --redact
   ```

### 7.4 Container Image Scanning

**Tools:** `trivy`, `grype` (free)

**Implementation Steps:**

1. Scan base images and application:

   ```bash
   trivy image --severity HIGH,CRITICAL python:3.11-slim
   trivy image apps/api:latest
   ```

### 7.5 Dependency Vulnerability Scanning

**Purpose:** Find vulnerable dependencies.

**Tools:** `safety`, `pip-audit` (Python), `npm audit` (Node)

**Implementation Steps:**

1. Python dependencies:

   ```bash
   pip install pip-audit
   pip-audit -r apps/api/requirements.txt
   ```

2. Node dependencies (add to CI):

   ```bash
   npm audit --workspaces
   ```

### 7.6 API Security Testing

**Purpose:** Validate REST API security controls.

**Tools:** `nuclei-templates`, custom OWASP tests

**Implementation Steps:**

1. Test endpoints:
   - SQL injection on search params
   - XSS on form inputs
   - CSRF on state-changing endpoints
   - Rate limiting on auth endpoints
   - JWT token tampering

2. Test bypass scenarios:
   - Access landlord listings as tenant
   - Modify another user's booking
   - Refund already processed payments

---

## 8. Code Quality & Analysis

### 8.1 Static Analysis

**Purpose:** Catch bugs and code smells early.

**Tools:** `bandit` (Python), `eslint` (JS), `mypy` (Python)

**Implementation Steps:**

1. Bandit for security issues:

   ```bash
   pip install bandit
   bandit -r apps/api/core/ -ll
   ```

2. Mypy for type checking:

   ```bash
   pip install mypy
   mypy apps/api --ignore-missing-imports
   ```

3. ESLint (already configured):

   ```bash
   npm run lint:web
   ```

### 8.2 Test Coverage

**Purpose:** Ensure adequate test coverage.

**Tools:** `coverage.py`, `vitest/coverage`

**Implementation Steps:**

1. Python coverage target: 80% minimum
2. TypeScript coverage target: 80% minimum
3. Integrate with CI:

   ```yaml
   - name: Coverage report
     run: |
       coverage report --fail-under=80
       npm run test:coverage -- --run
   ```

### 8.3 Mutation Testing

**Purpose:** Validate test quality by introducing mutations.

**Tools:** `mutpy` (Python)

**Implementation Steps:**

1. Install mutpy:

   ```bash
   pip install mutpy
   ```

2. Run on critical modules:

   ```bash
   mut.py --target core.pricing --unit-test core.tests.test_pricing -m
   ```

---

## 9. Monitoring & Observability

### 9.1 Health Check Testing

**Purpose:** Validate health endpoints under various failure conditions.

**Implementation Steps:**

```python
def test_health_returns_healthy_when_db_connected(self):
    response = self.client.get("/api/health/ready")
    assert response.json()["status"] == "healthy"

def test_health_returns_503_when_redis_down(self):
    # Simulate Redis failure
    with patch("core.middleware.cache_healthcheck", return_value=(False, None)):
        response = self.client.get("/api/health/ready")
        assert response.status_code == 503
```

### 9.2 Log Format Validation

**Purpose:** Ensure structured logging for monitoring.

**Implementation Steps:**

1. Test log output format in tests
2. Validate JSON structure for log aggregation
3. Test log levels (DEBUG, INFO, WARNING, ERROR)

### 9.3 Metrics Testing

**Purpose:** Validate custom metrics are emitted.

**Implementation Steps:**

1. Use `testcontainers` to run Prometheus
2. Scrape metrics endpoint during tests
3. Validate metric values for business-critical operations

---

## 10. Implementation Roadmap

### Phase 1: Immediate (Week 1-2)

| Week | Task | Tool |
|------|------|------|
| 1 | Add vitest for frontend unit tests | vitest |
| 1 | Expand Python unit tests to 80% coverage | pytest-cov |
| 1 | Add k6 load test scripts | k6 |
| 2 | Implement OWASP ZAP in CI | OWASP ZAP |
| 2 | Add gitleaks pre-commit hook | gitleaks |
| 2 | Create Playwright E2E tests for critical flows | playwright |

### Phase 2: Pre-Launch (Week 3-4)

| Week | Task | Tool |
|------|------|------|
| 3 | Schemathesis contract testing | schemathesis |
| 3 | Container image scanning with trivy | trivy |
| 3 | Terraform security scanning | checkov |
| 4 | Full E2E test suite | playwright |
| 4 | Database performance testing | pgbench |
| 4 | Integration tests with mocked payment provider | pytest-mock |

### Phase 3: Production (Week 5-6)

| Week | Task | Tool |
|------|------|------|
| 5 | Chaos engineering experiments | chaos-mesh |
| 5 | Soak testing for 24h duration | k6 |
| 5 | Accessibility compliance tests | axe-core |
| 6 | Mutation testing | mutpy |
| 6 | Security penetration testing | nuclei |
| 6 | Performance regression in CI | k6 |

---

## Summary of Recommended Free Tools

| Category | Tool | Primary Use |
|----------|------|-------------|
| Python unit testing | pytest-django | Backend unit/integration tests |
| Frontend unit testing | vitest | React component tests |
| E2E testing | playwright | Browser automation |
| Load testing | k6 | Performance testing |
| Stress testing | locust | Distributed load testing |
| IaC scanning | checkov | Terraform security |
| Container scanning | trivy | Image vulnerability scan |
| Secret scanning | gitleaks | Credential detection |
| DAST | OWASP ZAP | Dynamic security scan |
| Contract testing | schemathesis | API spec validation |
| Policy testing | conftest | Infrastructure policy |
| Type checking | mypy | Static type analysis |
| Security analysis | bandit | Python security linting |
| Penetration testing | nuclei | Automated vuln scanning |
