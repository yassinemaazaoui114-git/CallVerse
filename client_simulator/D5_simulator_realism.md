# D5 - Real customer messages and real numbers for the Client Simulator (M1)

Owner: Client Simulator. Numbers come from `scripts/p2_build_real_messages.py` (results in
`results/p2_real_numbers_and_profile.json`, hand check in `results/p2_mapping_handcheck.json`) or from the cited
source page. Processed data: `data/processed/real_messages/` (git-ignored; rebuilt by the script).

## The team's table

| Source | Link | Licence | What it gives (messages / numbers) | Size | Domain | Notes |
|---|---|---|---|---|---|---|
| Customer Support on Twitter | [kaggle thoughtvector](https://www.kaggle.com/datasets/thoughtvector/customer-support-on-twitter) | CC BY-NC-SA 4.0 | **messages** (first customer messages, brand replies, multi-turn threads) and **numbers** (timestamps -> arrivals per hour/weekday, brand response times) | 2,811,774 tweets; we kept 165,747 English first messages to 16 brands + 196,763 later customer turns | e-commerce/delivery (Amazon, UPS, Target, Argos, eBay) and travel (Delta, American, BA, Southwest, AirAsia, JetBlue, Alaska, Virgin Atlantic, Virgin Trains, GWR, Airbnb) | 177 MB zip (under the 300 MB limit; the 517 MB CSV is read from the zip). 99.3% of tweets are from Oct-Dec 2017. Public tweets, so shorter and more performative than private chat. |
| Twitter US Airline Sentiment | [kaggle crowdflower](https://www.kaggle.com/datasets/crowdflower/twitter-airline-sentiment) | CC BY-NC-SA 4.0 | **messages** + **numbers** (negative-reason mix labelled by CrowdFlower annotators) | 14,640 tweets | US airlines (tweets dated 16-24 Feb 2015 in the file) | Reason labels by annotators, not customers. |
| eCommerce Customer Service Satisfaction (Flipkart-style) | [kaggle ddosad](https://www.kaggle.com/datasets/ddosad/ecommerce-customer-service-satisfaction) | **to verify** ("other") | **numbers**: contact-reason mix, arrivals per hour/weekday, minutes to first response | 85,907 contacts | e-commerce support | Same set as D6. Licence unclear, so numbers are a secondary source. |
| County Medi-Cal call-center data (California) | [data.chhs.ca.gov](https://data.chhs.ca.gov/dataset/county-medi-cal-call-center-data) (mirrored on [data.ca.gov](https://data.ca.gov/dataset/county-medi-cal-call-center-data)) | CHHS Terms of Use: "freely download and use", "non-exclusive, non-transferable, revocable license to use and distribute", attribution required (data.chhs.ca.gov lists "No License Provided" / "See Terms of Use"; the data.ca.gov mirror lists "Creative Commons Attribution") | **numbers**: monthly abandonment rate, call volume (working hours vs after hours), average wait, per county | 180 county-months with a value (Jan-Jun 2026), 204 county-month rows per file | public-benefits call centers | Real abandonment, but a different domain; column unit not stated (see below). |
| Technion SEE Lab "Anonymous Bank" / US Bank call-center data | [SEE Lab](https://seelab.net.technion.ac.il/) | to verify (access by request) | numbers: call-by-call arrivals, waits, abandonment | to verify | bank call center | Server unreachable from here; access is through the lab (see@technion.ac.il). **Download pending team approval / request.** |
| Public complaint portals (e.g. CFPB complaint database) | [consumerfinance.gov](https://www.consumerfinance.gov/data-research/consumer-complaints/) | to verify | messages (narratives) | to verify | consumer finance, not retail/travel | Not checked in detail: wrong domain for ShopNova/Atlas. |

## What we built (`data/processed/real_messages/`)

- `first_messages.jsonl`: 165,747 anonymised English first messages (35,103 ShopNova-like, 130,644 Atlas-like),
  each with brand, mapped reason, all matching reasons, whether the brand replied, minutes to the first brand reply
  and the anonymised brand reply. 5,587 messages were dropped as not English (heuristic: under 60% of words known
  to the English spell checker) or too short.
- `later_turns_sample.jsonl`: 20,000 of the 196,763 later customer turns (replies to a brand tweet).
- `agent_replies_sample.jsonl`: 3,000 real brand replies, used as the agent turns in the Phase 3 realism test.
- Anonymisation: @handles -> `<HANDLE>`, URLs -> `<URL>`, emails -> `<EMAIL>`, phone numbers -> `<PHONE>`, long
  IDs -> `<ID>`, agent sign-offs such as "^JK" -> `<AGENT>`; leading @mentions are removed.

### Reason mapping (keyword rules in `scripts/realism.py`) and its hand-checked accuracy

The rules match keywords in priority order (ShopNova: damaged_item, refund_request, return_item, late_delivery,
order_status; Atlas: special_assistance, refund_request, cancellation, rebooking, delay_disruption, booking_status);
no match -> `other`. Several matches -> "several reasons in one message".

| Check (judged by Claude Code, reading each message) | n | accuracy | ShopNova | Atlas |
|---|---|---|---|---|
| v1 rules, sample seed 7 (then used to improve the rules) | 50 | 76% | 68% | 84% |
| **v2 rules (final), fresh sample seed 2024, not used for tuning** | 50 | **76%** | 72% | 80% |

Files: `data/processed/real_messages/mapping_handcheck_v1.csv`, `mapping_handcheck_v2.csv`. Typical misses: indirect
lateness ("won't be here til Monday"), "came already opened" (damaged), complaints with no reason keyword.
**Use the mapped reason mix as a rough guide only.**

## Realism profile of real messages (3,000 random messages per group, seed 42)

| Metric | ShopNova first msgs | Atlas first msgs | ShopNova later turns | Atlas later turns |
|---|---|---|---|---|
| words per message, median (IQR) | 21 (15-26) | 19 (14-24) | 17 (9-25) | 16 (8-23) |
| share with a spelling error (pyspellchecker; brand names, Capitalised words, ALL-CAPS tokens ignored) | 28.6% | 32.3% | 23.3% | 20.7% |
| share all-lowercase | 11.2% | 6.2% | 5.6% | 3.8% |
| share with "!" | 15.9% | 25.1% | 13.9% | 20.2% |
| share with "?" | 45.5% | 34.2% | 16.8% | 22.4% |
| share with an ALL-CAPS word (3+ letters, common acronyms excluded) | 9.4% | 17.6% | 6.0% | 7.8% |
| share with an emoji | 7.6% | 12.3% | 5.5% | 8.6% |
| share with several reasons (rule hits >= 2) | 7.1% | 6.0% | 3.4% | 3.7% |

The Phase 3 realism test compares each model against the combined profile (1,500 + 1,500 first messages: median
20 words, IQR 14-24; spelling errors 30.4%; all-lowercase 8.8%; "!" 20.8%; "?" 40.0%; ALL-CAPS 14.1%; emoji 10.4%;
several reasons 6.2%). Caveat: tweets are capped at 140/280 characters and written in public.

## 20 anonymised sample messages (random, seed 11; mapped reason in brackets)

| # | Company | Message |
|---|---|---|
| 1 | Atlas (Delta) [other] | We arrived `<HANDLE>` `<HANDLE>` `<URL>` |
| 2 | Atlas (American) [delay_disruption] | - don't make announcements about rushed boarding if you know full well the flight is delayed until TBD because the idiot pilot called for a maintenance crew to look at a bathroom light. |
| 3 | Atlas (Alaska) [other] | Thank you #TMobileWingman for the FREE WiFi and texting during my `<HANDLE>` flight! Love you, `<HANDLE>`! You rock! You too, Alaska Airlines! Keep up the GREAT work! |
| 4 | Atlas (Delta) [other] | Heading back to Tampa w/ `<HANDLE>` |
| 5 | Atlas (Alaska) [other] | screw you! Done. Done. Done. |
| 6 | Atlas (Virgin Trains) [other] | Typical `<HANDLE>` not being in time so I miss my connecting train and have to wait over half an hour for my next train!!! |
| 7 | Atlas (BA) [other] | the British Airways terminal 7 is a disgrace. Filthy toilets, hardly any chairs to sit and in this day and age, rip off charging for WiFi with `<HANDLE>` - taking custom for granted? |
| 8 | Atlas (Southwest) [booking_status] | can't wait to fly out of Phoenix to HNL #hawaii feb 8th! Can't wait to book as soon as you start taking reservations! |
| 9 | Atlas (Delta) [delay_disruption] | this is the 4th flight in a row on this itinerary that is running late! No excuse |
| 10 | Atlas (GWR) [booking_status] | again the 629 from Reading has just 3 carriages and not the required 8. 1 carriage is 6 seats, the large toilet and cycle rack - guaranteed crush from Slough onwards |
| 11 | ShopNova (Amazon) [other] | I was told I would receive a call back from a manager within two hours and it's now been two and a half with no call. what gives? |
| 12 | ShopNova (Amazon) [other] | In the time it took me to write that tweet, the app started working again. sorry to bother! |
| 13 | ShopNova (UPS) [damaged_item] | Thx `<HANDLE>` for the damaged package &amp; item. On backorder. No wonder the driver didn't ring the bell. `<HANDLE>` `<URL>` |
| 14 | ShopNova (Amazon) [other] | I bought a 25€ coupon that gives me a 5€ extra with a code in another order, i recieved the code but i cant use it, it says i cant use the code, what can i do? |
| 15 | ShopNova (Amazon) [other] | I Ordered A Gionee s6s Cover From Amazon..Totally Unsatisfied with the Product Given, the Product is Totally Different From what i have Ordered Colour is Different And It is also Not properly Fitting I my Phone.. Never Buy from Amazon 😡 `<URL>` |
| 16 | ShopNova (UPS) [order_status] | The Forest Park GA location habitually takes at least 2 days to deliver my packages, and they often deliver to the post office.. My package has been within 50 miles from my house for 3 days....... |
| 17 | ShopNova (Amazon) [other] | Why bother offering same day Prime delivery in New York when you never deliver on the expected day `<HANDLE>` 🤔 `<URL>` |
| 18 | ShopNova (Amazon) [other] | If this kind of fraud Amazon done in USA, Gov block the company `<HANDLE>` `<HANDLE>` `<HANDLE>` `<HANDLE>` |
| 19 | ShopNova (UPS) [other] | do all #shipments out of Savannah, GA go to Jacksonville, FL first? |
| 20 | ShopNova (Amazon) [other] | worst experience with Amazon,it's been 11 days fraud transaction happen on my card but no proper response from `<HANDLE>` |

Rows 6, 15-17 show where the keyword mapping misses (missed connection, wrong product, late delivery all fell to `other`).

## Real numbers, each with its source

**Contact-reason mix**
| Source | Mix |
|---|---|
| Flipkart CSAT categories mapped to ShopNova labels (company-labelled, all 85,907 contacts; licence to verify) | return_item 40.4%, other 32.2%, late_delivery 9.7%, order_status 8.6%, refund_request 5.3%, damaged_item 3.7% |
| Twitter, ShopNova-like brands, keyword rules (76% accurate on the hand check) | other 65.2%, order_status 14.2%, late_delivery 8.6%, refund_request 4.8%, damaged_item 3.7%, return_item 3.5% |
| Twitter, Atlas-like brands, keyword rules | other 61.4%, booking_status 16.4%, delay_disruption 11.0%, refund_request 4.0%, cancellation 4.0%, rebooking 2.0%, special_assistance 1.3% |
| US Airline tweets, negative reasons (annotators; 9,178 negative tweets) | Customer Service Issue 31.7%, Late Flight 18.1%, Can't Tell 13.0%, Cancelled Flight 9.2%, Lost Luggage 7.9%, Bad Flight 6.3%, Flight Booking Problems 5.8%, Flight Attendant Complaints 5.2%, long lines 1.9%, Damaged Luggage 0.8% |

**Arrivals per hour of day and day of week** (chart: `reports/figures/arrivals_by_hour.png`)
- Twitter first messages (UTC, so a mix of US and UK local times): lowest 05:00 UTC (2.0%), peak 16:00-17:00 UTC
  (6.1-6.2% each). Weekdays: Friday 16.7%, Thursday 15.7%, Wednesday 15.3%, Monday 14.3%, Tuesday 14.2%,
  Sunday 12.4%, Saturday 11.4%.
- Flipkart contacts (local time): almost nothing 01:00-05:00 (0.1-0.5% per hour), plateau 10:00-20:00 (5.5-6.9% per
  hour). Weekdays: Tuesday 16.6%, Thursday 16.1%, Wednesday 15.9%, Monday 14.0%, Sunday 12.7%, Saturday 12.4%,
  Friday 12.3%.
- Medi-Cal call centers: 9.0% of calls arrive after working hours (Jan-Jun 2026, all counties).

**Response times (time to first answer)**
- Twitter, minutes from first customer tweet to first brand reply: ShopNova-like brands median 14.3 (IQR 6.6-35.0,
  90th percentile 275); Atlas-like brands median 10.1 (IQR 3.5-37.6, p90 156).
- Flipkart, minutes from "issue reported" to "issue responded": median 6 (IQR 2-39, p90 432).

**Give-up / abandonment**
- **Real abandonment (call center)**: Medi-Cal county call centers, "Average Abandonment Rate", 180 county-months
  Jan-Jun 2026: median 0.28, IQR 0.20-0.37. **Unit confirmed** by the source data dictionary
  (`average-call-abandonment-rate-data-dictionary.csv` in the portal's "Download all" ZIP): a fraction from 0 to 1,
  "a value of 0.5 representing 50%", computed as calls abandoned by the caller after entering the queue for a live
  agent / calls that entered the queue (after-hours calls, hang-ups before the queue and queued call-backs are not
  counted). So **28% of queued calls**. Domain gap: public benefits,
  long waits (average wait per county-month: median 28.4 min, IQR 9.7-48.1 min, 204 county-months in the wait-time file).
- **Proxy (Twitter)**: share of first customer tweets that got no brand reply in the dataset: ShopNova-like 4.2%,
  Atlas-like 3.7%. This measures *the brand not answering*, not customers giving up.

## Choice

- **Message source: Customer Support on Twitter** (CC BY-NC-SA 4.0, confirmed on the Kaggle page). It is the only
  large real source with first messages, brand replies and later turns for both e-commerce/delivery and travel.
- **Numbers source: Customer Support on Twitter** for arrivals and response times (same licence) and **County
  Medi-Cal call-center data** (CHHS Terms of Use: free use and distribution with attribution) for a real abandonment
  rate. Flipkart is used as a cross-check only (licence to verify).

**Privacy rebuild (2026-10-25).** The real-message data was rebuilt with person-name masking (BLOCKERS.md B16). The
profile above was computed before that; after the rebuild 10 fewer messages pass the English filter (165,737) and the
random 3,000-message samples change, so the profile shares move by at most 1.5 points
(`results/p2_real_numbers_and_profile_after_name_mask.json`). The numbers above are kept because all writer
realism distances were measured against them.
