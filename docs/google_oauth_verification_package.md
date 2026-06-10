# Pacote de verificação Google OAuth — ZapAction Calendar

Texto pronto para colar no **OAuth Verification Center** (inglês recomendado pelo Google).

## Scope justifications (English)

### `https://www.googleapis.com/auth/calendar.events`

ZapAction is a scheduling platform for businesses. When a professional connects Google Calendar in the ZapAction dashboard (Agenda → Professionals → Connect Google), our app uses this scope to **create** calendar events when a customer books an appointment and to **delete** events when an appointment is cancelled. We only modify events created by our service; we do not manage calendar lists, sharing settings, or ACLs. A narrower scope such as read-only would not allow writing bookings to the user's calendar.

### `https://www.googleapis.com/auth/calendar.events.freebusy`

We use the Google Calendar API method `freebusy.query` to read **availability** (busy/free time ranges) so customers can see open time slots on the public booking page and in WhatsApp scheduling flows. The `calendar.events` scope alone does not authorize `freebusy.query` per Google's API reference. We do not read full event titles or descriptions for unrelated events—only free/busy intervals needed for slot calculation.

## Why we do NOT request `calendar` (full access)

We intentionally avoid `https://www.googleapis.com/auth/calendar` because our product does not need to list calendars, change sharing, or delete calendars—only event insert/delete and freebusy for scheduling.

## Demo video script (YouTube Unlisted, English UI)

Duration target: 3–5 minutes.

1. **Intro (10s)**  
   Show browser on `https://zapaction.com.br` — briefly state: "ZapAction scheduling with Google Calendar sync."

2. **Login (20s)**  
   Go to `https://api.updigitalbrasil.com.br` (or painel login). Log in as a business user.

3. **Navigate to Agenda (15s)**  
   Open **Painel → Agenda → Professionals** tab.

4. **Connect Google (60s)**  
   Click **Connect Google** for one professional.  
   **Pause on OAuth consent screen** — ensure visible:
   - App name: **ZapAction**
   - Scopes listed (calendar events + free/busy)
   - Browser URL bar (OAuth client visible in redirect flow)
   - Language toggle bottom-left → **English** (Google requirement)

5. **Grant access (20s)**  
   Complete consent. Return to ZapAction — show success message "Google Calendar conectado."

6. **Show scope usage (90s)**  
   - Open public booking link or scheduling screen with **green available slots** (freebusy).  
   - Complete one test booking.  
   - Open Google Calendar in another tab — show **new event** created by ZapAction.  
   - Optional: cancel booking in panel — show event removed.

7. **Disconnect (20s)**  
   Show **Disconnect Google** in Professionals tab (proves user control / revocation path).

8. **Outro (10s)**  
   State that data use is described at `https://zapaction.com.br/politica`.

Upload to YouTube Studio → Visibility: **Unlisted** → paste link in verification form.

## Submission steps (Console)

1. GCP → **APIs & Services** → **OAuth consent screen**
2. Confirm all branding fields and scopes (see checklist)
3. **Publish app** (Testing → Production)
4. Open **OAuth Verification Center** → **Submit for verification**
5. Attach:
   - Scope justifications (above)
   - Demo video URL
   - Privacy policy URL: `https://zapaction.com.br/politica`
6. Respond to Trust & Safety email within 48h if they request changes

Typical review: **3–5 business days**.

## URLs for consent screen (copy-paste)

```
Home page:        https://zapaction.com.br
Privacy policy:   https://zapaction.com.br/politica
Terms of service: https://zapaction.com.br/termos
Redirect URI:     https://api.updigitalbrasil.com.br/painel/agenda/google/callback
```
