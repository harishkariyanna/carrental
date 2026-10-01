# RideX Endpoint and Screen Audit

Audit date: 2026-10-01

FastAPI OpenAPI exposes 96 HTTP operations. Every operation belongs to a web screen, an integration callback, a media resource, or an operational health surface.

## Operational contracts

- One vehicle document represents one physical fleet unit.
- Supported vehicle types are `SEDAN_CNG`, `SEDAN_NON_CNG`, `SUV`, `ERTIGA`, `INNOVA`, `INNOVA_CRYSTA`, and `TT`.
- Vehicle status is operational only: `ACTIVE`, `MAINTENANCE`, or `INACTIVE`.
- Booking availability comes from `vehicle_reservations`; it is never entered manually as a vehicle status.
- Multiple cars of the same type are represented by multiple vehicle records with unique registration numbers.
- Driver `ONLINE` means on duty with live location and is assignment-eligible.
- Driver `OFFLINE` means on leave and is not eligible for new assignments.
- Admins can place an on-duty driver on leave. Only the driver can start duty because live location is required.
- Future booking detail is owned by `GET /api/v1/admin/bookings/calendar` and the Admin Future Calendar screen.

## Platform and health

| Operations | Owner / purpose |
| --- | --- |
| `GET /` | API identity and docs discovery |
| `GET /health` | Render/deployment health probe |

## Authentication and account recovery

| Operations | Owner / purpose |
| --- | --- |
| `POST /api/v1/auth/register` | Login modal customer/driver registration |
| `POST /api/v1/auth/login` | Login modal |
| `POST /api/v1/auth/logout` | Public and admin sign-out controls |
| `GET /api/v1/auth/session` | AppProvider session restoration |
| `GET /api/v1/auth/me` | External/API-client current-user lookup; web app uses session |
| `POST /api/v1/auth/forgot-password` | Forgot Password page |
| `POST /api/v1/auth/reset-password` | Forgot Password OTP completion |

## Customer booking and catalog

| Operations | Owner / purpose |
| --- | --- |
| `GET /api/v1/vehicles` | Home fleet, Fleet page, customer catalog |
| `GET /api/v1/vehicles/{vehicle_id}` | Vehicle detail page |
| `POST /api/v1/quotes` | Results page; pricing plus reservation-aware physical-unit availability |
| `GET, POST /api/v1/bookings` | Customer booking list and checkout creation |
| `GET /api/v1/bookings/{booking_id}` | Customer booking detail |
| `POST /api/v1/bookings/{booking_id}/cancel` | Customer/admin cancellation |
| `POST /api/v1/bookings/{booking_id}/payment-order` | UPI checkout |
| `GET /api/v1/bookings/{booking_id}/receipt.pdf` | Receipt download |
| `POST /api/v1/bookings/{booking_id}/reviews` | Completed-trip review form |
| `GET /api/v1/payment-policy/preview` | Checkout advance breakdown |
| `GET /api/v1/coupons/public` | Checkout offers |

## Customer workspace

| Operations | Owner / purpose |
| --- | --- |
| `GET /api/v1/customer/dashboard` | Customer dashboard metrics and active/upcoming trips |
| `GET, PATCH /api/v1/customer/profile` | Customer profile |
| `GET /api/v1/customer/reviews` | My Reviews |
| `GET, POST /api/v1/customer/saved-locations` | Saved Locations and booking shortcuts |
| `DELETE /api/v1/customer/saved-locations/{location_id}` | Remove saved location |
| `GET /api/v1/notifications` | Customer/driver notifications |
| `POST /api/v1/notifications/{notification_id}/read` | Notification read state |
| `POST /api/v1/support-requests` | Customer/driver Support page |

## Payments and integrations

| Operations | Owner / purpose |
| --- | --- |
| `GET /api/v1/payments/{payment_id}/qr` | UPI QR panel |
| `POST /api/v1/payments/{payment_id}/demo-confirm` | Development payment confirmation |
| `POST /api/v1/payments/{payment_id}/verify` | Provider signature verification |
| `POST /api/v1/webhooks/razorpay` | Server-to-server Razorpay callback; intentionally no UI |

## Maps

| Operations | Owner / purpose |
| --- | --- |
| `GET /api/v1/maps/geocode` | Location search compatibility |
| `GET /api/v1/maps/reverse` | Map picker and driver nearest-address display |
| `GET /api/v1/maps/route` | Quote distance, booking preview, driver/customer ETA |

## Driver workspace

| Operations | Owner / purpose |
| --- | --- |
| `GET /api/v1/driver/dashboard` | Driver dashboard, duty state, earnings |
| `PATCH /api/v1/driver/availability` | Start Duty / Go On Leave |
| `GET /api/v1/driver/trips` | Driver trip list |
| `POST /api/v1/driver/trips/{booking_id}/{command}` | Accept and start-navigation transitions |
| `POST /api/v1/driver/documents/{document_type}` | Driver onboarding documents |

## Trip operations

| Operations | Owner / purpose |
| --- | --- |
| `GET /api/v1/trip-operations/{booking_id}` | Driver operations and customer live trip |
| `POST /api/v1/trip-operations/{booking_id}/location` | Driver live location and arrival detection |
| `POST /api/v1/trip-operations/{booking_id}/arrived` | Manual arrival fallback |
| `POST /api/v1/trip-operations/{booking_id}/start-waiting` | Local-trip waiting timer |
| `GET /api/v1/trip-operations/{booking_id}/otp/{purpose}` | Start/completion OTP display |
| `POST /api/v1/trip-operations/{booking_id}/start` | Start OTP verification |
| `POST /api/v1/trip-operations/{booking_id}/extras` | Toll, parking, and other charges |
| `POST /api/v1/trip-operations/{booking_id}/evidence` | Charge receipt upload |
| `POST /api/v1/trip-operations/{booking_id}/record-balance` | Driver cash/UPI balance collection |
| `POST /api/v1/trip-operations/{booking_id}/request-end` | Destination-zone completion request |
| `POST /api/v1/trip-operations/{booking_id}/verify-end/DRIVER_END` | Completion OTP verification |

## Admin operations

| Operations | Owner / purpose |
| --- | --- |
| `GET /api/v1/admin/dashboard` | Admin dashboard |
| `GET /api/v1/admin/users`, `PATCH /api/v1/admin/users/{user_id}` | Customer account management |
| `GET, POST /api/v1/admin/drivers` | Driver management |
| `PATCH /api/v1/admin/drivers/{driver_id}` | Approval, leave, account, licence, vehicle assignment |
| `GET, POST /api/v1/admin/vehicles` | Fixed-type physical-unit fleet CRUD |
| `PATCH, DELETE /api/v1/admin/vehicles/{vehicle_id}` | Edit or archive fleet unit |
| `POST /api/v1/admin/vehicles/{vehicle_id}/assign-driver` | Default driver assignment |
| `GET /api/v1/admin/bookings` | Booking table |
| `GET /api/v1/admin/bookings/calendar` | Future Calendar range query |
| `GET /api/v1/admin/bookings/{booking_id}` | Detailed booking/events/payment lookup |
| `GET /api/v1/admin/bookings/{booking_id}/available-drivers` | Schedule-aware assignment options |
| `POST /api/v1/admin/bookings/{booking_id}/assign-driver` | Admin assignment override |
| `GET /api/v1/admin/payments` | Payment ledger |
| `GET, POST /api/v1/admin/pricing-rules` | Fixed-type pricing rules |
| `PATCH /api/v1/admin/pricing-rules/{rule_id}` | Activate/deactivate pricing version |
| `GET, POST /api/v1/admin/coupons` | Coupon administration |
| `PATCH /api/v1/admin/coupons/{coupon_id}` | Coupon update/status |
| `GET /api/v1/admin/reviews` | Review moderation list |
| `PATCH /api/v1/admin/reviews/{review_id}` | Publish/hide/flag review |
| `GET /api/v1/admin/notifications` | Communication log |
| `GET /api/v1/admin/email-deliveries` | Delivery diagnostics |
| `POST /api/v1/admin/email-deliveries/{delivery_id}/retry` | Retry failed delivery |
| `GET /api/v1/admin/support-requests` | Support queue |
| `PATCH /api/v1/admin/support-requests/{ticket_id}` | Support status workflow |
| `GET /api/v1/admin/reports/summary` | Reports page |
| `GET, PATCH /api/v1/admin/settings` | Platform/payment/support settings |
| `GET /api/v1/admin/audit-logs` | Immutable sensitive-action history |

## Admin database and media

| Operations | Owner / purpose |
| --- | --- |
| `GET /api/v1/admin/database/collections` | Database console collection list |
| `GET /api/v1/admin/database/{collection}` | Safe/redacted record inspection |
| `DELETE /api/v1/admin/database/{collection}` | Eligible-record cleanup |
| `DELETE /api/v1/admin/database/{collection}/{record_id}` | Eligible single-record cleanup |
| `POST /api/v1/admin/media/{entity_type}/{entity_id}` | Admin vehicle/media upload |
| `POST /api/v1/me/profile-image` | Customer/driver profile photo |
| `GET /api/v1/media/{media_id}` | Blob delivery for images/documents |

## Public reviews

| Operations | Owner / purpose |
| --- | --- |
| `GET /api/v1/reviews` | Public homepage; only published reviews |

## Verification

- FastAPI OpenAPI operation count: 96.
- Backend integration suite covers authentication, profiles, quotes, reservation conflicts, multi-unit capacity, bookings, payments, driver assignment/leave, trip state, OTP, extras, media, communications, moderation, reports, database cleanup, settings, and calendar detail.
- Frontend production build and ESLint validate all routed screen contracts.
