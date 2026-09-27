# Chauffeur-Driven Car Rental MVP

## Product and Technical Architecture

| Attribute | Value |
|---|---|
| Status | Proposed for review before coding |
| Version | 2.0, simplified MVP |
| Date | 26 September 2026 |
| Initial market | Bengaluru, India |
| Roles | `CUSTOMER`, `ADMIN`, `DRIVER` only |
| Architecture | React + FastAPI modular monolith + MongoDB Atlas |

This document replaces the earlier multi-company marketplace design. The MVP is operated by one platform organization. There is no rental-company account, portal, tenant boundary, payout system, or company staff role.

---

## 0. Scope and Decisions

### 0.1 MVP goals

1. Let a customer search, price, pay for, and manage a chauffeur-driven booking.
2. Let an admin operate the complete fleet, driver, booking, pricing, and payment workflow.
3. Let a driver accept assigned trips and report trip progress from a mobile-first interface.
4. Prevent duplicate payment effects and overlapping vehicle/driver bookings.
5. Produce trustworthy confirmations, receipts, notifications, and audit history.

### 0.2 In scope

- Four dedicated booking services: Normal, Airport, Hourly, and Outstation.
- Customer, admin, and driver responsive experiences in one React application.
- Platform-managed vehicles, drivers, pricing, bookings, payments, reviews, coupons, notifications, and reports.
- Razorpay payment, Google Maps Platform, object-storage vehicle images, email, in-app notifications, and backend-generated PDF receipts.
- Secure authentication, role authorization, file validation, rate limiting, payment webhook verification, audit logs, error handling, and monitoring.

### 0.3 Explicitly deferred

- Rental-company portal, multi-tenancy, company payouts, commissions, and company-specific pricing.
- Native mobile apps, continuous background tracking, turn-by-turn navigation SDK, automated flight tracking, WhatsApp/SMS sending, wallets, loyalty, corporate billing, multiple currencies, and AI features.
- Microservices, Kubernetes, Kafka/event buses, search clusters, data warehouse, and multiple databases.

### 0.4 Assumptions requiring approval

| Topic | Recommended MVP decision |
|---|---|
| Fleet ownership | All vehicles and drivers are managed by the platform admin |
| Checkout | Browsing/search may be public; login or phone verification is required before booking creation |
| Vehicle selection | Customer selects a concrete available vehicle, not only a category |
| Driver assignment | Admin assigns a driver after confirmed payment; driver may accept/reject within an SLA |
| Pricing | Price is fixed from a 15-minute backend quote; actual toll/parking treatment must be stated before payment |
| Cancellation | Versioned policy based on service type and time before pickup; confirm exact fee bands before Phase 4 |
| Receipts | Platform is the receipt issuer; GST/tax invoice requirements need accountant approval before production |
| Driver earnings | Admin-configured, read-only for drivers; automatic payout is deferred |
| Tracking | MVP tracks status. Optional periodic driver location is limited to active trips and requires an approved privacy basis |
| Google | Internal reviews remain separate; Google button opens the legitimate platform business review destination |

---

## 1. Complete Application Structure

### 1.1 Runtime components

```mermaid
flowchart LR
    U[Customer / Admin / Driver] --> FE[React Vite application]
    FE --> API[FastAPI modular monolith]
    API --> PG[(MongoDB Atlas)]
    API --> R[(Redis)]
    API --> S[(Object storage)]
    API --> M[Google Maps]
    API --> P[Razorpay]
    R --> W[Background worker]
    W --> E[SMTP provider]
    W --> S
    W --> PG
```

### 1.2 Frontend route groups

- Public/customer: `/`, `/services`, `/book/*`, `/search`, `/vehicles/:id`, `/payment/:bookingId`, `/confirmation/:bookingId`, `/bookings`, `/bookings/:id`, `/trip/:id`, `/notifications`, `/profile`, `/review/:bookingId`, `/support`.
- Driver: `/driver`, `/driver/trips`, `/driver/trips/:id`, `/driver/active`, `/driver/history`, `/driver/earnings`, `/driver/profile`.
- Admin: `/admin`, `/admin/customers`, `/admin/drivers`, `/admin/vehicles`, `/admin/bookings`, `/admin/payments`, `/admin/pricing`, `/admin/reviews`, `/admin/coupons`, `/admin/notifications`, `/admin/reports`, `/admin/settings`.

### 1.3 Backend modules

`auth`, `users`, `drivers`, `vehicles`, `availability`, `pricing`, `bookings`, `trips`, `payments`, `documents`, `reviews`, `notifications`, `maps`, `reports`, `settings`, and `audit`.

Modules run in one FastAPI process and one deployable codebase. They communicate with direct typed service calls and Atlas transactions where multi-document atomicity is required. Redis is used for queues, short-lived rate limits, and cache only; MongoDB Atlas remains the source of truth.

---

## 2. Customer Flow

### 2.1 Pages

1. Home
2. Services
3. Book a Ride
4. Normal Pickup/Drop
5. Airport Booking
6. Hourly Rental
7. Outstation
8. Search Results
9. Vehicle Details
10. Passenger Details
11. Fare Summary
12. Payment
13. Booking Confirmation
14. My Bookings
15. Booking Details
16. Active Trip
17. Notifications
18. Profile
19. Review
20. Support

### 2.2 Home page

The first viewport contains the platform name, headline “Your Journey, Our Responsibility,” short supporting copy, and a four-option booking selector. The page then shows popular cars, service summaries, why choose us, verified customer reviews, Google rating/map location, and contact/support.

### 2.3 Seven-step booking journey

1. **Select Service:** Normal, Airport, Hourly, or Outstation.
2. **Trip Details:** collect only service-relevant locations, schedule, passengers, luggage, and optional flight data.
3. **Select Vehicle:** show only vehicles that satisfy capacity, operational status, service eligibility, maintenance, and reservation overlap checks.
4. **Customer Details:** sign in/register and confirm the travelling contact; do not repeat known profile data unnecessarily.
5. **Review Price:** show backend quote, cancellation summary, discount, taxes, and any payable-at-actual charges.
6. **Payment:** create a server-side Razorpay order for the quote total and confirm only after backend verification.
7. **Confirmation:** show booking ID, customer, service, route, schedule, vehicle, assigned driver if any, amount, payment state, and receipt/bookings actions.

Form state is preserved when moving backward. Any change to route, schedule, service, package, vehicle, or coupon invalidates the old quote and availability result.

### 2.4 Service-specific inputs

| Service | Inputs | Notes |
|---|---|---|
| Normal | pickup, destination, date/time, passengers, luggage | Point-to-point Bengaluru service |
| Airport to airport | Not supported | The UI never presents this option |
| To Airport | pickup, configured airport, date/time, passengers, luggage, optional flight number | Pickup must be inside enabled service area |
| From Airport | configured airport, flight number, arrival date/time, destination, passengers, luggage | Destination must be inside enabled area; waiting/grace policy displayed |
| Hourly | pickup, date, start time, package, passengers, luggage | No destination field; packages include duration/km and extra rates |
| Outstation One Way | origin, destination, date/time, passengers, luggage | Allowed destination/state rules apply |
| Outstation Round Trip | origin, destination, departure, return, pickup time, passengers, luggage | Return must follow departure; daily minimum and allowance are backend rules |

### 2.5 Vehicle presentation

Result cards show primary image, name, seats, bags, transmission, fuel, AC, rating, “From” or quoted price, View Details, and Select. Detail pages show a large responsive gallery, specifications, amenities, price context, platform information, availability, and Book Now.

### 2.6 Post-booking flow

- My Bookings supports upcoming, active, completed, and cancelled filters.
- Booking Details shows a status timeline, driver after assignment, payment, cancellation eligibility, and receipt.
- Active Trip shows status and optional map location when tracking is enabled.
- Cancellation first shows the policy result and refund estimate, then requires confirmation.
- Review is available once per completed booking. After internal submission, the Google review button opens an official review URL and never copies or posts the internal review.

---

## 3. Admin Flow

### 3.1 Navigation and dashboard

Navigation: Dashboard, Customers, Drivers, Vehicles, Bookings, Payments, Pricing, Reviews, Coupons, Notifications, Reports, Settings.

Dashboard cards: total bookings, today's bookings, active trips, customers, drivers, vehicles, revenue, pending payments, and cancellations. Operational sections show recent bookings/customers and active drivers. Every metric states its date range, timezone, and freshness.

### 3.2 Customer management

- Search and filter customers; view profile, booking history, reviews, and account status.
- Activate/deactivate through guarded commands with reason and audit log.
- Customer PII is masked in lists and revealed only where operationally necessary.

### 3.3 Driver management

- Add/edit/deactivate drivers, create their login, upload documents, view expiry/status, availability, assignments, history, ratings, and earnings.
- Assign or replace a driver on a confirmed booking after server checks driver availability and vehicle authorization.
- A driver account has role `DRIVER`; there is no public driver signup in the initial MVP.

### 3.4 Vehicle management

- Add/edit/deactivate vehicles; set category, capacity, transmission, fuel, AC, amenities, base eligibility, availability, and maintenance.
- Upload, reorder, caption, delete, and choose a primary image.
- UI statuses are `AVAILABLE`, `BOOKED`, `ON_TRIP`, `MAINTENANCE`, `INACTIVE`. `BOOKED` and `ON_TRIP` are derived from active reservations/trips; maintenance/inactive are admin-controlled.

### 3.5 Booking and payment management

- View/search bookings with customer, service, route, date/time, vehicle, driver, amount, payment state, and booking state.
- View, assign/change driver, cancel, request a guarded modification/requote, inspect payment, and open receipt.
- Admin cannot type an arbitrary booking/payment status. Commands pass through state-machine rules and are audited.
- Payments list gateway references, amount, method category, status, failures, refunds, and reconciliation state. Sensitive payment credentials are never stored.

### 3.6 Pricing, reviews, notifications, and reports

- Create draft pricing versions by service/vehicle category, preview examples, and publish future-effective versions.
- Configure hourly packages, airport rates, one-way/round-trip outstation rules, extra km/hour, driver allowance, tax, and discounts.
- View/filter reviews, rating statistics, customer, booking, and driver rating; hide/flag inappropriate content with reason.
- Inspect email/in-app delivery logs and safely retry eligible failed deliveries.
- Reports cover bookings, revenue, cancellations, service mix, vehicle utilization, driver activity, and payment reconciliation. CSV export is admin-only and audited.

---

## 4. Driver Flow

### 4.1 Navigation and dashboard

Navigation: Dashboard, My Trips, Active Trip, Trip History, Earnings, Profile.

Dashboard shows greeting, today's/upcoming/completed trip counts, today's earnings, current status, and Available/Offline control.

### 4.2 Trip workflow

Driver sees booking ID, customer name, pickup, destination when applicable, schedule, passengers, luggage, assigned vehicle, and special instructions. Private customer data not required for the ride is omitted.

```mermaid
stateDiagram-v2
    [*] --> ASSIGNED
    ASSIGNED --> ACCEPTED: Accept Trip
    ASSIGNED --> REJECTED: Reject with reason
    ACCEPTED --> ON_THE_WAY: Start Navigation
    ON_THE_WAY --> ARRIVED: Arrived
    ARRIVED --> TRIP_STARTED: Start Trip
    TRIP_STARTED --> TRIP_COMPLETED: Complete Trip
```

Each command includes the expected trip version and a unique client action ID. The backend rejects skipped, repeated, stale, or unauthorized transitions. Every accepted command creates an immutable trip event and relevant customer/admin notification.

### 4.3 Availability and earnings

- Drivers set Available or Offline. Active assignments prevent conflicting offline periods unless admin resolves the assignment.
- Earnings are read-only and derived from completed-trip earning records configured by admin.
- Driver profile includes contact, password/security, license/document status, and availability; sensitive identity documents are private.

---

## 5. Database Schema

MongoDB Atlas is the single database. Collections use `snake_case`, string UUID identifiers, UTC BSON datetimes, integer money in minor units plus `currency_code`, schema validation, references, and explicit indexes. Embedded objects are limited to bounded snapshots such as service details and fare line items; independently changing entities use separate collections.

### 5.1 Relationship diagram

```mermaid
erDiagram
    USERS ||--o| DRIVERS : has_profile
    USERS ||--o{ BOOKINGS : creates
    VEHICLES ||--o{ VEHICLE_IMAGES : has
    VEHICLES ||--o{ VEHICLE_RESERVATIONS : reserves
    VEHICLES ||--o{ BOOKINGS : selected_for
    VEHICLES ||--o{ QUOTES : quoted_for
    DRIVERS ||--o{ DRIVER_RESERVATIONS : reserves
    DRIVERS ||--o{ BOOKINGS : assigned_to
    DRIVERS ||--o{ DRIVER_DOCUMENTS : verifies
    DRIVERS ||--o{ DRIVER_EARNINGS : earns
    BOOKINGS ||--o{ BOOKING_VERSIONS : versions
    BOOKINGS ||--|| BOOKING_PRICING : snapshots
    BOOKINGS ||--o{ PAYMENTS : has
    BOOKINGS ||--o{ TRIP_EVENTS : records
    BOOKINGS ||--o{ DOCUMENTS : generates
    BOOKINGS ||--o| REVIEWS : verifies
    USERS ||--o{ NOTIFICATIONS : receives
    COUPONS ||--o{ COUPON_USAGE : used_by
    PRICING_RULES ||--o{ BOOKING_PRICING : prices
```

### 5.2 Core collections

- `users`: `id`, `role (CUSTOMER|ADMIN|DRIVER)`, `name`, `email_normalized`, `phone_e164`, `password_hash`, `status`, `email_verified_at`, `phone_verified_at`, `last_login_at`, `created_at`, `updated_at`.
- `drivers`: `id`, `user_id`, `license_number_encrypted`, `license_expiry`, `availability_status`, `rating_average`, `rating_count`, `earning_rule_json`, `created_at`, `updated_at`.
- `vehicles`: `id`, `name`, `category`, `registration_number_encrypted`, `registration_search_hash`, `seat_capacity`, `luggage_capacity`, `transmission`, `fuel_type`, `has_ac`, `amenities_json`, `operational_status`, `rating_average`, `rating_count`, `created_at`, `updated_at`.
- `vehicle_images`: `id`, `vehicle_id`, `storage_key`, `renditions_json`, `image_type`, `caption`, `display_order`, `is_primary`, `processing_status`, `created_at`.
- `bookings`: `id`, `public_id`, `customer_id`, `vehicle_id`, `driver_id`, `service_type`, `service_details_json`, `pickup_place_id`, `pickup_address`, `pickup_latitude`, `pickup_longitude`, `drop_place_id`, `drop_address`, `drop_latitude`, `drop_longitude`, `scheduled_start_at`, `scheduled_end_at`, `passenger_count`, `luggage_count`, `status`, `payment_status`, `current_version`, `cancellation_policy_snapshot`, `special_instructions`, `created_at`, `updated_at`.
- `booking_pricing`: `id`, `booking_id`, `pricing_rule_id`, `pricing_version`, `currency_code`, `base_fare_minor`, `distance_charge_minor`, `package_charge_minor`, `extra_charge_minor`, `driver_allowance_minor`, `tax_minor`, `discount_minor`, `total_minor`, `line_items_json`, `quote_expires_at`, `created_at`.
- `payments`: `id`, `booking_id`, `provider`, `provider_order_id`, `provider_payment_id`, `provider_refund_id`, `amount_minor`, `currency_code`, `method_type`, `status`, `idempotency_key_hash`, `verified_at`, `failure_code`, `created_at`, `updated_at`.
- `reviews`: `id`, `booking_id`, `customer_id`, `driver_id`, `vehicle_id`, `rating`, `driver_rating`, `comment`, `status (PENDING|PUBLISHED|HIDDEN|FLAGGED)`, `created_at`, `updated_at` with unique `booking_id`.
- `notifications`: `id`, `user_id`, `event_type`, `title`, `message`, `data_json`, `read_at`, `archived_at`, `created_at`.
- `documents`: `id`, `booking_id`, `document_type`, `document_number`, `storage_key`, `sha256`, `version`, `created_at`.
- `coupons`: `id`, `code_hash`, `display_code`, `discount_type`, `value`, `maximum_discount_minor`, `minimum_booking_minor`, `service_types_json`, `valid_from`, `valid_to`, `total_limit`, `per_customer_limit`, `status`.
- `pricing_rules`: `id`, `service_type`, `vehicle_category`, `rule_version`, `configuration_json`, `effective_from`, `effective_to`, `status (DRAFT|ACTIVE|RETIRED)`, `created_by`, `created_at`.
- `audit_logs`: `id`, `actor_user_id`, `action`, `entity_type`, `entity_id`, `request_id`, `ip_hash`, `before_redacted_json`, `after_redacted_json`, `reason`, `created_at`; append-only.

### 5.3 Small operational collections required for correctness

- `refresh_sessions`: rotating refresh-token hashes, token family, expiry, revocation, and device metadata.
- `quotes`: customer/session, vehicle, service request snapshot, route snapshot, pricing-rule version, line items/total, currency, and expiry. Booking creation atomically verifies this record and copies it to `booking_pricing`.
- `booking_versions`: booking, version number, change type, actor, reason, and immutable before/after snapshot. Admin modification appends a version; it never erases the original itinerary.
- `vehicle_reservations`: one document per vehicle and 30-minute UTC slot, with deterministic unique `_id = vehicle_id:slot`, `booking_id`, `status`, and BSON `expires_at`. Unique slot insertion rejects overlap; booking and slot writes use an Atlas transaction in production.
- `vehicle_availability_blocks`: vehicle, closed-open period, type (`MAINTENANCE|UNAVAILABLE`), reason, and status for scheduled admin blocks.
- `driver_reservations`: equivalent exclusion constraint for assigned drivers.
- `driver_documents`: driver, document type, private storage key, verification status, expiry, verifier, and timestamps.
- `driver_earnings`: driver, booking, rule snapshot, amount, currency, status, and created timestamp. Completed trip logic creates it; drivers cannot update it.
- `trip_events`: `booking_id`, `driver_id`, `event_type`, `client_action_id`, `expected_version`, `occurred_at`, `received_at`, optional location, and safe metadata. Unique `(booking_id, client_action_id)` deduplicates mobile retries.
- `payment_webhook_events`: unique provider event ID, signature result, event type, redacted payload, processing status, attempts, and timestamps.
- `notification_deliveries`: notification/event ID, channel, template, destination redacted, status, attempts, next retry, provider ID, safe error code, and timestamps.
- `coupon_usage`: coupon, customer, booking, amount, and reserved/used/released state for concurrency-safe limits.
- `idempotency_records`: actor, operation scope, key hash, request hash, cached response, and expiry.
- `support_requests`: customer, optional booking, category, message, status, admin assignee, and timestamps.
- `platform_settings`: typed, versioned values for public contact, business/map/review links, cancellation policy, and operational configuration.

### 5.4 Critical constraints

- Unique indexes: user email/phone where present, booking public ID, registration hash, Razorpay IDs, webhook event ID, `(booking_id, version)` for booking history, `(driver_id, booking_id)` earnings, receipt number/version, reservation `_id`, and one review per booking.
- Pydantic plus MongoDB JSON Schema validation enforce positive capacities, ratings 1-5, non-negative money, return after departure, and passenger/luggage capacity.
- Reservation buckets include service duration plus turnaround buffer. A TTL index removes expired unpaid holds; confirmed holds are extended through trip completion.
- Deactivating users/vehicles preserves historical bookings; financial, booking, trip, document, and audit documents are never hard-deleted.

---

## 6. API List

All APIs are under `/api/v1`, return JSON except signed document downloads, and publish OpenAPI through FastAPI. Errors use Problem Details with a stable `code`, field errors, and `request_id`. State-changing create/payment/transition endpoints require an `Idempotency-Key` where noted.

### 6.1 Public and authentication

| Method | Path | Access | Purpose |
|---|---|---|---|
| `POST` | `/auth/register` | Public/rate-limited | Register customer |
| `POST` | `/auth/login` | Public/rate-limited | Login any role and create secure session |
| `POST` | `/auth/logout` | Authenticated client | Clear the locally stored bearer JWT |
| `POST` | `/auth/forgot-password` | Public/rate-limited | Start reset without account enumeration |
| `POST` | `/auth/reset-password` | Reset token | Set new password and revoke old sessions |
| `GET` | `/services` | Public | Active services and packages |
| `GET` | `/vehicles/popular` | Public | Home-page vehicles |
| `GET` | `/vehicles/{id}` | Public | Published vehicle details/gallery |
| `GET` | `/reviews` | Public | Published customer reviews |
| `GET` | `/locations/autocomplete` | Public/rate-limited | Google Places suggestions |
| `POST` | `/locations/resolve` | Public/rate-limited | Normalize selected place |

### 6.2 Customer booking and account

| Method | Path | Access | Purpose / important validation |
|---|---|---|---|
| `POST` | `/availability/search` | Public/session | Typed service request; capacity, zone, schedule, maintenance, overlap |
| `POST` | `/quotes` | Public/session | Server price for selected available vehicle; 15-minute expiry |
| `POST` | `/quotes/{id}/coupon` | Customer | Validate and reserve eligible coupon use |
| `POST` | `/bookings` | Customer + idempotency | Create draft from live quote and vehicle hold |
| `POST` | `/bookings/{id}/payment-order` | Booking owner + idempotency | Create/reuse Razorpay order for server total |
| `GET` | `/bookings` | Customer | List own bookings |
| `GET` | `/bookings/{id}` | Owner, assigned driver, or admin | Role-redacted booking detail |
| `POST` | `/bookings/{id}/cancel-preview` | Booking owner | Return fee/refund under captured policy |
| `POST` | `/bookings/{id}/cancel` | Booking owner + idempotency | Guarded cancellation and refund initiation |
| `GET` | `/bookings/{id}/receipt` | Booking owner/admin | Receipt HTML metadata |
| `POST` | `/documents/{id}/download-url` | Authorized viewer | Short-lived private PDF URL |
| `POST` | `/bookings/{id}/review` | Owner of completed booking | Create one verified review |
| `GET/PATCH` | `/me` | Authenticated | Own profile |
| `GET` | `/me/notifications` | Authenticated | Own in-app feed |
| `POST` | `/me/notifications/{id}/read` | Notification owner | Mark read |
| `POST` | `/support-requests` | Customer | Persist and notify admin of support request |

### 6.3 Driver

| Method | Path | Access | Purpose / important validation |
|---|---|---|---|
| `GET` | `/driver/dashboard` | Driver | Counts, current status, earnings summary |
| `GET` | `/driver/trips` | Driver | Own assigned/history trips |
| `GET` | `/driver/trips/{id}` | Assigned driver | Minimum required trip/customer detail |
| `POST` | `/driver/trips/{id}/accept` | Assigned driver + idempotency | Accept pending assignment |
| `POST` | `/driver/trips/{id}/reject` | Assigned driver + idempotency | Reject with reason |
| `POST` | `/driver/trips/{id}/on-the-way` | Assigned driver + idempotency | Guarded status transition |
| `POST` | `/driver/trips/{id}/arrived` | Assigned driver + idempotency | Guarded status transition |
| `POST` | `/driver/trips/{id}/start` | Assigned driver + idempotency | Guarded status transition |
| `POST` | `/driver/trips/{id}/complete` | Assigned driver + idempotency | Complete and create earning/receipt work |
| `PATCH` | `/driver/availability` | Driver | Available/offline with assignment guard |
| `GET` | `/driver/earnings` | Driver | Own read-only earnings |

### 6.4 Admin

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/admin/dashboard` | Operational metrics and recent activity |
| `GET/PATCH` | `/admin/customers/{id}` | View and activate/deactivate customer through commands |
| `GET/POST` | `/admin/drivers` | Search/list or create driver login/profile |
| `GET/PATCH` | `/admin/drivers/{id}` | View/edit/status driver |
| `POST` | `/admin/drivers/{id}/documents` | Secure document upload intent/metadata |
| `GET/POST` | `/admin/vehicles` | Search/list or create vehicle |
| `GET/PATCH/DELETE` | `/admin/vehicles/{id}` | View/edit or deactivate; no destructive historical delete |
| `POST` | `/admin/vehicles/{id}/images/upload-intent` | Presigned quarantine upload |
| `POST` | `/admin/vehicles/{id}/images/complete` | Validate and queue image processing |
| `PATCH` | `/admin/vehicles/{id}/images/order` | Reorder/set primary |
| `GET` | `/admin/bookings` | Filtered booking list |
| `GET` | `/admin/bookings/{id}` | Complete booking timeline |
| `POST` | `/admin/bookings/{id}/assign-driver` | Reserve available driver and notify parties |
| `POST` | `/admin/bookings/{id}/change-driver` | Close assignment and reserve replacement |
| `POST` | `/admin/bookings/{id}/cancel` | Guarded, reasoned, audited cancellation |
| `POST` | `/admin/bookings/{id}/modify` | Validate, requote, version, and notify |
| `GET` | `/admin/payments` | Payment/refund/reconciliation list |
| `POST` | `/admin/payments/{id}/refund` | Allowed amount, reason, idempotency, audit |
| `GET/POST` | `/admin/pricing-rules` | List or create draft rule version |
| `POST` | `/admin/pricing-rules/{id}/publish` | Validate and activate future-effective rule |
| `GET/POST` | `/admin/coupons` | List or create coupon |
| `GET` | `/admin/reviews` | Review moderation queue/statistics |
| `POST` | `/admin/reviews/{id}/hide` | Hide with reason and audit |
| `GET` | `/admin/notification-deliveries` | Delivery logs without message secrets |
| `POST` | `/admin/notification-deliveries/{id}/retry` | Retry eligible failed delivery |
| `GET` | `/admin/reports/{type}` | Bounded report or CSV export |
| `GET/PATCH` | `/admin/settings` | Typed, versioned platform settings |

### 6.5 Integration and health

| Method | Path | Access | Purpose |
|---|---|---|---|
| `POST` | `/webhooks/razorpay` | Verified raw-body signature | Persist unique event and acknowledge quickly |
| `GET` | `/health` | Public/minimal | Service status |
| `GET` | `/liveness` | Infrastructure | Process health |
| `GET` | `/readiness` | Infrastructure | Required dependency health |

Each operation documents request/response schemas, role, ownership, validation, rate-limit class, idempotency, and stable error codes in generated OpenAPI.

---

## 7. Authentication Architecture

### 7.1 Account creation

- Customer registers with name, email or phone, and password; contact verification can be added without changing the user model.
- Driver is created by an admin. The driver receives a one-time activation link and sets a password.
- Admin has no public registration. The first admin is created by a one-time deployment command; additional admins are created by an authenticated admin command added only when needed.

### 7.2 Token security

- Argon2id password hashing.
- The MVP uses one short-lived signed bearer JWT in the single browser key `ridex_jwt`.
- JWT claims contain user ID, role, display name, email, phone, issued time, and expiry; they never contain passwords or password hashes.
- API requests send the JWT in the `Authorization: Bearer` header. No profile or booking draft is stored separately in browser storage.
- A strict Content Security Policy and XSS controls are mandatory because local storage is JavaScript-readable.
- Admin login has stricter rate limits and MFA before public launch.
- Password reset tokens are short-lived, one-use, hashed at rest, and revoke existing sessions after reset.

### 7.3 Authorization

Backend dependency checks role for every protected endpoint and then ownership/assignment:

- Customer resource: `booking.customer_id == current_user.id`.
- Driver resource: `booking.driver_id == current_driver.id` and assignment is active.
- Admin: role `ADMIN`; high-risk changes still require reason, recent authentication, state guard, and audit.

Frontend route guards improve navigation only. They never replace backend authorization. Unauthorized resources return `404` where exposing existence would leak information.

---

## 8. Booking Architecture

### 8.1 Booking state machine

```mermaid
stateDiagram-v2
    [*] --> DRAFT
    DRAFT --> PENDING_PAYMENT: checkout
    PENDING_PAYMENT --> CONFIRMED: verified payment
    PENDING_PAYMENT --> PAYMENT_FAILED: terminal failure/expiry
    CONFIRMED --> DRIVER_ASSIGNED: admin assigns
    DRIVER_ASSIGNED --> DRIVER_ACCEPTED: driver accepts
    DRIVER_ASSIGNED --> CONFIRMED: driver rejects
    DRIVER_ACCEPTED --> DRIVER_ON_THE_WAY
    DRIVER_ON_THE_WAY --> DRIVER_ARRIVED
    DRIVER_ARRIVED --> TRIP_STARTED
    TRIP_STARTED --> TRIP_COMPLETED
    DRAFT --> CANCELLED
    PENDING_PAYMENT --> CANCELLED
    CONFIRMED --> CANCELLED: policy/admin
    DRIVER_ASSIGNED --> CANCELLED: policy/admin
    DRIVER_ACCEPTED --> CANCELLED: controlled exception
    CANCELLED --> REFUND_PENDING: paid and refundable
    REFUND_PENDING --> REFUNDED: provider confirms
```

Only command services can transition status. Each command validates current state, actor, expected version, payment/assignment facts, and policy; then updates state, writes audit/trip event, and creates notifications in one database transaction.

### 8.2 Availability and holds

1. Search checks vehicle operational status, capacity, maintenance, and overlapping active reservations.
2. Quote captures pricing-rule version and expires after 15 minutes.
3. Booking creation creates a vehicle hold with the same checkout deadline.
4. Deterministic half-hour slot documents with a unique `_id` are the MongoDB concurrency guard; an application “availability check” alone is insufficient.
5. Verified payment activates the reservation. Failed/expired checkout releases it.
6. Driver assignment creates a driver reservation for the full trip plus buffer and fails atomically on overlap.

### 8.3 Idempotency

Booking creation, payment order, cancellation, refund, assignment, and driver commands accept a client key. Reusing a key with the same request returns the original response; reusing it with a different request returns `409 IDEMPOTENCY_CONFLICT`.

---

## 9. Pricing Architecture

The backend `PricingService` selects the active rule version for service type and vehicle category, evaluates service-specific components, applies one eligible coupon, calculates tax, and returns an immutable quote snapshot.

| Service | Configurable components |
|---|---|
| Normal | base fare, included km, per-km, optional time charge, minimum fare |
| Airport | direction/airport base, included km, per-km, waiting grace/rate, parking/toll treatment |
| Hourly | package price, duration, included km, extra km, extra hour |
| Outstation One Way | minimum km, per-km, driver allowance, toll/state/parking treatment |
| Outstation Round Trip | minimum km/day, per-km, service days, driver allowance/day, toll/state/parking treatment |

Quote output: base fare, distance, package, extra km/hour assumptions, driver allowance, toll/parking treatment, tax, discount, and total. Money uses integer paise and ISO currency code; the frontend only displays the server response.

Rules are draft, active, or retired and effective-dated. Publishing validates missing/overlapping rules and runs admin-visible examples before activation. Existing bookings retain their pricing snapshot.

---

## 10. Payment Architecture

```mermaid
sequenceDiagram
    participant C as Customer
    participant A as FastAPI
    participant DB as MongoDB Atlas
    participant R as Razorpay
    participant W as Worker
    C->>A: Create payment order + idempotency key
    A->>DB: Lock booking; verify quote and hold
    A->>R: Create order with backend amount
    R-->>A: Razorpay order ID
    A-->>C: Checkout configuration
    C->>R: Pay
    R-->>A: Signed webhook
    A->>DB: Store unique webhook event
    A-->>R: 2xx
    W->>DB: Verify/process event idempotently
    W->>DB: Payment success + CONFIRMED + notification work
    C->>A: Get booking
    A-->>C: Authoritative status
```

- The browser callback is never proof of payment.
- Webhook verification uses the raw body and secret; provider event IDs are unique.
- Payment amount/currency must match the stored order and booking quote.
- Local idempotency prevents duplicate provider orders when a request is retried.
- A reconciliation job checks pending/uncertain orders and refunds against Razorpay.
- Refund status changes only after the backend request/provider webhook is verified.
- No card, UPI credential, CVV, or full provider payload is stored.

---

## 11. Notification Architecture

```text
Booking/Payment/Trip service
  -> insert in-app notification + delivery record in same DB transaction
  -> Redis queue wake-up
  -> background worker
  -> Email adapter now
  -> SMS / WhatsApp adapters later
```

No Kafka or separate event service is needed. MongoDB delivery documents make work recoverable if Redis restarts. The worker retries transient failures with backoff and marks terminal failures for admin review.

| Event | Customer | Driver | Admin |
|---|---|---|---|
| Booking confirmed | Email + in-app | - | In-app |
| Payment confirmed/failed | Email + in-app | - | In-app on failure/anomaly |
| Driver assigned | Email + in-app | Email + in-app | In-app |
| Driver on the way/arrived | In-app + email initially | In-app | In-app |
| Trip started/completed | In-app; completion email | In-app | In-app |
| Booking cancelled/refund | Email + in-app | In-app if assigned | In-app |
| Review request | Email + in-app | - | - |
| Receipt ready | Email + in-app | - | In-app on failure |

Notifications support unread, read, and archived. Transactional notifications are separate from future marketing preferences.

---

## 12. Email Architecture

- `EmailService` exposes provider-neutral send operations.
- `EmailTemplateService` renders versioned HTML and plain-text templates.
- Worker sends asynchronously through SMTP/transactional provider; booking APIs do not wait for SMTP.
- Delivery records store template/version, redacted recipient, status, attempts, provider ID, safe error code, and timestamps, not unnecessary message bodies.
- Retry schedule starts at 1, 5, and 30 minutes; exhausted work remains visible to admin.
- Production configures SPF, DKIM, DMARC, bounce/complaint handling, and a transactional sending domain.

Templates: Welcome, Booking Confirmation, Payment Confirmation, Driver Assigned, Driver On The Way, Trip Completed, Booking Cancelled, Refund, Receipt, and Review Request.

The confirmation subject may use “Your Ride is Confirmed - Booking #RX12345”. Email body contains a concise booking summary and signed application links. Driver details are included only after assignment. Receipt PDF may be attached within provider size limits; otherwise use a secure link.

---

## 13. Receipt Architecture

1. Verified payment confirmation queues receipt generation.
2. Worker loads an immutable booking, pricing, payment, customer, vehicle, and assigned-driver snapshot.
3. Versioned HTML/CSS template renders PDF with WeasyPrint.
4. PDF is hashed and stored privately in object storage; `documents` stores key/version/hash.
5. Customer receives an accessible web view, short-lived PDF URL, and email.

Receipt fields: platform identity/contact, booking ID, customer name/phone/email, service, route or hourly package, date/time, vehicle, assigned driver, base/distance/package/extra/allowance/tax/discount line items, total, payment method/status/reference, cancellation policy, and support contact.

Issued receipt versions are never overwritten. A corrected document supersedes the old version. Legal GST invoice fields and numbering are activated only after accountant approval; a payment receipt must not be mislabeled as a tax invoice.

---

## 14. Google Maps Architecture

- Places API (New) autocomplete/details supplies place IDs, formatted addresses, and coordinates.
- Maps JavaScript API renders customer/admin maps using a browser key restricted by exact web origins and API.
- Routes API is called by backend for distance/duration used in pricing and availability.
- Browser-selected locations are resolved/validated by backend before quote.
- Store place ID, address snapshot, latitude, and longitude on the booking; do not proxy/store map tiles.
- Use autocomplete session tokens, explicit Places field masks, API quotas, and cost alerts.

As of 26 September 2026, Place Details (New) can return public rating, rating count, Google Maps links, and other fields at different billing tiers. Request only necessary fields and follow attribution/caching terms.

The platform's Google Place ID and official Maps/review URL are admin settings. After an internal review, “Review us on Google” opens that URL. The application does not scrape, generate, transfer, or post Google reviews.

---

## 15. Vehicle Image Architecture

1. Admin requests an upload intent with filename, size, MIME type, and image category.
2. Backend returns a short-lived presigned upload to a private quarantine prefix.
3. Worker verifies file signature/MIME, size and pixel limits, strips metadata, normalizes orientation, scans content, and creates AVIF/WebP/JPEG responsive renditions.
4. Approved renditions move to a CDN-served prefix; database records the storage key/rendition manifest.
5. Admin reorders images and selects exactly one primary image.

Recommended source limit is 10 MB with JPEG, PNG, and WebP initially. Invalid, oversized, unprocessed, or deleted files never become public. The frontend uses explicit aspect ratios, responsive `srcset`, lazy loading below the fold, and useful alt text.

---

## 16. Role and Permission Matrix

Legend: `Own` is the user's record, `Assigned` is the driver's active assignment, `All` is admin access through audited application commands.

| Capability | Customer | Driver | Admin |
|---|---:|---:|---:|
| Register/login | Yes | Login only | Login only |
| Manage own profile/session | Own | Own | Own |
| Search/quote | Yes | No | View/test |
| Create/pay booking | Own | No | Assisted booking deferred |
| View booking | Own | Assigned, redacted | All |
| Cancel booking | Own, policy | No | All, guarded |
| View receipt/payment | Own | No | All, redacted |
| Review completed trip | Own eligible booking | No | View/moderate |
| View notifications | Own | Own | Own + delivery logs |
| Update trip status | No | Assigned only | Exception commands only |
| Manage driver availability | No | Own | All |
| View driver earnings | No | Own | All |
| Manage customers | No | No | All |
| Manage drivers/documents | No | Own profile view | All |
| Manage vehicles/images | No | Assigned vehicle view | All |
| Assign/change driver | No | Accept/reject | All |
| Manage pricing/coupons | No | No | All |
| Manage payments/refunds | Own checkout | No | All, guarded |
| View reports/audit/settings | No | No | All |

There are exactly three role values. Fine-grained admin roles are deferred; high-risk admin actions still require recent authentication, reason, and immutable audit.

---

## 17. Folder Structure

```text
carrental/
  docs/
    MVP_ARCHITECTURE.md
  frontend/
    src/
      app/
        router.tsx
        providers.tsx
      assets/
      components/
        ui/
        layout/
        forms/
      features/
        auth/
        home/
        booking/
        vehicles/
        payments/
        bookings/
        trips/
        reviews/
        notifications/
        profile/
        support/
        driver/
        admin/
      hooks/
      layouts/
        CustomerLayout.tsx
        DriverLayout.tsx
        AdminLayout.tsx
      pages/
      services/
        api/
      schemas/
      store/
      types/
      utils/
    tests/
  backend/
    app/
      main.py
      api/
      core/
        config.py
        database.py
        security.py
        logging.py
      models/
      schemas/
      repositories/
      services/
        auth_service.py
        availability_service.py
        pricing_service.py
        booking_service.py
        payment_service.py
        driver_service.py
        notification_service.py
        email_service.py
        document_service.py
        maps_service.py
      integrations/
        razorpay.py
        google_maps.py
        storage.py
        smtp.py
      workers/
      templates/
        email/
        receipts/
    alembic/
    tests/
      unit/
      integration/
      api/
  infrastructure/
  .github/workflows/
  .env.example
  README.md
```

This is one frontend and one backend. Split a module only when its file becomes difficult to maintain; do not create a package per database table.

---

## 18. Environment Variables

Only placeholders are committed in `.env.example`; production values come from the deployment secret manager.

```dotenv
APP_NAME=RideX
APP_ENV=development
APP_BASE_URL=http://localhost:5173
API_BASE_URL=http://localhost:8000
ALLOWED_ORIGINS=http://localhost:5173
LOG_LEVEL=INFO

MONGODB_URI=mongodb+srv://username:password@cluster.mongodb.net/?retryWrites=true&w=majority
MONGODB_DATABASE=ridex
REDIS_URL=redis://localhost:6379/0
SECRET_KEY=replace_me
TOKEN_ENCRYPTION_KEY=replace_me
ACCESS_TOKEN_TTL_MINUTES=15
REFRESH_TOKEN_TTL_DAYS=30

STORAGE_PROVIDER=s3
STORAGE_BUCKET=replace_me
STORAGE_REGION=ap-south-1
CDN_BASE_URL=https://cdn.example.com

GOOGLE_MAPS_SERVER_API_KEY=replace_me
GOOGLE_MAPS_BROWSER_API_KEY=replace_me
GOOGLE_PLACE_ID=replace_me
GOOGLE_REVIEW_URL=https://search.google.com/local/writereview?placeid=replace_me

RAZORPAY_KEY_ID=replace_me
RAZORPAY_KEY_SECRET=replace_me
RAZORPAY_WEBHOOK_SECRET=replace_me

SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USERNAME=replace_me
SMTP_PASSWORD=replace_me
SMTP_FROM_EMAIL=support@example.com
SMTP_FROM_NAME=RideX
SMTP_USE_TLS=true
SMTP_USE_SSL=false

WORKER_QUEUE_ENABLED=true
SENTRY_DSN=
OTEL_EXPORTER_OTLP_ENDPOINT=
```

Startup rejects placeholder production secrets, unsafe origins, invalid URLs, missing required provider values, and simultaneous SMTP TLS/SSL modes.

---

## 19. Responsive Design

### 19.1 Visual direction

Use a clear transport-service visual language: blue primary, dark navy text/navigation, green success, orange warning, red error, and light neutral surfaces. Keep corners at 8-12 px, use prominent real vehicle photography, clear labels, and restrained cards. Avoid decorative dashboard cards, oversized marketing copy, and nested cards.

### 19.2 Customer

- Mobile first from 320 px; single-column booking, full-width vehicle media, 48 px touch targets, sticky primary action.
- Bottom navigation: Home, Book, Bookings, Profile.
- On tablet, use two columns where content remains readable.
- On desktop, use form/results plus a sticky fare summary; never hide required errors behind it.

### 19.3 Driver

- Prioritize Dashboard, Trips, Active Trip, Profile on mobile.
- Trip state action is the largest control and only valid next actions are shown.
- Support intermittent connectivity: pending action indicator, idempotent retry, and explicit conflict message.

### 19.4 Admin

- Desktop sidebar and dense, scannable tables with filters and pagination.
- Tablet uses collapsible sidebar and horizontally scrollable tables or card rows where needed.
- Destructive/high-impact commands are distinct and require confirmation/reason.

### 19.5 Shared quality requirements

- Skeletons match final content geometry. Empty and error states always offer a relevant next action.
- Keyboard navigation, visible focus, semantic HTML, persistent input labels, linked errors, sufficient contrast, and reduced-motion support target WCAG 2.2 AA.
- Test widths: 320, 375, 390, 414, 768, 1024, 1280, 1440, and 1920 px. Text and controls must not overlap.

---

## 20. MVP Implementation Phases

### Phase 0: Decisions and UX contract

- Approve assumptions in section 0, cancellation rules, pricing examples, tax/receipt wording, driver earnings, and privacy copy.
- Wireframe all customer steps plus admin assignment and driver active-trip flow.
- Define acceptance criteria and error/empty/loading states.

**Exit:** product, operations, finance/accounting, and engineering approve the contract.

### Phase 1: Foundation and authentication

- Create frontend/backend projects, Atlas index/schema bootstrap, Redis worker, CI, configuration, structured logging, and health checks.
- Implement three-role users, customer registration, login/logout/refresh/reset, driver/admin account creation path, route guards, backend authorization, and audit foundation.
- Build shared responsive UI primitives and three layouts.

**Exit:** each role can authenticate and cannot access another role's protected APIs/routes.

### Phase 2: Admin fleet and pricing

- Vehicle CRUD, categories/specifications/amenities, status/maintenance, secure image pipeline, and galleries.
- Driver CRUD, activation, documents, availability, and basic earning rules.
- Versioned pricing rules, hourly packages, coupons, and admin preview examples.

**Exit:** admin can prepare valid vehicles, drivers, images, availability, and prices without frontend hard-coding.

### Phase 3: Customer discovery and booking forms

- Home/services pages, four separate service forms, Places autocomplete/map confirmation, search results, vehicle details, passenger details, fare summary, and persisted step state.
- Backend service validation, route estimation, availability query, quote engine, and vehicle hold.

**Exit:** customer can reach an accurate expiring quote for every service type; concurrency test prevents two holds on one vehicle.

### Phase 4: Booking and payment

- Draft booking, state machine, idempotency, Razorpay orders/webhook verification/reconciliation, confirmation page, My Bookings, detail, and policy-based cancellation/refund.
- Backend receipt HTML/PDF and private download.

**Exit:** sandbox E2E completes search -> booking -> verified payment -> confirmation -> receipt, including duplicate webhook/click tests.

### Phase 5: Admin dispatch and driver app

- Admin booking tables/detail, driver assignment/replacement, reservation conflict checks, and operational dashboard.
- Driver dashboard/trips, accept/reject, on-the-way, arrived, start, complete, history, availability, profile, and read-only earnings.
- Customer active-trip/status timeline and driver detail.

**Exit:** confirmed booking progresses through assignment and completion with all transitions recorded.

### Phase 6: Notifications, reviews, and support

- Database-backed in-app/email delivery work, templates, retries, admin logs, and receipt email.
- Verified post-trip review, moderation, Google review link, support requests, and customer notification center.

**Exit:** critical lifecycle events create in-app/email deliveries and failed sends can be retried safely.

### Phase 7: Reports and production readiness

- Admin metrics/reports, payment reconciliation view, settings, audit search, retention jobs, and data export controls.
- Unit/integration/API tests, pricing golden cases, RBAC matrix tests, webhook tests, availability concurrency, receipt tests, Playwright E2E/responsive/accessibility checks, load tests, and dependency/security scans.
- Managed deployment, CDN/WAF, database backups and restore test, alerting, runbooks, CSP/security headers, secret rotation, and launch checklist.

**Exit:** critical E2E passes in staging; restore, rollback, payment reconciliation, and alert drills are complete.

---

## 21. Security, Testing, and Operations Baseline

### 21.1 Security

- Input validation with Pydantic/Zod, allowlisted PyMongo filters and updates, output encoding, strict CORS/CSP/security headers, bearer authorization, and route-specific rate limits.
- Private database/Redis/object storage networking where available; TLS in transit and encryption at rest.
- Upload signature/type/size/pixel validation, malware scan, metadata stripping, and private quarantine.
- Secrets only in environment/secret manager; redact passwords, tokens, OTPs, full phone/email, payment payloads, IDs, and precise trip coordinates from logs.
- Payment signatures, unique webhook IDs, idempotency, amount matching, and reconciliation.
- Audit login, customer/driver/vehicle changes, booking commands, assignment, pricing publication, payment/refund changes, moderation, and settings.

### 21.2 Minimum automated tests

- Unit: pricing, coupons, cancellation, state transitions, rounding.
- Database/integration: reservation overlap, migrations, role/ownership scopes, idempotency.
- API: authentication, all role boundaries, booking/payment validation, webhook signatures and duplicates.
- Worker: retries, email failure, image processing, PDF generation.
- Frontend: service forms, loading/error/empty states, route guards, keyboard behavior.
- E2E: customer booking/payment, admin assignment, driver completion, customer review/receipt.

### 21.3 Deployment and observability

Deploy the Vite frontend on Vercel and the FastAPI service/workers on Render; use MongoDB Atlas, managed Redis, and private object storage/CDN. Docker may simplify deployment but is optional for local development. Kubernetes is unnecessary for MVP.

Collect structured logs, request/correlation IDs, error tracking, API latency/error metrics, database pool/locks, queue age, booking conversion, reservation conflicts, payment/webhook failures, assignment SLA, email failures, and object-processing failures. Alert on payment confirmation backlog, database unavailability, queue age, and repeated booking failures.

Target initial service availability is 99.9%, with documented backup retention, an RPO target of 15 minutes, an RTO target of 2 hours, and tested restore/rollback procedures.

---

## 22. Architecture Acceptance Checklist

- [ ] Exactly three roles exist: `CUSTOMER`, `ADMIN`, `DRIVER`.
- [ ] No rental-company portal, tenant schema, company payout, or company role exists.
- [ ] All four dedicated booking flows and both outstation modes are approved.
- [ ] Pricing/cancellation/tax/receipt examples are approved before payment work.
- [ ] Database constraints prevent vehicle and driver overlap.
- [ ] Payment confirmation depends only on verified backend/provider facts.
- [ ] Admin assignment and driver transition rules are approved.
- [ ] Internal and Google review flows remain separate.
- [ ] All twenty requested architecture outputs and implementation phases are approved.
- [ ] Only then does Phase 1 coding begin.