# RideX

RideX is a responsive chauffeur-driven booking MVP with customer, admin, and driver experiences.

## Stack

- Frontend: React 19, TypeScript, Vite, React Router, Lucide icons
- Backend: FastAPI, Pydantic, PyMongo Async API
- Database: MongoDB Atlas
- Deployment: Vercel frontend and Render backend
- Integrations: Razorpay-ready payments, SMTP email, Google Maps configuration, private object-storage architecture

## Local Development

The backend defaults to an in-memory demo store so the project can run before an Atlas cluster is configured. Production refuses to start in demo mode.

```powershell
# Backend
Copy-Item backend/.env.example backend/.env
$env:PYTHONPATH='backend'
./.venv/Scripts/python.exe -m uvicorn app.main:app --reload --port 8000

# Frontend, in a second terminal
Copy-Item frontend/.env.example frontend/.env
npm --prefix frontend run dev
```

Open `http://127.0.0.1:5173` (or use `localhost` consistently for both services). API docs are at `http://127.0.0.1:8000/docs`. In development the frontend automatically uses the same hostname for port `8000`, which keeps authentication cookies same-site.

### Demo accounts

| Role | Email | Password |
|---|---|---|
| Customer | `ridex.customer@mailinator.com` | `Customer@123` |
| Driver | `ridex.driver@mailinator.com` | `Driver@123` |
| Admin | Configured through `SEED_ADMIN_EMAIL` | Configured privately through `SEED_ADMIN_PASSWORD` |

Demo accounts exist only when `DEMO_MODE=true` or `SEED_DEMO_DATA=true`.

Passwords are never encrypted reversibly or stored as plaintext. Each password receives a cryptographically random salt and a one-way `scrypt` hash; both `password_salt` and `password_hash` are stored in Atlas. Password-reset OTPs are also salted and hashed, expire after 10 minutes, and are never returned by the API.

Authentication uses one short-lived bearer JWT stored under the single browser key `ridex_jwt`. Signed claims contain the user ID, role, name, email, phone, issued time, and expiry. No profile, booking draft, CSRF value, or password is stored separately in browser storage. Because browser local storage is readable by JavaScript, production must retain a strict Content Security Policy and XSS controls.

For Gmail SMTP, set `SMTP_HOST=smtp.gmail.com`, `SMTP_PORT=587`, `SMTP_USERNAME` and `SMTP_FROM_EMAIL` to the same authenticated Gmail address, and enter the Google app password directly as `SMTP_PASSWORD`. Do not send or commit the app password.

Every lifecycle email is written to the MongoDB `email_outbox` before delivery. **Admin → Notifications** shows the original recipient, development redirect, SMTP status, attempts, and immediate errors. `SMTP_ACCEPTED` means Gmail accepted the message; it cannot guarantee that a recipient server will not generate a later bounce.

Mailinator may reject Gmail outbound IPs with `500 Email is flagged for abuse`. In development, `EMAIL_REDIRECT_DISPOSABLE_DOMAINS=true` redirects Mailinator recipients to `EMAIL_TEST_REDIRECT_TO`, or to `SMTP_USERNAME` when no explicit target is set. Redirected subjects identify the original recipient. Production never performs this automatic redirect. Use verified customer domains and a transactional provider with SPF, DKIM, DMARC, bounce webhooks, and a dedicated sending domain for production delivery.

## Vehicle Pricing

Local and outstation tariffs belong to each uniquely numbered vehicle and are edited from **Admin → Vehicles**. Approved drivers are also assigned or unassigned on the vehicle card. Local pickup/drop quotes use the OSRM road distance and calculate a fixed base fare, included kilometres, and a per-kilometre charge beyond the allowance.

Outstation one-way quotes use a fixed package with included kilometres, an excess-kilometre rate, and separate driver bata. Round trips use a separate daily package with included kilometres per day, an excess-kilometre rate, and driver bata per day. Both modes have independently editable AC and non-AC rates. Airport and hourly defaults remain backend-managed; the redundant Pricing and Media navigation pages are removed.

For local rides, the assigned driver may start waiting only after reaching the pickup radius. Each vehicle defines a free waiting period and a per-minute rate. The backend calculates this automatically when the trip start OTP starts the trip. Drivers can manually add only toll and parking charges and see the amount paid online, additional charges, final total, and customer collection balance.

When a driver reaches the pickup radius, the customer's booking-detail page and Live Ride page display the trip start OTP. The booking page refreshes every five seconds, names the assigned driver, shows the OTP expiry, and removes the banner after trip start. If the OTP expires while the driver is still waiting, the next customer refresh creates a replacement securely.

Coupons are either personal or public. A personal coupon is assigned to one customer and has one redemption. A public coupon is displayed in the booking form for everyone, but each customer can redeem it only once; a campaign-wide redemption limit also applies.

Every quote stores its route distance, trip days, complete vehicle tariff, line items, and total. The booking copies this snapshot, so later tariff edits never alter an existing customer's agreed price. Vehicles with active or upcoming bookings cannot be deleted; deletion archives an otherwise unused vehicle for audit history.

## Advance & UPI Payments

**Admin → Settings** stores the UPI ID and separate Airport/Outstation advance policies. Each policy may be a percentage or a fixed INR amount. Local and hourly bookings require the full quoted fare; airport and outstation bookings collect only the configured advance before confirmation.

The payment endpoint creates a unique UPI transaction reference and QR for one booking/payment record. Repeated checkout clicks reuse the existing pending booking and payment instead of creating conflicting vehicle holds. Development exposes **I have paid (test)** to update MongoDB; production hides it and requires provider verification. A paid QR is invalidated, and booking details/receipts distinguish quoted total, amount paid, and remaining balance.

## Database Console

**Admin → Database** lists every Atlas collection and displays up to 100 records at a time with passwords, OTP material, email bodies, and binary blobs removed or redacted. Direct deletion is deliberately restricted to disposable records such as notifications, completed email-delivery logs, resolved support requests, consumed/expired reset OTPs, expired quotes, and expired vehicle holds. Identity, booking, vehicle, driver, payment, audit, and billing collections are protected from direct deletion.

## Validation

```powershell
$env:PYTHONPATH='backend'
./.venv/Scripts/python.exe -m pytest backend/tests -q
npm --prefix frontend run lint
npm --prefix frontend run build
```

## MongoDB Atlas

1. Create an Atlas project and database user with access only to the RideX database.
2. Allow Render's outbound access according to your Atlas network policy. Avoid unrestricted access when a fixed-egress option is available.
3. Set `MONGODB_URI` and `MONGODB_DATABASE` in Render.
4. Set `DEMO_MODE=false`. Keep `SEED_DEMO_DATA=false` in production.
5. On startup, the API creates the required unique and lookup indexes.

## Render Backend

Create a Render Blueprint from [render.yaml](render.yaml). Set every `sync: false` secret in the Render dashboard. Set `ALLOWED_ORIGINS` to the exact Vercel URL, for example `https://ridex.example.com`, without a trailing slash.

After deployment, configure the Razorpay webhook URL as:

```text
https://YOUR-RENDER-SERVICE.onrender.com/api/v1/webhooks/razorpay
```

## Vercel Frontend

Import the repository, set the Root Directory to `frontend`, and use the detected Vite settings. Configure:

```text
VITE_API_URL=https://YOUR-RENDER-SERVICE.onrender.com/api/v1
VITE_GOOGLE_MAPS_API_KEY=...
VITE_GOOGLE_REVIEW_URL=...
VITE_RAZORPAY_KEY_ID=...
```

Add the final Vercel domain to `ALLOWED_ORIGINS` and `FRONTEND_URL` on Render. The frontend sends the signed JWT in the `Authorization: Bearer` header; CORS must allow only the deployed frontend domains.

## Current MVP Boundary

The booking, demo payment, confirmation, admin dashboard, driver workflow, notifications, reviews, support, and PDF receipt paths are implemented. Production Razorpay checkout UI, real Google autocomplete/map widgets, cloud upload signing, and background job infrastructure require their provider credentials before public launch.

### Admin workspace

The admin sidebar contains complete API-backed pages for Dashboard, Customers, Drivers, Vehicles, Bookings, Payments, Pricing, Reviews, Coupons, Notifications and Support, Reports, Audit Logs, and Settings. Dashboard charts and reports are calculated by FastAPI from Atlas records. Customer status, driver onboarding/verification, vehicle creation/status, driver assignment, cancellation, pricing rules, coupons, review moderation, support status, and settings changes are persisted through protected API commands and recorded in audit logs.

Architecture and phase details are in [docs/MVP_ARCHITECTURE.md](docs/MVP_ARCHITECTURE.md).