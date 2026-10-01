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
| Super Admin | Configured through `SEED_SUPER_ADMIN_EMAIL` | Configured privately through `SEED_SUPER_ADMIN_PASSWORD` |

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

Coupons are either personal or public. A personal coupon is assigned to one customer and has one redemption. A public coupon is displayed at checkout, but each customer can redeem it only once; a campaign-wide redemption limit also applies. Vehicle search always uses regular fares so coupon validation cannot hide the fleet. After the customer selects a vehicle, checkout applies or removes the coupon by recalculating that selected vehicle's quote before the booking and payment order are created.

Every quote stores its route distance, trip days, complete vehicle tariff, line items, and total. The booking copies this snapshot, so later tariff edits never alter an existing customer's agreed price. Vehicles with active or upcoming bookings cannot be deleted; deletion archives an otherwise unused vehicle for audit history.

## Advance & UPI Payments

**Admin → Settings** stores the UPI ID and separate Local & Hourly, Airport, and Outstation advance policies. Each policy may be a percentage of the discounted fare or a fixed INR amount. Checkout displays the complete fare, the amount payable now, and the remaining amount collected by the driver after the trip.

The payment endpoint creates a unique UPI transaction reference and QR for one booking/payment record. Repeated checkout clicks reuse the existing pending booking and payment instead of creating conflicting vehicle holds. Development exposes **I have paid (test)** to update MongoDB. A deployed test environment may temporarily expose the same action with `ALLOW_TEST_PAYMENTS=true`; this allows an authenticated customer to mark their own payment as paid and must never remain enabled after the Razorpay cutover. A paid QR is invalidated, and booking details/receipts distinguish quoted total, amount paid, and remaining balance.

Driver assignment is available only after a booking reaches `PAID` or `ADVANCE_PAID`. The admin booking table disables assignment for pending payments and lists only active, verified drivers.

### Temporary deployed payment testing

Keep the normal production safeguards enabled and add this Render environment variable only while testing the end-to-end booking workflow:

```text
APP_ENV=production
DEMO_MODE=false
SEED_DEMO_DATA=false
ALLOW_TEST_PAYMENTS=true
```

The customer can then select **I have paid (test)**. After confirmation, the admin can assign an approved driver. Existing unpaid payment orders use the current value of `ALLOW_TEST_PAYMENTS`, so they do not need to be recreated after changing the setting.

### Demo advance and final balance

The demo flow supports full and advance payments without Razorpay. If a ride total is ₹100 and the configured advance is 25%, payment confirmation records ₹25 as `paid_amount`, leaves ₹75 as `balance_due`, and displays the same split to admin and driver.

At trip end, the driver records the exact backend-calculated outstanding balance as `CASH` or `UPI`. The booking stores `driver_collected_amount`, `balance_payment_method`, and `balance_collected_at`; the original online `paid_amount` remains unchanged for reconciliation. Trip completion is blocked while any balance remains.

After settlement, the driver location is checked:

- Within 200 metres of the destination, the trip completes immediately.
- Outside 200 metres, the existing customer completion OTP is generated and must be verified.

This is an internal demo settlement record. It does not call Razorpay or independently verify a UPI transfer.

### Razorpay production cutover

Before accepting real payments:

1. Complete the production checkout UI so it creates a real Razorpay order and sends `razorpay_payment_id` and `razorpay_signature` to `/api/v1/payments/{payment_id}/verify`. Adding credentials alone does not complete this checkout flow.
2. Set `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`, and `RAZORPAY_WEBHOOK_SECRET` in Render.
3. Set only the public `VITE_RAZORPAY_KEY_ID` in Vercel. Never expose either Razorpay secret through a `VITE_` variable.
4. Configure the Razorpay webhook URL shown in the Render section below and enable the required payment events.
5. Set `ALLOW_TEST_PAYMENTS=false` in Render and redeploy the backend.
6. Confirm that **I have paid (test)** is absent, a successful Razorpay payment changes the booking to `PAID` or `ADVANCE_PAID`, and a failed or unsigned request cannot confirm payment.

With `APP_ENV=production` and `ALLOW_TEST_PAYMENTS=false`, the test confirmation endpoint returns `404` and the frontend does not render the demo button.

## Live Ride Lifecycle

The backend is the source of truth for the active ride state:

```text
DRIVER_ASSIGNED
→ DRIVER_ACCEPTED
→ DRIVER_ON_THE_WAY
→ DRIVER_ARRIVED
→ TRIP_STARTED
→ DESTINATION_REACHED or COMPLETION_OTP_PENDING
→ TRIP_COMPLETED
```

The assigned driver publishes browser GPS coordinates every five seconds during an active assignment. Coordinates are held in the backend's TTL-based in-memory live-location service and are not inserted into MongoDB on every update. The customer live-trip page polls the current trip view every five seconds, moves the driver marker without reloading the page, and reports how recently the location was updated.

Each active location uses the booking ID as its single in-memory key. Updating GPS replaces that value rather than creating history records. Customer trip views and admin booking data read the same key; admin receives a Google Maps link for the current coordinate.

This in-memory transport is appropriate for the current single-process Render service. If the backend is scaled to multiple workers or multiple instances, replace the in-memory live-location service with Redis pub/sub or another shared realtime layer before scaling. Pickup, destination, ride states, lifecycle timestamps, OTP state, and audit events remain persisted in MongoDB.

### Trip OTPs

Trip OTPs reuse the existing encrypted `trip_otps` collection. Each record is tied to a booking and purpose, stores a salted hash plus encrypted customer-readable code, expires after 15 minutes, limits verification attempts, and records `ACTIVE`, `VERIFIED`, `EXPIRED`, or `CANCELLED` status with lifecycle timestamps.

- `START` is created when the driver arrives at pickup.
- `DRIVER_END` is created when the driver confirms destination arrival or requests customer-authorized completion.
- Customers see active OTPs inline in the dashboard and Live Ride page; there is no floating OTP banner or customer OTP modal.
- Refreshing or signing in again reloads the active booking and OTP from MongoDB.
- Expired or locked OTPs regenerate through the existing customer OTP endpoint when the ride is still in the matching state.
- Drivers only receive an OTP input. The backend validates assignment, ride state, purpose, expiry, attempt count, and code before changing state.

### Driver Navigation

Before trip start, the driver map shows the current driver position and pickup target. After the start OTP is verified, it switches to the destination target. **Open in Google Maps** launches external driving navigation for the active target. Pickup and destination arrival use swipe confirmation controls; completion always requires the customer completion OTP.

### Customer Map Selection

Pickup and destination may be selected by address search or through the fixed-center map picker. In map mode, the customer moves the map underneath a fixed pin, sees a reverse-geocoded address after a 700 ms debounce, and confirms the point before it is copied into the quote and booking payload. The current-location button uses browser geolocation with explicit permission.

## Automatic Driver Assignment

Admin assigns one default driver to each vehicle from **Admin → Vehicles**. The customer selects only the vehicle and trip details; no customer-facing driver selection exists.

Driver assignment occurs after payment is verified, before driver acceptance:

```text
Payment verified
→ load vehicle default driver
→ validate account, approval, and availability
→ check active trips and schedule overlap
→ claim driver time slots
→ DRIVER_ASSIGNED
→ driver accepts the ride
```

A driver is eligible only when the user account is active, the driver profile is verified with `schedule_availability=AVAILABLE`, there is no active trip, and no assigned booking overlaps the requested window. Booking windows use the same 30-minute slots as vehicle reservations. Normal rides default to three hours, airport rides to four hours, outstation rides to twelve hours, and explicit package/return times extend the window.

`schedule_availability` is controlled by admin and determines whether future bookings may be assigned. `online_status` is controlled by the driver and represents only current app/GPS presence. Going offline does not remove the driver from future schedules. Driver endpoints re-read the current user account, so an inactive driver or a stale JWT role cannot continue using trip, document, location, or dashboard APIs.

The `driver_reservations` collection uses IDs in the form `driver_id:slot`. MongoDB's unique `_id` guarantee is the scheduling lock: if two payment confirmations attempt to claim the same driver and time, only one booking can win. The losing booking remains paid and `CONFIRMED` with `assignment_status=AWAITING_ADMIN` and a human-readable conflict reason.

Admin booking rows do not show a mandatory driver dropdown. Auto-assigned bookings show **Auto assigned** with an optional **Change driver** action. Conflict bookings show **Admin attention** and **Assign another driver**. Opening the control calls `/api/v1/admin/bookings/{booking_id}/available-drivers`; unavailable drivers are disabled with the reason. The assignment endpoint validates and claims the schedule again, releases the previous driver's slots, removes the booking from the old driver's query, and makes it appear on the new driver's dashboard.

Cancelling an eligible booking releases both vehicle and driver reservations. Driver changes are blocked once pickup navigation has started.

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

Create a Render Blueprint from [render.yaml](render.yaml). Set every `sync: false` secret in the Render dashboard, including both Admin and Super Admin seed credentials. Set `ALLOWED_ORIGINS` to the exact Vercel URL, for example `https://ridex.example.com`, without a trailing slash.

`ALLOW_TEST_PAYMENTS` defaults to `false` in the Blueprint. Change it to `true` only for temporary deployed workflow testing, then restore `false` during the Razorpay production cutover.

After deployment, configure the Razorpay webhook URL as:

```text
https://YOUR-RENDER-SERVICE.onrender.com/api/v1/webhooks/razorpay
```

## Vercel Frontend

Import the repository, set the Root Directory to `frontend`, and use the detected Vite settings. Configure:

```text
VITE_API_URL=https://YOUR-RENDER-SERVICE.onrender.com/api/v1
VITE_DEMO_MODE=false
VITE_GOOGLE_MAPS_API_KEY=...
VITE_GOOGLE_REVIEW_URL=...
VITE_RAZORPAY_KEY_ID=...
```

Add the final Vercel domain to `ALLOWED_ORIGINS` and `FRONTEND_URL` on Render. The frontend sends the signed JWT in the `Authorization: Bearer` header; CORS must allow only the deployed frontend domains.

## Current MVP Boundary

The booking, gated test payment, confirmation, admin dashboard, driver workflow, notifications, reviews, support, and PDF receipt paths are implemented. The backend includes Razorpay signature and webhook verification, but the production Razorpay order/checkout UI still requires implementation before public launch. Real Google autocomplete/map widgets, cloud upload signing, and background job infrastructure also require their provider credentials and production integration.

### Admin workspace

The admin sidebar contains complete API-backed pages for Dashboard, Customers, Drivers, Vehicles, Bookings, Payments, Pricing, Reviews, Coupons, Notifications and Support, Reports, Audit Logs, and Settings. Dashboard charts and reports are calculated by FastAPI from Atlas records. Customer status, driver onboarding/verification, vehicle creation/status, driver assignment, cancellation, pricing rules, coupons, review moderation, support status, and settings changes are persisted through protected API commands and recorded in audit logs.

Architecture and phase details are in [docs/MVP_ARCHITECTURE.md](docs/MVP_ARCHITECTURE.md).