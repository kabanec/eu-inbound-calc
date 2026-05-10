# Avalara Quoting API — Agent Reference

> **Source:** `Quoting API/AXB - Quoting API - V1-Swagger (3).yaml` (OpenAPI 3.0.2, version `2.0.0`).
> **Audience:** coding agents (Claude Code et al.) building or modifying integrations against
> the Avalara Quoting API. This document is an opinionated, navigable rewrite of the OpenAPI
> spec — it intentionally drops YAML noise, keeps every field name verbatim, and preserves
> enum values, examples, and prose semantics (especially the basket parameter behaviors that
> are not obvious from the schema alone).

The Quoting API is a REST service within Avalara Cross Border that calculates estimated
import duties, VAT/GST, and other applicable cross-border taxes for international shipments.
It applies country-specific tariff schedules, tax rules, de minimis thresholds, and trade
regulations across more than 200 destination countries and territories. The API is
**stateless** and designed for **synchronous, real-time** integration scenarios such as
checkout flows, OMS, and pricing engines. Responses provide item-level and shipment-level
breakdowns suitable for both display and persistence.

---

## Table of Contents

1. [TL;DR for agents](#tldr-for-agents)
2. [Servers / Environments](#servers--environments)
3. [Authentication](#authentication)
4. [Endpoint catalog](#endpoint-catalog)
   - [POST /api/v2/companies/quotes/create](#post-apiv2companiesquotescreate)
   - [POST /api/v2/companies/{companyId}/quotes/create](#post-apiv2companiescompanyidquotescreate)
   - [POST /api/v2/companies/{companyId}/quotes/bulk/create](#post-apiv2companiescompanyidquotesbulkcreate)
   - [POST /api/v3/companies/{companyId}/quotes/bulk/create](#post-apiv3companiescompanyidquotesbulkcreate)
   - [POST /api/v2/companies/{companyId}/globalcompliance](#post-apiv2companiescompanyidglobalcompliance)
   - [POST /api/v2/compliance/tariff-trade-library/search](#post-apiv2compliancetariff-trade-librarysearch)
   - [GET /api/v2/countries](#get-apiv2countries)
5. [Schemas](#schemas)
6. [Common request parameters (`parameters` & `classificationParameters`)](#common-request-parameters-parameters--classificationparameters)
7. [Response: cost lines reference (`costLines[]`)](#response-cost-lines-reference-costlines)
8. [Quote types (`type` / `quoteType`)](#quote-types-type--quotetype)
9. [Examples](#examples)
10. [Error model](#error-model)
11. [Spec ambiguities & notes](#spec-ambiguities--notes)

---

## TL;DR for agents

- For **EU landed-cost (eu-inbound-calc)** use **POST `/api/v2/companies/{companyId}/globalcompliance`**.
  Request body is a [GlobalComplianceRequestModel](#globalcompliancerequestmodel) (a `BulkBasket`
  with `restrictionsCheck`). Response is a [GlobalComplianceResponseModel](#globalcomplianceresponsemodel).
- For a **single-destination quote** use **POST `/api/v2/companies/{companyId}/quotes/create`**
  with a [BasketModel](#basketmodel); response is a [LandedCostModel](#landedcostmodel).
- For **multi-destination duty/tax only** (no compliance restrictions) use the bulk variants
  (`v2` keeps HS codes trimmed to 6 digits; `v3` keeps the full HS10 and adds country-specific HS).
- For **HS-line tariff inspection** (MFN, FTA, IEEPA / Section 122 / Section 232 / Section 301,
  CVD/ADD, restrictions) use **POST `/api/v2/compliance/tariff-trade-library/search`** with an
  [EnhanceProductComplianceRequest](#enhanceproductcompliancerequest); response is an **array**
  of [EnhanceProductComplianceResponse](#enhanceproductcompliancerseponse) snapshots sorted by
  `effectiveDate`.
- **Auth:** HTTP Basic (Client ID = username, License Key = password) **or** Bearer Token, sent
  in the `Authorization` header. **HTTPS only.**
- **Content type:** every endpoint requires `Content-Type: application/json`. Anything else
  returns **415**.
- **gzip:** `globalcompliance` honors `Accept-Encoding: gzip` (response is gzip-encoded with
  `Content-Encoding: gzip`).
- **Critical EU integration knob:** to get administrative/customs-clearance fee lines
  (`CCF` cost lines) at the basket level, send `administrative_fee=true` in the basket-level
  `parameters` array **and** include a `TOTAL_PRICE` parameter (with `unit` = currency) so the
  CCF threshold formulas can be evaluated. See [Common request parameters](#common-request-parameters-parameters--classificationparameters).

---

## Servers / Environments

| Description | URL | When to use |
|---|---|---|
| Quoting **staging** | `https://quoting.xbo.dev.avalara.io` | Development / pre-integration |
| Quoting **sandbox** | `https://quoting-sbx.xbo.avalara.com` | Sandbox account testing |
| Quoting **production** | `https://quoting.xbo.avalara.com` | Live merchant traffic |

All three serve the same paths. Choose based on which Avalara account / tenant your credentials
belong to.

---

## Authentication

Two security schemes are defined; both go on the standard `Authorization` header. **All
requests must be transmitted over HTTPS.**

| Scheme | OpenAPI key | Mechanism | Header example |
|---|---|---|---|
| Basic Auth | `basicAuth` | HTTP Basic — username = **Client ID**, password = **License Key**, Base64-encoded | `Authorization: Basic <base64(clientId:licenseKey)>` |
| Bearer Token | `bearerAuth` | HTTP Bearer — access token issued by Avalara's identity provider; tokens are time-limited and must be refreshed on expiration | `Authorization: Bearer <token>` |

In the spec, every Quoting endpoint declares `security: [- basicAuth: []]`. Bearer Token is
defined in `securitySchemes` but is not attached to the path-level `security` blocks; treat
it as an alternative supported by the platform.

---

## Endpoint catalog

### POST `/api/v2/companies/quotes/create`

**Purpose:** GetQuote without `companyId` in the URL. Calculates estimated import duties,
VAT/GST, and other applicable cross-border taxes for a shipment of one or more items destined
for a **single** destination country. Synchronous; returns item-level and shipment-level
breakdowns. AI-based language detection and HS classification are performed when an HS code
is not provided; the response includes confidence scores.

- **operationId:** `GetQuote`
- **Tag:** GetQuote
- **Auth:** `basicAuth`

**Parameters**

| Name | In | Required | Type | Description |
|---|---|---|---|---|
| `Content-Type` | header | yes | `application/json` ([ContentType](#contenttype)) | Must be `application/json` |

**Request body:** [BasketModel](#basketmodel) (must carry `companyId` in the body since it is not in the URL).

**Responses**

| Status | Body | Meaning |
|---|---|---|
| `200` | [LandedCostModel](#landedcostmodel) | Successful; landed cost returned |
| `400` | [ErrorInfo](#errorinfo) | Bad / malformed JSON |
| `401` | [ErrorInfo](#errorinfo) | Authentication required (`AuthenticationException`, number 30) |
| `415` | [ErrorInfo](#errorinfo) | `Content-Type` header is not `application/json` |
| `422` | [ErrorInfo](#errorinfo) | Validation failure (e.g. `InvalidCountry` with country code `ZZ`, `ModelStateInvalid`) |

---

### POST `/api/v2/companies/{companyId}/quotes/create`

**Purpose:** Same as `GetQuote` above, but with `companyId` carried in the URL path.

- **operationId:** `GetQuoteByCompany`
- **Tag:** GetQuote
- **Auth:** `basicAuth`

**Parameters**

| Name | In | Required | Type | Description |
|---|---|---|---|---|
| `companyId` | path | yes | integer ([companyId](#companyid)) | The ID of the company that owns this item |
| `Content-Type` | header | yes | `application/json` ([ContentType](#contenttype)) | Must be `application/json` |

**Request body:** [BasketModel](#basketmodel).

**Responses**

| Status | Body | Meaning |
|---|---|---|
| `200` | [LandedCostModel](#landedcostmodel) | Successful; landed cost returned |
| `400` | [ErrorInfo](#errorinfo) | Bad / malformed JSON |
| `401` | [ErrorInfo](#errorinfo) | Authentication required |
| `415` | [ErrorInfo](#errorinfo) | `Content-Type` is not `application/json` |
| `422` | [ErrorInfo](#errorinfo) | Validation failure |

---

### POST `/api/v2/companies/{companyId}/quotes/bulk/create`

**Purpose:** GetBulkQuote (V2). Calculates estimated import duties, VAT/GST, and other taxes
for a list of items across **multiple destination countries** in a single request.
Functionally equivalent to `getQuote` for calculation logic; allows multiple destination
contexts in one call. **Per-item results per destination are returned; shipment-level totals
are not.** Each destination is processed independently. AI-based language detection and HS
classification run per item per basket; HS codes are trimmed to 6 digits.

- **operationId:** `GetBulkQuote`
- **Tag:** GetBulkQuote
- **Auth:** `basicAuth`

**Parameters**

| Name | In | Required | Type | Description |
|---|---|---|---|---|
| `companyId` | path | yes | integer ([companyId](#companyid)) | The ID of the company that owns this item |
| `Content-Type` | header | yes | `application/json` ([ContentType](#contenttype)) | Must be `application/json` |

**Request body:** [BulkBasketModel](#bulkbasketmodel). Example: `SampleBulkRequest`.

**Responses**

| Status | Body | Meaning |
|---|---|---|
| `200` | [BulkLandedCostModel](#bulklandedcostmodel) | Successful; per-destination landed cost (`SampleBulkResponse` for an example) |
| `400` | [ErrorInfo](#errorinfo) | Bad JSON request (`ModelStateInvalid` example provided) |
| `401` | [ErrorInfo](#errorinfo) | Authentication required (`AuthenticationException`) |
| `415` | n/a | Unsupported media type (no body schema specified) |
| `422` | [ErrorInfo](#errorinfo) | Validation errors. Documented examples: `field-required` (`ValueRequiredError`, number 5) and `invalid-country` (`InvalidCountry`, country `ZS`, number 125) |

---

### POST `/api/v3/companies/{companyId}/quotes/bulk/create`

**Purpose:** GetBulkQuoteV3 — same calculation logic as the V2 bulk endpoint but with
**enhanced HS classification**:

- Supports HS10 classification across countries.
- **Does not** trim HS codes to 6 digits.
- Uses the HSAC v3 endpoint for multi-country classification.
- Returns country-specific HS codes (HS10 if available, HS6 as fallback).

Each destination is processed independently using applicable tariff schedules, tax rules, and
de minimis thresholds at `transactionDate` (or current date if omitted). Shipment-level
totals are not returned.

- **operationId:** `GetBulkQuoteV3`
- **Tag:** GetBulkQuoteV3
- **Auth:** `basicAuth`

**Parameters**

| Name | In | Required | Type | Description |
|---|---|---|---|---|
| `companyId` | path | yes | integer ([companyId](#companyid)) | The ID of the company that owns this item |
| `Content-Type` | header | yes | `application/json` ([ContentType](#contenttype)) | Must be `application/json` |

**Request body:** [BulkBasketModel](#bulkbasketmodel).

**Responses**

| Status | Body | Meaning |
|---|---|---|
| `200` | [BulkLandedCostModel](#bulklandedcostmodel) | Successful; landed cost with country-specific HS codes |
| `401` | [ErrorInfo](#errorinfo) | Authentication required |
| `404` | [ErrorInfo](#errorinfo) | Quote not found |
| `422` | [ErrorInfo](#errorinfo) | Validation failed |
| `500` | [ErrorInfo](#errorinfo) | Internal server error |

---

### POST `/api/v2/companies/{companyId}/globalcompliance`

**Purpose:** Evaluates a list of items across multiple destination countries and returns
estimated import duties and taxes (same calculation logic as `getBulkQuote`) **plus**
applicable compliance restrictions per destination country. Extends `getBulkQuote` with
regulatory compliance checks; **shipment-level totals are not returned**.

Per-item per-destination response may include restriction type (e.g. `prohibited`,
`restricted`, `conditional`), description of the restriction, regulatory reference or
category, and indicators of whether the product can be imported.

**Compression:** when `Accept-Encoding: gzip` is present, the response is gzip-encoded
(`Content-Encoding: gzip`).

This is the endpoint **eu-inbound-calc** uses today (see `backend/app/services/avalara_client.py`).

- **operationId:** `GlobalCompliance`
- **Tag:** GlobalCompliance
- **Auth:** `basicAuth`

**Parameters**

| Name | In | Required | Type | Description |
|---|---|---|---|---|
| `companyId` | path | yes | integer ([companyId](#companyid)) | The ID of the company that owns this item |
| `Content-Type` | header | yes | `application/json` ([ContentType](#contenttype)) | Must be `application/json` |
| `Accept-Encoding` | header | no | `gzip` | Optional. When present, server returns gzip-compressed response |

**Request body:** [GlobalComplianceRequestModel](#globalcompliancerequestmodel). Example:
`SampleGlobalComplianceRequest` ([see Examples](#examples)).

**Responses**

| Status | Body | Meaning |
|---|---|---|
| `200` | [GlobalComplianceResponseModel](#globalcomplianceresponsemodel) | Successful; landed cost + per-destination compliance results (`SampleGlobalComplianceResponse` for an example) |
| `400` | [ErrorInfo](#errorinfo) | Bad / malformed JSON (`ModelStateInvalid` example) |
| `401` | [ErrorInfo](#errorinfo) | Authentication required (`AuthenticationException`) |
| `415` | n/a | Unsupported media type |
| `422` | [ErrorInfo](#errorinfo) | Validation failure. Documented examples: `field-required` and `invalid-country` |

---

### POST `/api/v2/compliance/tariff-trade-library/search`

**Purpose:** **Recommended EPC entry point.** Returns one or more **time-sliced**
`EnhanceProductComplianceResponse` snapshots — an **array**, sorted by `effectiveDate` —
enriched with MFN, FTA, punitive (IEEPA / Section 122 / Section 232 / Section 301), and
CVD/ADD components for the requested HS line, plus restrictions / PGA flags.

**Future Rates window.** Optional `startDate` / `endDate` (`yyyy-MM-dd`) bound the
transaction window. When omitted, the response contains the snapshot for the current date
only. When provided, the response contains every snapshot whose effective range overlaps the
window — so consumers can show upcoming Section 232 / Section 122 changes.

**`shipmentType`:** `postal` is only valid when **`countryOfImport` is `US`**; otherwise
**422**. `courier` is valid for any supported `countryOfImport`. Any other value returns
**422**.

**Section 232 / Section 122 era awareness.** Snapshots before `2026-02-24` carry country-
specific labels of the form `IEEPA <CC>`; snapshots on/after `2026-02-24` carry `Section 122
<CC>`. Snapshots on/after `2026-04-06` apply Section 232 to the **full customs value** of
matching lines and may include the U.S. 10% / GB 15% / GB 25% reduced rates when metal COO
and composition rules are satisfied (see [Section232Parameters](#section232parameters)).
Match punitive labels by **prefix** (`IEEPA `, `Section 122 `, `SECTION 232 `, `SECTION 301`)
rather than exact equality.

**Note on conditional arrays:** `punitiveRates`, `cvds`, `adds`, and `ftaRates` are only
included when their corresponding boolean flags (`hasPunitiveRate`, `hasCVD`, `hasADD`,
`hasFTARate`) are `true`. When the flags are `false`, these arrays are omitted entirely.

- **operationId:** `TariffTradeLibrarySearch`
- **Tag:** TariffTradeLibrary
- **Auth:** `basicAuth`

**Parameters**

| Name | In | Required | Type | Description |
|---|---|---|---|---|
| `Content-Type` | header | yes | `application/json` ([ContentType](#contenttype)) | Must be `application/json` |

**Request body:** [EnhanceProductComplianceRequest](#enhanceproductcompliancerequest).
Numerous wired examples (`sample-with-section232-*-request`, `sample-with-postal-shipment-request`,
`sample-with-fta-preference-matched-request`, `sample-request`).

**Responses**

| Status | Body | Meaning |
|---|---|---|
| `200` | array of [EnhanceProductComplianceResponse](#enhanceproductcompliancerseponse) | One or more snapshots sorted by `effectiveDate` |
| `400` | [ErrorInfo](#errorinfo) | Bad request — malformed JSON, **or** invalid `section232Parameters` (e.g. total percentages > 100%, negative values, invalid `auto`) |
| `401` | [ErrorInfo](#errorinfo) | Authentication required |
| `415` | n/a | Unsupported media type |
| `422` | [ErrorInfo](#errorinfo) | Validation failure. Documented examples: `field-required`, `invalid-country`, `postal-shipment-non-us-import` (`InvalidValue`) |

Documented `400` examples include:

- `section232-exceeds-100`: `Total material composition cannot exceed 100%. Received total: 120.0% (steel=0.6, aluminum=0.6)`
- `section232-negative-percentage`: `Percentage for 'steel' cannot be negative. Received: -0.3`
- `section232-invalid-auto`: `Invalid auto parameter value: 'TRUCK'. Allowed values are: AUTO, HEAVYVEHICLE, HEAVYVEHICLEPARTS, BUSES`
- `malformed-json`: `Invalid JSON object.` (`ModelStateInvalid`, number 70)

---

### GET `/api/v2/countries`

**Purpose:** Returns the list of countries supported by the Quoting API.

- **operationId:** `GetSupportedCountries`
- **Tag:** SupportedCountries
- **Auth:** none declared (the spec does not attach a `security` block; treat as a public
  metadata endpoint subject to platform policy).

**Parameters:** none.

**Responses**

| Status | Body | Meaning |
|---|---|---|
| `200` | `string[]` (each entry is a 2-character ISO 3166-1 alpha-2 country code; example: `["US", "CA", "GB", "DE", "FR", "CN", "JP", "AU"]`) | Successful |
| `500` | [ErrorInfo](#errorinfo) | Internal server error |

---

## Schemas

Each subsection lists fields with type, required-ness, and the spec's description (preserving
embedded markdown where the spec uses it).

### BasketModelBase

Shared property definitions for all basket-based request models (single-quote, bulk-quote,
and global compliance). This schema contains only properties and **no required constraints**;
each concrete basket model composes this base and declares its own `required` list.

| field | type | required | description |
|---|---|---|---|
| `id` | string (maxLength 200) | no | Client-generated unique identifier for the quote request. Used to correlate the response with the originating request. Example: `QT5654560` |
| `companyId` | integer | no | Identifier of the company for which the quote is executed. Controls configuration and entitlements applied during calculation. Example: `202102` |
| `currency` | string (maxLength 3) | no | ISO-4217 currency code used for monetary inputs and returned amounts. Example: `CAD` |
| `transactionDate` | string (`date`) | no | Date on which the transaction is considered to occur for duty/tax calculation (`YYYY-MM-DD`). Determines applicable tariff schedules, rates, trade measures, de minimis thresholds, and regulatory rules. If not specified, the system uses the current system date (UTC) |
| `shipFrom` | [AddressInfo](#addressinfo) | no | Origin address context used for origin-dependent logic (preferential treatment, punitive tariffs, origin-dependent thresholds) |
| `shipTo` | [AddressInfo](#addressinfo) | no | Destination address. Determines destination-specific tariff/tax rules and regional taxation (region required for US/CA). Required for single-quote requests; optional for bulk-quote requests (each destination has its own `shipTo`) |
| `lines` | array of [BasketLineItemModel](#basketlineitemmodel) | no | List of items to be quoted. Each line includes quantity and product data used for classification and duty/tax calculation |
| `parameters` | array of [ItemParameterModel](#itemparametermodel) | no | Basket-level parameters that apply to the whole quote (shipping, handling, insurance, special flags). When applicable, basket-level monetary parameters may be prorated to lines. **See [Common request parameters](#common-request-parameters-parameters--classificationparameters) for `SPECIAL_CALC`, `ENABLE_COO_PREDICTION`, `administrative_fee`, and Incoterm cost components** |
| `type` | string enum (maxLength 20, readOnly) | no | Pricing strategy. Values: `QUOTE_MINIMUM`, `QUOTE_MAXIMUM`, `QUOTE_AVERAGE`, `QUOTE_MEDIAN`, `QUOTE_ENHANCED10`, `QUOTE_ENHANCEDMEDIAN`. See [Quote types](#quote-types-type--quotetype) |
| `shipmentType` | string enum | no | Triggers the calculation of U.S. customs duties for international postal shipments. Values: `postal_flat`, `postal`, `courier` |
| `sellerCode` | string | no | Identifier of the seller associated with the transaction. Used to apply seller-specific configurations and entitlements during duty and tax calculation. Example: `ABC124` |
| `taxRegistered` | boolean | no | Whether the importer is tax registered in the destination country. If `true`, de minimis thresholds are not applied; if `false` (or omitted), de minimis rules may apply per destination logic |
| `storeMerchandiseTypes` | string[] | no | Merchandise type codes associated with the seller's store. Used to apply merchandise-type-specific calculation rules |
| `disableCalculationSummary` | boolean | no | When `true`, the calculation summary section is omitted from the response. Reduces response size when summary metadata is not required. Default `false` |
| `b2b` | boolean | no | Whether this is a Business-to-Business transaction. When `true`, B2B-specific duty and tax rules may apply (e.g., preferential program eligibility). Default `false` |
| `incoterm` | string enum | no | Incoterm 2020 defining the allocation of logistics costs, risks, and duties between buyer and seller. When provided, the response includes a detailed cost component breakdown (BUYER/SELLER) and aggregated totals (`PAYABLE_LOGISTICS_TOTAL`, `TOTAL_LANDED_PAYABLE`). Values: `EXW`, `FCA`, `FAS`, `FOB`, `CFR`, `CIF`, `CPT`, `CIP`, `DAP`, `DPU`, `DDP` |
| `pricedParty` | string enum | no | Identifies which party (`BUYER` or `SELLER`) is the "priced party" — the party whose total payable cost is being calculated. When `incoterm` is provided, determines which cost components are included in `TOTAL_LANDED_PAYABLE`. Defaults to `SELLER` |

---

### BasketModel

Root request payload for `getQuote`. Defines a single quoting transaction for **one
destination** and a list of line items. Encapsulates destination/origin context, pricing
strategy, item data (including optional explicit HS inputs), and optional parameters that
influence calculation behavior. Only one destination country is supported per basket; all
items are evaluated under the same destination context.

**Composition:** `allOf` → [BasketModelBase](#basketmodelbase) **plus** the following
**required** fields:

| field | required |
|---|---|
| `id` | yes |
| `companyId` | yes |
| `currency` | yes |
| `shipTo` | yes |
| `lines` | yes |
| `type` | yes |

(All other properties are inherited from `BasketModelBase` as optional.)

---

### BulkBasketModel

Root request payload for `getBulkQuote`. Encapsulates all data required to calculate duties
and taxes for a single set of items across **multiple destination countries**. Each item
includes the product data required for classification and tax calculation. **Only one
currency is supported per BulkBasket.**

**Composition:** `allOf` → [BasketModelBase](#basketmodelbase) **plus**:

| field | type | required | description |
|---|---|---|---|
| `id` | string | yes | Inherited from base |
| `companyId` | integer | yes | Inherited from base |
| `currency` | string | yes | Inherited from base |
| `lines` | array | yes | Inherited from base |
| `type` | string enum | yes | Inherited from base |
| `destinations` | array of [BulkDestinations](#bulkdestinations) | **yes** | List of destination countries for which duties, taxes, and (if enabled) compliance checks will be performed. Each destination is processed independently |

---

### GlobalComplianceRequestModel

Request payload for the `globalCompliance` method. Structurally equivalent to a
`BulkBasketModel`. Extends `BulkBasketModel` by introducing a boolean flag that enables or
disables regulatory restriction checks.

**Composition:** `allOf` → [BulkBasketModel](#bulkbasketmodel) **plus**:

| field | type | required | description |
|---|---|---|---|
| `id` | string | yes | Inherited |
| `companyId` | integer | yes | Inherited |
| `currency` | string | yes | Inherited |
| `lines` | array | yes | Inherited |
| `type` | string enum | yes | Inherited |
| `destinations` | array | yes | Inherited |
| `restrictionsCheck` | boolean | **yes** | Enables or disables regulatory restriction checks for the request. Example: `true` |
| `program` | string | no | Program identifier. Example: `PFDE` |

---

### GlobalComplianceResponseModel

Response model returned by the `globalCompliance` method. Contains request metadata,
per-destination compliance results, and landed cost calculations.

| field | type | required | description |
|---|---|---|---|
| `program` | string | no | Program identifier. Example: `PFDE` |
| `b2b` | boolean | **yes** | Whether this is a B2B transaction |
| `id` | string (maxLength 200) | **yes** | Unique identifier of the quote request. Echoed from the request. Example: `QT5654560` |
| `currency` | string (maxLength 3) | **yes** | Currency for the quote response. All cost components are guaranteed in this currency. Echoed from request |
| `shipFrom` | [AddressInfo](#addressinfo) | no | Origin address. Echoed from the request |
| `quoteType` | string enum (maxLength 20, readOnly) | **yes** | Pricing strategy. Echoed. Values: `QUOTE_MINIMUM`, `QUOTE_MAXIMUM`, `QUOTE_AVERAGE`, `QUOTE_MEDIAN`, `QUOTE_ENHANCED10`, `QUOTE_ENHANCEDMEDIAN` |
| `transactionDate` | string (`date`) | no | Transaction date (`yyyy-MM-dd`) |
| `globalCompliance` | array of [GlobalCompliance](#globalcompliance) | **yes** | Per-destination compliance and quote results |
| `errorInfo` | [ErrorInfo](#errorinfo) | no | Error info if applicable |
| `summary` | array of [ItemParameterModel](#itemparametermodel) | no | Basket-level summary parameters |

---

### GlobalCompliance

Per-destination calculation and compliance result in the `globalCompliance` response.

| field | type | required | description |
|---|---|---|---|
| `shipTo` | [AddressInfo](#addressinfo) | no | Destination address |
| `basketRestrictions` | array of [GCRestriction](#gcrestriction) | no | EXPORT, IMPORT, or CARRIER restrictions applicable to items for this destination |
| `quote` | [GCQuote](#gcquote) | no | Landed cost calculation result for this destination |

---

### GCQuote

Landed cost calculation result for a specific destination within a `globalCompliance`
response.

| field | type | required | description |
|---|---|---|---|
| `lines` | array of [LandedCostLineItemModel](#landedcostlineitemmodel) | no | Product-specific costs that contribute to the fully landed cost for the basket |
| `costLines` | array of [CostComponentModel](#costcomponentmodel) | no | List of cost components contributing to the fully landed cost, calculated for each individual item |
| `calculationSummary` | [QuoteCalculationSummary](#quotecalculationsummary) | no | Summary metadata for the quote |
| `errors` | [ErrorInfo](#errorinfo) | no | Errors associated with the destination (`shipTo` address) |

---

### GCRestriction

Restriction results for a specific line item within a `globalCompliance` response.

| field | type | required | description |
|---|---|---|---|
| `lineNumber` | integer | no | The line number or code indicating the line on this basket. Example: `202102` |
| `restrictions` | array of [RestrictionsModel](#restrictionsmodel) | no | Restrictions determined for each individual item |

---

### RestrictionsModel

Represents a restriction (IMPORT, EXPORT, etc.) applicable to an item for a destination.

| field | type | required | description |
|---|---|---|---|
| `type` | string (maxLength 20) | no | Restriction type: `EXPORT`, `IMPORT`, or `CARRIER`. Example: `IMPORT` |
| `regulation` | string (maxLength 20) | no | Restriction regulation: `PROHIBITED`, `RESTRICTED`, `LICENCE`, or `DOCUMENT` |
| `complianceMessage` | string (maxLength 1000) | no | Compliance message describing the restriction |
| `condition` | string (maxLength 1000) | no | If returned, the restriction applies only if the specified condition applies |
| `hsCode` | string (maxLength 20) | no | HS code associated with the restriction |
| `governmentAgency` | string (maxLength 1000) | no | Applicable government agency |
| `pgaCode` | string | no | Partner Government Agency code |
| `exportCode` | string | no | Export control code |
| `programCode` | string | no | Program code associated with the restriction |
| `agencyCode` | string | no | Agency code associated with the restriction |
| `flagNote` | string | no | Flag note providing additional context |
| `ruleTitle` | string | no | Title of the rule or regulation |
| `ruleSummary` | string | no | Summary of the rule or regulation |
| `searchKeyword` | string | no | Search keyword associated with the restriction |
| `legislationTitle` | string | no | Title of the applicable legislation |
| `legislationSummary` | string | no | Summary of the applicable legislation |
| `textLink` | string | no | Text link to the regulation or legislation source |
| `webLink` | string | no | Web URL link to the regulation or legislation source |
| `topic` | string | no | Topic or category of the restriction |

---

### BulkDestinations

Defines a single destination context within a `BulkBasket` request. Each destination
represents a country (and corresponding address) against which duty, tax, and optionally
compliance calculations are executed. When multiple destinations are provided, each is
processed independently.

| field | type | required | description |
|---|---|---|---|
| `shipTo` | [AddressInfo](#addressinfo) | **yes** | Destination address. At minimum, the country code must be provided |
| `parameters` | array of [ItemParameterModel](#itemparametermodel) | no | Destination-specific basket parameters (same flags as `Basket.parameters`: `SPECIAL_CALC`, `ENABLE_COO_PREDICTION`, `administrative_fee`, etc.) |
| `taxRegistered` | boolean | no | Whether the importer is tax registered in this destination. If `true`, de minimis thresholds are not applied. If omitted/`false`, standard de minimis rules may apply |

---

### LandedCostModel

Response model returned by `getQuote` (single destination). Represents the complete landed
cost result.

| field | type | required | description |
|---|---|---|---|
| `id` | string (maxLength 1000) | **yes** | Echoed from `Basket.id`. Example: `QT5654560` |
| `companyId` | integer | **yes** | Echoed from `Basket.companyId`. Example: `202102` |
| `currency` | string (maxLength 3) | **yes** | Echoed from `Basket.currency`. All cost components are in this currency |
| `shipFrom` | [AddressInfo](#addressinfo) | no | Echoed from `Basket.shipFrom` |
| `shipTo` | [AddressInfo](#addressinfo) | no | Echoed from `Basket.shipTo` |
| `lines` | array of [LandedCostLineItemModel](#landedcostlineitemmodel) | **yes** | Item-level landed cost details. Each entry corresponds to a `BasketLineItem` and includes applied HS code, duty and tax cost components, and optional calculation summary |
| `costLines` | array of [CostComponentModel](#costcomponentmodel) | no | **Basket-level cost components.** Aggregated duty and tax for the entire basket plus other country-specific transaction-level charges. When an Incoterm is provided, also includes logistics cost components for each `CostComponentCode` payable by the priced party (each entry has `type` = Incoterm name, `name` = component code, `responsibleParty`, `payableByPricedParty: true`, `status`). **Incoterm cost component names:** `EXPORT_PACKAGING`, `LOADING_CHARGES`, `DELIVERY_NAMED_PLACE`, `EXPORT_CLEARANCE_FEES`, `ORIGIN_TERMINAL_CHARGES`, `LOADING_ON_CARRIAGE`, `INTERNATIONAL_FREIGHT`, `INSURANCE`, `DEST_PORT_TERMINAL_CHARGES`, `DELIVERY_TO_DESTINATION`, `UNLOADING_AT_DESTINATION`, `BROKER_CLEARANCE_DUTIES` |
| `parameters` | array of [ItemParameterModel](#itemparametermodel) | no | Echoed from `Basket.parameters` |
| `type` | string enum (maxLength 20, readOnly) | **yes** | Echoed from `Basket.type` |
| `shipmentType` | string | no | Shipment type used for this quote. Example: `postal_flat` |
| `sellerCode` | string | no | Echoed from request |
| `taxRegistered` | boolean | no | Echoed from `Basket.taxRegistered` |
| `storeMerchandiseTypes` | string[] | no | Store merchandise types |
| `incoterm` | string enum | no | Echoed from `Basket.incoterm`. Same enum values |
| `pricedParty` | string enum (`BUYER`/`SELLER`) | no | Echoed from `Basket.pricedParty` |
| `summary` | array of [ItemParameterModel](#itemparametermodel) | no | Basket-level summary parameters. When Incoterm is provided, includes `PAYABLE_LOGISTICS_TOTAL` (sum of logistics components payable by priced party) and `TOTAL_LANDED_PAYABLE` (total landed cost including goods, logistics, duty/tax payable by priced party) |

---

### BulkLandedCostModel

Top-level response returned by `getBulkQuote`. Encapsulates the full result of a bulk quoting
request: metadata + per-destination landed cost results.

| field | type | required | description |
|---|---|---|---|
| `id` | string (maxLength 200) | **yes** | Echoed from `BulkBasket.id`. Example: `QT5654560` |
| `currency` | string (maxLength 3) | **yes** | ISO-4217 currency for all returned monetary values. Echoed |
| `shipFrom` | [AddressInfo](#addressinfo) | no | Origin address. Echoed |
| `type` | string enum (maxLength 20, readOnly) | **yes** | Pricing strategy. Echoed |
| `quotes` | array of [LandedQuoteModel](#landedquotemodel) | **yes** | Per-destination landed cost results. Each entry corresponds to a destination provided in the request and contains item-level duty, tax, and calculation summaries for that country |
| `transactionDate` | string (`date`) | no | Transaction date (`yyyy-MM-dd`) |
| `summary` | array of [ItemParameterModel](#itemparametermodel) | no | Basket-level summary parameters |

---

### LandedQuoteModel

Calculation result for a single destination within a bulk quoting response. Each
`LandedQuote` corresponds to one destination provided in the request. Destinations are
processed independently; therefore, each `LandedQuote` is self-contained.

| field | type | required | description |
|---|---|---|---|
| `shipTo` | [AddressInfo](#addressinfo) | **yes** | Destination address. Echoed from `Destination.shipTo` |
| `parameters` | array of [ItemParameterModel](#itemparametermodel) | no | Destination-level parameters |
| `lines` | array of [LandedCostLineItemModel](#landedcostlineitemmodel) | no | Item-level landed cost details. Includes applied HS code, duty/tax amounts, classification confidence (if AI was used), language detection summary (if applicable), and calculation summary (if enabled) |
| `costLines` | array of [CostComponentModel](#costcomponentmodel) | no | Transaction-level cost components for this destination |
| `errors` | [ErrorInfo](#errorinfo) | no | Errors associated with this destination. Other destinations in the same bulk request may still return successful results |
| `deminimisFormula` | string | no | De minimis formula applied for this destination |
| `caseAttributes` | array of [ItemParameterModel](#itemparametermodel) | no | Case-level attributes |
| `isAdmin` | boolean | no | Whether admin mode is active |

---

### AddressInfo

Structured postal address used in quoting requests. Used for both origin (`shipFrom`) and
destination (`shipTo`) contexts and directly influences tariff rules, tax determination, de
minimis thresholds, and compliance checks. The `country` field is mandatory; additional
fields may become required by country-specific regulatory or tax rules.

| field | type | required | description |
|---|---|---|---|
| `line1` | string (maxLength 100) | no | Primary street address line |
| `line2` | string (maxLength 100) | no | Secondary street address (apt, suite, unit, building, floor) |
| `line3` | string (maxLength 100) | no | Additional address information |
| `city` | string (maxLength 50) | no | City |
| `region` | string (maxLength 50) | no | State / province / administrative region. Must conform to ISO 3166-2 subdivision standards where applicable. **Required for Canada and the United States** (tax calculation in those countries is region-dependent). Example: `CA` |
| `country` | string (maxLength 2) | **yes** | Two-character ISO 3166-1 alpha-2 country code. Determines applicable tariff schedules, tax framework, de minimis thresholds, and compliance regulations |
| `postalCode` | string (maxLength 11) | no | Postal/ZIP code. May influence calculation in some jurisdictions |
| `latitude` | number (`double`) | no | Geospatial latitude (decimal degrees) |
| `longitude` | number (`double`) | no | Geospatial longitude (decimal degrees) |

---

### BasketLineItemModel

A single product entry within a `Basket` or `BulkBasket`. Each line contains the product-
specific data required for AI classification, duty calculation, tax determination, and (if
enabled) compliance evaluation. Each line item is processed independently within the context
of the destination country.

| field | type | required | description |
|---|---|---|---|
| `lineNumber` | number | **yes** | Unique line identifier within the basket. Used to correlate response with request line. Duplicates within the same basket are not allowed. Example: `15646456` |
| `item` | [ItemModel](#itemmodel) | **yes** | Product details object |
| `quantity` | number | **yes** | Number of units of the product. Combined with declared value or unit price to determine total customs value for the line. Example: `11` |
| `preferenceProgramApplicable` | boolean | no | Whether a preferential trade agreement (FTA) may apply to this item. When `true`, the system evaluates eligibility for preferential duty rates if a valid COO is provided in the item data |
| `classificationParameters` | array of [ItemParameterModel](#itemparametermodel) | no | Additional classification parameters associated with this line item (e.g. `price`, `coo`, `hs_code`). See [Common request parameters](#common-request-parameters-parameters--classificationparameters) |

---

### LandedCostLineItemModel

Landed cost calculation result for a single product line within the `LandedCost` response.
Each entry corresponds to one `BasketLineItem` and provides item-level duty, tax, and
calculation details for the destination country.

| field | type | required | description |
|---|---|---|---|
| `number` | integer | no | Echoed from `BasketLineItem.lineNumber`. Example: `15646456` |
| `item` | [ItemModel](#itemmodel) | no | Echoed from `BasketLineItem.item` |
| `itemCode` | string | no | Unique product identifier. Echoed from `Item.itemCode` |
| `quantity` | integer | no | Quantity used in calculation. Echoed |
| `classificationParameters` | array of [ItemParameterModel](#itemparametermodel) | no | Classification parameters used for this line |
| `parameters` | array of [ItemParameterModel](#itemparametermodel) | no | Line-level parameters |
| `costLines` | array of [CostComponentModel](#costcomponentmodel) | no | List of cost components contributing to the fully landed cost for this specific item. Each component may represent duty (MFN, punitive, additional measures), VAT/GST, or other applicable import taxes |
| `calculationSummary` | [CalculationSummaryModel](#calculationsummarymodel) | no | Detailed calculation metadata. Includes `dutyCalculationSummary`, `taxCalculationSummary`, `summary`, `dutyGranularity`, and AI-related metadata. Returned only when summary output is enabled (`disableCalculationSummary = false`) |
| `hsCode` | string | no | HS code used for duty calculation. Returned only when duty calculation is applicable. Reflects the HS code used to compute the final duty (after pricing strategy has been applied) — not necessarily the most probable classification |
| `exportHsCode` | string | no | Export HS code used for quote calculation |
| `ftas` | array of [FreeTradeAgreement](#freetradeagreement) | no | Free Trade Agreements applied to this line |
| `summary` | array of [ItemParameterModel](#itemparametermodel) | no | Line-level summary parameters |

---

### CalculationSummaryModel

Detailed calculation metadata and breakdown information. Supplements the item-level duty/tax
amounts by exposing the intermediate parameters, formulas, thresholds, and contextual values
used during calculation. Returned when summary output is enabled
(`disableCalculationSummary = false`).

| field | type | required | description |
|---|---|---|---|
| `dutyCalculationSummary` | array of [ItemParameterModel](#itemparametermodel) | no | Parameters used in duty calculation (de minimis evaluation, calculation basis `PRICE`/`CIF`, applied rates, thresholds) |
| `taxCalculationSummary` | array of [ItemParameterModel](#itemparametermodel) | no | Parameters used in VAT/GST calculation (de minimis evaluation, applied tax rates, tax base values) |
| `summary` | array of [ItemParameterModel](#itemparametermodel) | no | High-level monetary components used to derive final duty/tax amounts (destination country, pricing strategy used, HS code). When AI classification is used, includes `CLASSIFICATION_MODEL` (the model used) and `CLASSIFICATION_CONFIDENCE_SCORE`. When COO prediction is enabled (`ENABLE_COO_PREDICTION=true`) and no COO was provided, includes `COO_PREDICTION` (the predicted 2-letter country code) and `COO_PREDICTION_CONFIDENCE_SCORE` (0–1) |
| `cvdCalculationSummary` | array of [ItemParameterModel](#itemparametermodel) | no | Parameters used in CVD (Countervailing Duty) calculation |
| `addCalculationSummary` | array of [ItemParameterModel](#itemparametermodel) | no | Parameters used in ADD (Anti-Dumping Duty) calculation |
| `languageDetectionSummary` | array of [ItemParameterModel](#itemparametermodel) | no | AI-based language detection details (detected ISO 639-1 code, confidence score, source text type, translation flag, fallback logic) |
| `dutyGranularity` | array of [DutyGranularityModel](#dutygranularitymodel) | no | Detailed breakdown by HS code and rate type |

---

### ItemParameterModel

Structured name-value pair used to enrich product data within an `Item`, or for
basket/destination-level flags on `Basket.parameters` / `BulkDestinations.parameters`.
Provides additional attributes that may influence AI classification, duty calculation,
freight allocation, preferential treatment evaluation, or compliance processing. The
interpretation of the parameter depends on the `name` field.

Supported parameter names include: `coo` (Country of Origin), `hs_code` (Harmonized System
code), `price`, `shipping`, `handling`, `insurance`, `weight`, `height`, `length`, `width`,
`volume`. Basket-level flags include `SPECIAL_CALC`, `ENABLE_COO_PREDICTION`,
`administrative_fee` (see [Common request parameters](#common-request-parameters-parameters--classificationparameters)).

| field | type | required | description |
|---|---|---|---|
| `name` | string (maxLength 255) | **yes** | Parameter identifier. Defines the semantic meaning and how the system processes the value. Supported names include regulatory/classification (`coo`, `hs_code`), monetary (`price`, `shipping`, `handling`, `insurance`), physical/dimensional (`weight`, `height`, `length`, `width`, `volume`), and basket-level flags (`administrative_fee`, etc.) |
| `value` | string (maxLength 1000) | **yes** | Parameter value as a string. Numeric parameters must be valid numerics. Country codes must be ISO 3166-1 alpha-2. HS codes must be valid HS structure |
| `unit` | string (maxLength 255) | no | Unit of measure. Monetary: ISO-4217 currency (e.g. `USD`, `EUR`). Weight: e.g. `kg`, `lb`, `pound`. Dimensions: `in`, `cm`, `m`. Volume: `cubicinch`, `litre`. Parameters like `coo` and `hs_code` do not require a unit |

---

### ItemModel

Product-level information required for classification, duty calculation, tax determination,
and compliance evaluation.

| field | type | required | description |
|---|---|---|---|
| `itemCode` | string (maxLength 255) | no | Unique product identifier (typically SKU). Must be unique within the request. Example: `ABC` |
| `description` | string (maxLength 1000) | no | Short product description or title. Primary input for AI classification |
| `summary` | string (maxLength 4000) | no | Extended product description |
| `itemGroup` | string (maxLength 4000) | **yes** | Product category breadcrumb path (full hierarchy). Categories separated by `>`. Multiple paths are supported. Used by the AI classifier to narrow possible HS code matches. Example: `Clothing > Women > Formal` |
| `classificationParameters` | array of [ItemParameterModel](#itemparametermodel) | no | Additional structured parameters. **`parameters` and `classificationParameters` are interchangeable** — any supported parameter can go in either list and the system processes them equivalently |
| `parameters` | array of [ItemParameterModel](#itemparametermodel) | no | Additional structured parameters |
| `classifications` | array of [ClassificationBulkModel](#classificationbulkmodel) | no | Predefined classifications (pre-assigned HS codes per country). If valid, may bypass AI classification. **Only used in case of Bulk quote API** |
| `hs_code` | string | no | HS code shortcut for the item |

---

### ClassificationBulkModel

Explicitly assigned product classification. Allows the client to provide a predefined HS code
for a specific country, bypassing AI-based classification for that context. When valid, duty
and tax calculations are performed exclusively using the supplied HS code.

| field | type | required | description |
|---|---|---|---|
| `hscode` | string | **yes** | The Tariff Code or HS code assigned to the product for the specified country |
| `country` | string (maxLength 2) | **yes** | Two-character ISO 3166-1 alpha-2 country code. A separate `Classification` object must be provided for each country if different HS codes apply. Example: `US` |

---

### CostComponentModel

A single calculated monetary charge contributing to the landed cost result. Provides a
structured financial breakdown of duties, taxes, and other amounts. Each `CostComponent`
corresponds to one applied charge and may optionally specify the cost base on which it was
calculated.

When an Incoterm is provided, additional `CostComponent` entries are included for logistics
cost elements. For these entries: `type` is the Incoterm name (e.g. `CIF`, `FOB`), `name` is
the logistics cost code (e.g. `INTERNATIONAL_FREIGHT`, `INSURANCE`), and the Incoterm-specific
fields (`responsibleParty`, `payableByPricedParty`, `status`) are populated.

| field | type | required | description |
|---|---|---|---|
| `type` | string (maxLength 50) | no | Categorizes the cost component. For duty/tax: `DUTY` or `TAX`. For Incoterm logistics components: the Incoterm name (`CIF`, `FOB`, `DDP`). Other observed values include `CCF` (administrative/customs clearance fee — see [cost lines reference](#response-cost-lines-reference-costlines)) |
| `name` | string (maxLength 255) | no | Human-readable label. For duty/tax: e.g. `Minimum Duty`, `VAT`. For Incoterm logistics: the `CostComponentCode` (`EXPORT_PACKAGING`, `INTERNATIONAL_FREIGHT`, `INSURANCE`, `BROKER_CLEARANCE_DUTIES`, etc.) |
| `value` | number | no | Monetary amount. May be `0.00` when evaluated but not applicable (e.g. tax-exempt). Precision may exceed two decimal places depending on internal rounding |
| `currency` | string (maxLength 3) | no | ISO-4217 currency code |
| `rate` | number | no | Rate applied to calculate this component. Expressed as a percentage or defined unit rate. May represent ad valorem or other rate types depending on the country/tariff. Example: `0.13` |
| `target` | string | no | Base component to which the charge was applied. Common values: `product` (charge on product value), `shipping`, `duty` (tax on previously computed duty), `handling`, `insurance` |
| `responsibleParty` | string enum (`BUYER`/`SELLER`) | no | Party responsible for this cost component as determined by the Incoterm. Present only when an Incoterm is specified |
| `payableByPricedParty` | boolean | no | Whether this cost component is payable by the priced party. Present only when an Incoterm is specified |
| `status` | string enum (`PROVIDED`/`MISSING`) | no | Whether the cost component value was provided in the request or is missing. Present only for Incoterm logistics cost components |

---

### DutyGranularityModel

`DutyGranularity` is an array of duty component records that explains exactly which duty
layers were applied for a given destination. Each element represents one duty
rule/component used in the calculation (e.g. MFN/base duty, preferential duty,
punitive/retaliatory measures, chapter-99 add-ons, special programs). The set of elements is
dynamic and depends on the final HS code, country of destination, and country of
manufacture/origin.

| field | type | required | description |
|---|---|---|---|
| `description` | string | no | Human-readable description. Example: `Most Favored Nation Duty` |
| `rateLabel` | string | no | Short label/name as presented by the tariff source (e.g. `MFN Rate`, `SECTION 301`) |
| `hsCode` | string | no | HS/tariff code associated with this specific duty component. May be the primary HS10 used for the item, or a supplemental code (e.g. Chapter 99) that adds an additional duty layer |
| `rate` | string | no | Nominal duty rate. Typically expressed as a decimal fraction (e.g. `0.25` for 25%) |
| `effectiveRate` | string | no | Effective duty rate after applying rule logic, normalization, or transformations. Returned only when it differs from or supplements `rate` |
| `calculationMethod` | string | no | How this component contributes. Examples: `ADDITIVE` (added on top), `COMPOUNDED` (calculated on top of each other), `OVERRIDE` (one duty overrides others) |
| `applicability` | string | no | Which duty regimes this component can apply to (`MFN`, `PREFERRED`, or combinations like `MFN,PREFERRED`) |
| `type` | string | no | Categorizes the component. Common: `MFN`, `PUNITIVE` (retaliatory, safeguard, IEEPA, etc.) |
| `appliesOnDeMinimis` | boolean | no | Whether this component is still applied when de minimis would otherwise exempt duty |
| `rateType` | string enum (`AD_VALOREM`/`PER_UNIT`) | no | How the duty is calculated. `AD_VALOREM` = percentage applied to a value base |
| `unit` | string | no | Unit of `rate`/`effectiveRate` (e.g. `PERCENTAGE`) |
| `value` | number | no | Computed monetary amount for this component, in `currency` |
| `currency` | string | no | ISO-4217 currency code |

---

### FreeTradeAgreement

Free Trade Agreement applied to a line item.

| field | type | required | description |
|---|---|---|---|
| `costLine` | [CostComponentModel](#costcomponentmodel) | no | The cost line representing the FTA application |
| `dutyCalculationSummary` | array of [ItemParameterModel](#itemparametermodel) | no | Duty calculation summary for the FTA |

---

### QuoteCalculationSummary

Calculation summary for a global compliance quote.

| field | type | required | description |
|---|---|---|---|
| `calculationBasis` | string | no | Basis for duty calculation (e.g. `CIF`, `FOB`). Example: `CIF` |

---

### ReadyModel

Readiness check response.

| field | type | required | description |
|---|---|---|---|
| `Service` | string | no | Service name. Example: `QuoteAPI` |
| `Version` | string | no | Service version |
| `Ready` | boolean | no | Whether the service is ready to accept requests. Example: `true` |

---

### InfoModel

Service information response.

| field | type | required | description |
|---|---|---|---|
| `Service` | string | no | Service name. Example: `QuoteAPI` |
| `Version` | string | no | Service version |
| `Accounts` | string[] | no | Configured account IDs |
| `Cluster` | string | no | Cluster name |
| `Git Branch` | string | no | Git branch of the deployed build |
| `Short Commit Id` | string | no | Short git commit hash |
| `Cache Version` | string | no | Current cache version |
| `Env` | string | no | Application environment |
| `Hostname` | string | no | Hostname of the running instance |

---

### PunitiveRate

A punitive duty rate component on the EPC `duty.punitiveRates[]` array.

| field | type | required | description |
|---|---|---|---|
| `rate` | [Rate](#rate) | no | Numeric rate / effective rate / uom / currency |
| `stackable` | boolean | no | Whether this punitive rate should be applied **on top of** all other duty components (MFN, FTA). Example: `true` |
| `taxOnTax` | boolean | no | Whether the punitive rate is **compounded**, i.e. calculated as `rate + surchargeRate + (rate * surchargeRate)`. Example: `true` |
| `appliesUnderDeminimis` | boolean | no | Whether the rate applies under de minimis thresholds. Example: `true` |
| `hsCode99` | string | no | The Chapter 99 HS code associated with this punitive duty. Example: `9903.88.03` |
| `rateLabel` | string | no | Human-readable family + variant. **Match by prefix / category, not by exact equality** — labels evolve with cache vintage and regime cutovers. Country-specific punitive (non-stackable): `IEEPA <CC>` (pre-2026-02-24); `Section 122 <CC>` (on/after 2026-02-24, suppressed when Section 232 covers full customs value). Stackable IEEPA: `IEEPA FENTANYL`, `IEEPA ENERGY`, `IEEPA POTASH`, `IEEPA RECIPROCAL`. Section 232 metals + auto: `SECTION 232 STEEL`, `SECTION 232 ALUMINUM`, `SECTION 232 COPPER`, `SECTION 232 TIMBER_LUMBER`, `SECTION 232 AUTO`, `SECTION 232 HEAVYVEHICLE`, `SECTION 232 HEAVY VEHICLES`, `SECTION 232 HEAVYVEHICLEPARTS`, `SECTION 232 BUSES`, `SECTION 232 PARTS`, etc. Section 301: `SECTION 301`. Recommended consumer matching: `startsWith("IEEPA ")` (excluding stackable keywords) → country-specific IEEPA; `startsWith("Section 122 ")` → country-specific Section 122; `startsWith("SECTION 232 ")` → metals or auto/vehicle; `equals("SECTION 301")` → Section 301 |
| `description` | string | no | Detailed description. Example: `Chapter 99 Code 9903.02.03 - Reciprocal Tariff for CN` |
| `applicability` | string | no | Which duty types this applies to (`MFN`, `PREFERRED`, or both). Example: `MFN,PREFERRED` |
| `calculationMethod` | string | no | Method used (`ADDITIVE`, `COMPOUNDED`, `OVERRIDE`) |
| `notes` | string | no | Free-form, human-readable explanation of the `effectiveRate`. **Not stable** — useful for sales demos and audit logs but **do not parse**. Sample patterns: April 2026 full-value, April 2026 reduced rate, suppression, auto-filter mismatch, mismatched material rotation |

---

### Section232Parameters

Optional Section 232 inputs that drive metal-content and auto/vehicle filtering. Used on
`EnhanceProductComplianceRequest.section232Parameters`.

**Material map (free-form keys).** Each non-`auto` property is a Section 232 material
(`steel`, `aluminum`, `copper`, …) whose value is a [Section232MaterialConfig](#section232materialconfig).

**Section 232 outcome on a Section 232-eligible HS — the two paths:**

- **Field omitted entirely.** No `section232Parameters` on the request: Section 232 stays in
  scope at the **full** statutory rate; `Section 122 <CC>` is **suppressed**.
- **All `percentage` values = 0 (zero-metal exemption).** On **non-primary-metal** HS chapters
  Section 232 is **exempt** (`effectiveRate: "0.0000"`) and `Section 122 <CC>` (or pre-cutover
  `IEEPA <CC>`) applies at its full statutory rate. On **primary-metal chapters
  (72 / 73 / 74 / 76)** Section 232 still applies even when every declared `percentage` is 0.

**April 6, 2026 regime (current):**

- Matched Section 232 metals or auto/vehicle rates apply to the **full customs value** of the
  line. The `percentage` no longer scales the duty.
- When several Section 232 rates overlap, **only the single highest** is applied; the rest
  return `effectiveRate: "0.0000"` (still listed for transparency).
- **Reduced rates (Rules 10/11/12)** require **all** declared metals to share a uniform `coo`
  and total **≥ 95%** composition:
  - `coo: US` + HS in U.S. reduced-rate list → **10%**
  - `coo: GB` + HS in GB Annex I-A list → **25%**
  - `coo: GB` + HS in GB Annex I-B list → **15%**
  - Otherwise the **full statutory** Section 232 rate applies. There is no automatic US-origin
    exemption — `coo: US` at < 95% pays full rate.
- Country-specific punitives (`IEEPA <CC>` / `Section 122 <CC>`) are non-stackable and are
  **suppressed** when Section 232 covers full value; stackable IEEPA (`IEEPA FENTANYL` /
  `IEEPA ENERGY` / `IEEPA POTASH`) and `SECTION 301` continue to apply on top.

**Auto/Vehicle tier priority.** The HS may match more than one Section 232 auto rule. The
cache returns them in tier order:

- **Tier 1:** `AUTOMOBILES`, automobile `PARTS`.
- **Tier 2:** `HEAVY-DUTY VEHICLES`, their `PARTS`, and `BUSES`.

The optional `auto` filter keeps only the requested tier's `effectiveRate` non-zero;
non-matching auto categories return `effectiveRate: "0.0000"`.

**Validation rules:**

- Sum of all material `percentage` values **must be ≤ 1.0** (100%); 400 otherwise.
- Individual `percentage` values must be **between 0.0 and 1.0**; 400 otherwise.
- `auto` must be one of the enum values below (case-insensitive); 400 otherwise.

| field | type | required | description |
|---|---|---|---|
| `auto` | string enum | no | Filter for Section 232 Auto/Vehicle category. Allowed: `AUTO`, `HEAVYVEHICLE`, `HEAVYVEHICLEPARTS`, `BUSES`. When specified, only the matching auto category gets `effectiveRate` calculated |
| _(arbitrary key)_ | [Section232MaterialConfig](#section232materialconfig) | no | Per-material composition. Keys like `steel`, `aluminum`, `copper`. Other keys are accepted and rotated into IEEPA / Section 122 / MFN if the HS does not subject them to Section 232 (`additionalProperties` schema) |

---

### Section232MaterialConfig

Country of origin and composition share for a single Section 232 material.

| field | type | required | description |
|---|---|---|---|
| `percentage` | number (`decimal`, min 0, max 1) | no | Share of the line's customs value composed of this material (0.0–1.0; e.g. `0.3` = 30%). Sum of all materials must be ≤ 1.0 (100%). Under the April 6, 2026 regime the `percentage` no longer scales the Section 232 duty (which applies to full customs value), but it still drives (a) the ≥ 95% threshold for U.S./GB reduced rates and (b) the zero-metal exemption on non-primary-metal HS chapters |
| `coo` | string (maxLength 2) | no | Two-character ISO 3166-1 alpha-2 country of origin **for this material** (can differ from the line's `countryOfManufacture` and the request's `countryOfOrigin`). Drives the April 2026 reduced-rate matrix (`US` / `GB` reduced rates as described in `Section232Parameters`). If mixed, no reduced rate applies. If `coo` is omitted, the resolver falls back to the request's `countryOfOrigin` / `countryOfManufacture` for that material |

---

### companyId

| field | type | description |
|---|---|---|
| `companyId` | integer | The ID of the company that owns this item. Example: `3402` |

---

### ContentType

| field | type | description |
|---|---|---|
| `ContentType` | string | Content type must always be `application/json`. Example: `application/json` |

---

### ErrorInfo

Information about the error that occurred.

| field | type | required | description |
|---|---|---|---|
| `code` | string (readOnly) | no | Name of the error. Refer to Error Codes for accepted values |
| `message` | string (readOnly) | no | Short one-line message summarizing what went wrong |
| `target` | string enum (readOnly) | no | What object or service caused the error. Values: `Unknown`, `HttpRequest`, `HttpRequestHeaders`, `IncorrectData`. Example: `HttpRequest` |
| `details` | array of [ErrorDetail](#errordetail) (readOnly) | no | Detailed error messages |

---

### ErrorDetail

Detailed error message object.

| field | type | required | description |
|---|---|---|---|
| `code` | string (readOnly) | no | Name of the error. Refer to Error Codes |
| `number` | integer (readOnly) | no | Unique ID number referring to this error or message |
| `message` | string (readOnly) | no | Concise summary, suitable for display in the caption of an alert box |
| `description` | string (readOnly) | no | More detailed description, suitable for display in the contents area of an alert box |
| `helpLink` | string (readOnly) | no | URL to help for this message |
| `refersTo` | string (readOnly) | no | Item the message refers to (used to indicate a missing or incorrect value) |
| `severity` | string enum (readOnly) | no | Severity. Values: `Success`, `Warning`, `Error`, `Exception` |

---

### EnhanceProductComplianceRequest

Request for `/api/v2/compliance/tariff-trade-library/search`.

| field | type | required | description |
|---|---|---|---|
| `id` | string (maxLength 200) | **yes** | Unique ID for the EPC request. Example: `QT5654560` |
| `countryOfExport` | string (maxLength 2) | **yes** | ISO 3166-1 alpha-2. Example: `US` |
| `countryOfImport` | string (maxLength 2) | **yes** | ISO 3166-1 alpha-2. **When `shipmentType` is `postal`, this MUST be `US`** |
| `countryOfManufacture` | string (maxLength 2) | no | ISO 3166-1 alpha-2 |
| `hscode` | string | **yes** | Country-specific HS code value |
| `manufacturerName` | string (maxLength 1000) | no | Name of the manufacturing company. Example: `Taiwan Semiconductor Manufacturing Co. (TSMC)` |
| `productName` | string (maxLength 1000) | no | Name of the product. Example: `iPhone 16 Pro Max` |
| `shipmentType` | string enum (`postal`/`courier`) | no | **`postal`** (case-insensitive; whitespace ignored) requests U.S. inbound postal-style duty (punitive-only IEEPA / Section 122). **`courier`** selects the standard EPC duty path (MFN, FTAs, punitives, CVD/ADD) — same as omitting `shipmentType`. **Validation:** if `postal`, `countryOfImport` must be `US` (otherwise 422 `InvalidValue`). Legacy `postal_flat` is rejected with 422 |
| `preferenceProgramApplicable` | boolean | no | When **true**, top-level `effectiveRate` is **only** the selected FTA ad valorem fraction (minimum FTA percentage on duty, or the line matching `ftaName`). The duty response still includes MFN, FTAs, punitives, CVD/ADD for display; they are **not** summed into `effectiveRate`. Ignored for U.S. inbound `postal`. When false/omitted, `effectiveRate` is the full MFN + punitive + CVD/ADD stack. **Without** this flag, `ftaName` is ignored |
| `ftaName` | string (maxLength 200) | no | Optional preferential program / FTA name (e.g. `gsp`). **Only** applies when `preferenceProgramApplicable` is `true`. If set, `effectiveRate` uses that named FTA's ad valorem percentage when the agreement is in the FTA set for the line. If not found, 422 `InvalidValue`. Case-insensitive match against returned FTA names |
| `startDate` | string (`date`, pattern `^\d{4}-\d{2}-\d{2}$`) | no | Optional lower bound of the window. **Must** be `yyyy-MM-dd` or 422 |
| `endDate` | string (`date`, pattern `^\d{4}-\d{2}-\d{2}$`) | no | Optional upper bound of the window. **Must** be `yyyy-MM-dd` or 422 |
| `section232Parameters` | [Section232Parameters](#section232parameters) | no | Section 232 inputs (material map + `auto` filter). See schema for full semantics |

---

### EnhanceProductComplianceResponse

A single time-sliced snapshot. The endpoint returns an **array** of these.

| field | type | required | description |
|---|---|---|---|
| `id` | string (maxLength 1000) | no | Unique ID for the quote. Example: `QT5654560` |
| `countryOfExport` | string (maxLength 2) | no | ISO 3166-1 alpha-2 |
| `countryOfImport` | string (maxLength 2) | no | ISO 3166-1 alpha-2 |
| `countryOfManufacture` | string (maxLength 2) | no | ISO 3166-1 alpha-2 |
| `hscode` | string (maxLength 20) | no | Country-specific HS code |
| `manufacturerName` | string (maxLength 1000) | no | |
| `productName` | string (maxLength 1000) | no | |
| `duty` | [Duty](#duty) | no | Duty rates breakdown |
| `hasCVD` | boolean | no | Whether the request has CVD rates |
| `cvds` | array of [CvdAdd](#cvdadd) | no | CVD rates. **Only present when `hasCVD` is `true`** |
| `hasADD` | boolean | no | Whether the request has ADD rates |
| `adds` | array of [CvdAdd](#cvdadd) | no | ADD rates. **Only present when `hasADD` is `true`** |
| `hasRestrictions` | boolean | no | Whether the request has restrictions for `countryOfImport` |
| `hasPGA` | boolean | no | Whether the request has PGA restrictions for `countryOfImport` |
| `restrictions` | array of [RestrictionsModel](#restrictionsmodel) | no | List of restrictions |
| `effectiveDate` | string (`date`) | no | Date when this duty snapshot takes effect |
| `effectiveRate` | number | no | **Default (non-postal, no preference request):** total duty for this snapshot as a decimal fraction (e.g. `0.15` = 15%). MFN base + punitive + (when `hasCVD`/`hasADD` and loaded) CVD/ADD percentage rates per the usual EPC rules. **`preferenceProgramApplicable: true` (non-postal):** `effectiveRate` is **only** the FTA percentage (minimum among applicable percentage FTAs, or the rate for `ftaName` when matched; `0` if no percentage FTAs and no `ftaName`). MFN, punitives, CVD/ADD appear on the `duty` object but are **not** included. **U.S. inbound `postal` (any date):** no MFN, FTA, or CVD/ADD; the duty object carries punitives only (IEEPA / Section 122). `effectiveRate` is the decimal fraction of punitive ad valorem rates only; preference fields are ignored |

---

### Duty

| field | type | required | description |
|---|---|---|---|
| `calculationBasis` | string | no | Basis for duty calculation (e.g. `PRICE`, `QUANTITY`, `CIF`). Example: `PRICE` |
| `mfn` | [Rate](#rate) | no | Most-favored-nation rate |
| `hasPunitiveRate` | boolean | no | Whether punitive rates apply |
| `punitiveRates` | array of [PunitiveRate](#punitiverate) | no | Punitive rates. **Only present when `hasPunitiveRate` is `true`** |
| `hasFTARate` | boolean | no | Whether FTA rates apply |
| `ftaRates` | array of [FreeTradeAgreementRate](#freetradeagreementrate) | no | FTA rates. **Only present when `hasFTARate` is `true`** |

---

### Rate

| field | type | required | description |
|---|---|---|---|
| `rate` | string | no | Most-favored-nation rate value. Example: `0.048` |
| `uom` | string | no | Unit of measurement (e.g. `percentage`, `kilogram`) |
| `currency` | string | no | Currency of the rate, if applicable. Example: `USD` |
| `effectiveRate` | string | no | Optional effective rate value when applicable. Example: `0.052` |

---

### FreeTradeAgreementRate

| field | type | required | description |
|---|---|---|---|
| `ftaName` | string | no | FTA name. Example: `India-Australia Economic Cooperation and Trade Agreement (IndAus ECTA)` |
| `ftaRate` | [Rate](#rate) | no | The FTA rate |

---

### CvdAdd

| field | type | required | description |
|---|---|---|---|
| `productName` | string | no | The product that needs to ship. Example: `iPhone 16 Pro Max` |
| `manufacturerName` | string | no | Manufacturer name |
| `rate` | [Rate](#rate) | no | The CVD/ADD rate |
| `notes` | string | no | Notes. Example: `All producers/exporters from China` |

---

### SampleBulkResponse

OpenAPI `examples` entry for the bulk quoting response. Used by `getBulkQuote` 200 response.
A representative example is reproduced in the [Examples](#examples) section.

### SampleBulkRequest

OpenAPI `examples` entry for the bulk quoting request. Used by `getBulkQuote` request body.
A representative example is reproduced in the [Examples](#examples) section.

### SampleGlobalComplianceRequest

OpenAPI `examples` entry for the `globalCompliance` request body. See
[Examples](#examples).

### SampleGlobalComplianceResponse

OpenAPI `examples` entry for the `globalCompliance` 200 response. See
[Examples](#examples).

---

## Common request parameters (`parameters` & `classificationParameters`)

The Quoting API uses two **interchangeable** flat name-value lists to enrich a quote:

- **`Basket.parameters`** (or `BulkDestinations.parameters`) — basket/destination-level
  flags and monetary inputs for the whole quote.
- **`BasketLineItem.classificationParameters`** (and `Item.classificationParameters` /
  `Item.parameters`) — line/item-level inputs for classification, calculation, and
  preferences. From the spec: "**parameters and classificationParameters are interchangeable.
  Any supported parameter can be provided in either list, and the system processes them
  equivalently.**"

Each entry is an [ItemParameterModel](#itemparametermodel) with `name`, `value`, and an
optional `unit`.

### Basket-level flags (on `Basket.parameters` / `BulkDestinations.parameters`)

| name | semantic | accepted values / unit | notes |
|---|---|---|---|
| `SHIPPING` | Shipping cost for the quote | numeric `value`; `unit` = ISO-4217 currency | Example: `{name: SHIPPING, value: '20.01', unit: 'USD'}` |
| `HANDLING` | Handling cost | numeric `value`; `unit` = ISO-4217 currency | |
| `INSURANCE` | Insurance cost | numeric `value`; `unit` = ISO-4217 currency | |
| `SPECIAL_CALC` | Special calculation flag | `TAX_EXEMPT`, `TAX_ONLY`, `DUTY_ONLY`, `TAX_DUTY_INCLUDED`, `DUTY_ONLY_NO_DEMINIMIS`, `PRODUCT_TAX_INCLUDED`, `PRODUCT_SHIPPING_TAX_INCLUDED`, `DEFAULT` | Drives duty/tax inclusion behavior |
| `ENABLE_COO_PREDICTION` | Enables AI-based COO prediction via HSAC for products without a COO | `'true'` / `'false'` | When `true`, the response `calculationSummary.summary` includes `COO_PREDICTION` (predicted 2-letter country code) and `COO_PREDICTION_CONFIDENCE_SCORE` (0–1) for each line where prediction was applied |
| **`administrative_fee`** | **Basket-level flag.** When `true` or `1`, the quote may include eligible **EU inbound administrative import / customs clearance fee lines** (`CCF` cost lines from reference data, e.g. destination-specific basket fees) where configured. **Parameter name matching is case-insensitive** (e.g. `administrative_fee`, `ADMINISTRATIVE_FEE`). Omit or set to `false` when these fees must not be applied. The basket should include `TOTAL_PRICE` (and currency) so thresholds in reference formulas can be evaluated | `'true'` / `'false'` / `'1'` | **CRITICAL for CCF basket cost lines.** See [cost lines reference](#response-cost-lines-reference-costlines). Without `administrative_fee=true`, no `CCF` cost line appears at the basket level |
| **`TOTAL_PRICE`** | Basket-level monetary input used to evaluate CCF threshold formulas | numeric `value`; `unit` = ISO-4217 currency | **Companion required when `administrative_fee=true`** — the spec calls this out explicitly as a prerequisite for `CCF` evaluation |

#### Incoterm cost component parameters

When `incoterm` is provided on the basket, the following parameter names are recognized as
logistics cost inputs and used in the Incoterm landed cost calculation. Each should have a
numeric `value` and a currency `unit`. Components not provided default to `0` and are
returned with `status: MISSING` in the response `costLines`:

`EXPORT_PACKAGING`, `LOADING_CHARGES`, `DELIVERY_NAMED_PLACE`, `EXPORT_CLEARANCE_FEES`,
`ORIGIN_TERMINAL_CHARGES`, `LOADING_ON_CARRIAGE`, `INTERNATIONAL_FREIGHT`, `INSURANCE`,
`DEST_PORT_TERMINAL_CHARGES`, `DELIVERY_TO_DESTINATION`, `UNLOADING_AT_DESTINATION`,
`BROKER_CLEARANCE_DUTIES`.

Example basket-level `parameters` block from the spec:

```json
[
  {"name": "SHIPPING",              "value": "20.01", "unit": "USD"},
  {"name": "HANDLING",              "value": "20.01", "unit": "USD"},
  {"name": "INSURANCE",             "value": "20.01", "unit": "USD"},
  {"name": "SPECIAL_CALC",          "value": "DEFAULT"},
  {"name": "ENABLE_COO_PREDICTION", "value": "true"},
  {"name": "administrative_fee",    "value": "true"},
  {"name": "INTERNATIONAL_FREIGHT", "value": "50.00", "unit": "USD"},
  {"name": "EXPORT_PACKAGING",      "value": "15.00", "unit": "USD"}
]
```

### Line/item-level parameters (on `BasketLineItem.classificationParameters` / `Item.classificationParameters` / `Item.parameters`)

| name | semantic | accepted values / unit | notes |
|---|---|---|---|
| `coo` | Country of Origin | ISO 3166-1 alpha-2 (`unit` empty) | Used for FTA / punitive / CVD/ADD evaluation. Predicted by HSAC if `ENABLE_COO_PREDICTION=true` and not provided |
| `hs_code` | Pre-assigned HS code for the item | HS structure | If valid, may bypass AI classification |
| `price` | Per-line declared price | numeric `value`; `unit` = ISO-4217 currency | Combined with `quantity` to derive total customs value |
| `shipping`, `handling`, `insurance` | Per-line monetary parameters | numeric `value`; `unit` = ISO-4217 currency | |
| `weight` | Item weight | numeric; `unit` = `kg`, `lb`, `pound`, etc. | |
| `height`, `length`, `width` | Item dimensions | numeric; `unit` = `in`, `cm`, `m` | |
| `volume` | Item volume | numeric; `unit` = `cubicinch`, `litre` | |
| `preferential_program` | Optional preferential program identifier on a line | string | Seen in `SampleGlobalComplianceRequest` (e.g. `PFDE`) |

### Item-level booleans (on `BasketLineItemModel`)

| field | type | semantic |
|---|---|---|
| `preferenceProgramApplicable` | boolean | When `true`, the system evaluates eligibility for preferential duty rates if a valid COO is provided |

### Top-level toggles relevant to parameter behavior

| field | scope | semantic |
|---|---|---|
| `b2b` | basket / response | When `true`, B2B-specific duty/tax rules may apply. Default `false` |
| `taxRegistered` | basket / destination | When `true`, de minimis thresholds are not applied for that destination |
| `ftaName` | EPC request | Names a preferential program / FTA. Only honored when `preferenceProgramApplicable: true` |

---

## Response: cost lines reference (`costLines[]`)

`costLines[]` (an array of [CostComponentModel](#costcomponentmodel)) appears in two places
in quote responses, with subtly different semantics:

### 1. Line-level: `LandedCostLineItemModel.costLines[]`

Per-item cost components contributing to the fully landed cost for **that specific item**.
Each component may represent a duty layer (MFN, punitive, additional measures), VAT/GST, or
other applicable import taxes. Observed `type` values in line-level `costLines`:

| `type` | `name` examples | what it represents |
|---|---|---|
| `DUTY` | `Minimum Duty`, `Minimumduty.` | The duty calculated for this line |
| `TAX` | `VAT`, `TAX` | Tax on `target` = `product` / `shipping` / `handling` / `insurance` / `duty` (tax-on-tax) |

Each `TAX` entry typically also carries `rate` (e.g. `0.130000`) and `target` (the base it
was calculated on). See `SampleBulkResponse` and `SampleGlobalComplianceResponse` in the
[Examples](#examples) section.

### 2. Basket-level: `LandedCostModel.costLines[]` and `GCQuote.costLines[]` and `LandedQuoteModel.costLines[]`

Aggregated, basket/transaction-level cost components for the entire basket / destination,
**plus** other country-specific transaction-level charges. When an Incoterm is provided, this
array also includes logistics cost components for each `CostComponentCode` payable by the
priced party.

Observed `type` values at the basket level:

| `type` | `name` examples | what it represents | when present |
|---|---|---|---|
| `DUTY` | `Minimum Duty` | Aggregate duty payable for the basket | Always (when applicable) |
| `TAX` | `VAT` | Aggregate tax payable for the basket | Always (when applicable) |
| **`CCF`** | _destination-specific basket fee names from reference data_ | **Eligible EU inbound administrative import / customs clearance fee.** Sourced from reference data; threshold formulas evaluate against `TOTAL_PRICE` (and currency) | **Only when `administrative_fee=true` was sent** in the basket-level `parameters` and the destination has a configured CCF fee (and any `TOTAL_PRICE`-based threshold is met). Without `administrative_fee=true`, no `CCF` cost line is emitted |
| `FEE` | various | Other transaction-level fee types | Country-specific |
| `CIF`, `FOB`, `DDP`, `EXW`, `FCA`, `FAS`, `CFR`, `CPT`, `CIP`, `DAP`, `DPU` (Incoterm names) | Logistics cost code (`INTERNATIONAL_FREIGHT`, `INSURANCE`, `EXPORT_PACKAGING`, `BROKER_CLEARANCE_DUTIES`, etc.) | Logistics cost element broken out per Incoterm rules. `responsibleParty` (`BUYER`/`SELLER`), `payableByPricedParty`, and `status` (`PROVIDED`/`MISSING`) are populated | Only when `incoterm` is present on the basket. `MISSING` means no value was provided in the request and the component defaulted to 0 |

> **Spec note.** The OpenAPI document only enumerates `DUTY`, `TAX`, and the Incoterm-name
> family explicitly. The `CCF` value is documented in prose on `Basket.parameters`
> (`administrative_fee` description) but is not listed as an enum value on `CostComponentModel.type`;
> treat the `type` field as an open string and match by category.

Example basket-level `costLines[]` from the spec:

```json
[
  {"type": "DUTY", "name": "Minimum Duty", "value": 1.0, "currency": "USD"},
  {"type": "TAX",  "name": "VAT",          "value": 1.0, "currency": "USD"},
  {"type": "CIF",  "name": "INTERNATIONAL_FREIGHT", "value": 50.00, "currency": "USD",
   "responsibleParty": "SELLER", "payableByPricedParty": true, "status": "PROVIDED"},
  {"type": "CIF",  "name": "INSURANCE",            "value": 10.00, "currency": "USD",
   "responsibleParty": "SELLER", "payableByPricedParty": true, "status": "PROVIDED"}
]
```

---

## Quote types (`type` / `quoteType`)

Pricing strategy used when multiple tariff outcomes are possible (e.g. due to HS expansion).
Sent on requests as `Basket.type` / `BulkBasket.type`; echoed on responses as
`LandedCostModel.type` / `BulkLandedCostModel.type` / `GlobalComplianceResponseModel.quoteType`.

| value | meaning |
|---|---|
| `QUOTE_MINIMUM` | Lowest applicable duty across possible HS outcomes |
| `QUOTE_MAXIMUM` | Highest applicable duty across possible HS outcomes |
| `QUOTE_AVERAGE` | Average of possible duty outcomes |
| `QUOTE_MEDIAN` | Median value across possible duty outcomes |
| `QUOTE_ENHANCED10` | Selects the most probable fully expanded HS10 code and calculates duty exclusively using that HS10 (instead of MIN/MAX/AVG/MEDIAN aggregation) |
| `QUOTE_ENHANCEDMEDIAN` | Enhanced-median variant of the strategy. The OpenAPI spec lists this as a valid enum value but does not provide a separate textual description; treat as the median variant of the `QUOTE_ENHANCED10` family |

**`shipmentType`** (separate from `type`) — request-level enum on `BasketModelBase`:

| value | meaning |
|---|---|
| `postal_flat` | Postal flat-rate U.S. inbound calculation |
| `postal` | U.S. inbound postal duty (punitive-only — IEEPA / Section 122). Validation: `countryOfImport`/destination must be `US` for the EPC endpoint; legacy `postal_flat` is rejected with 422 on EPC. Case-insensitive at runtime |
| `courier` | Standard non-postal calculation (MFN, FTAs, punitives, CVD/ADD) |

---

## Examples

The OpenAPI document carries a number of wired examples. The two most useful for an EU
landed-cost integration are reproduced below.

### Example 1 — `globalCompliance` request (`SampleGlobalComplianceRequest`)

```json
{
  "b2b": false,
  "id": "1001",
  "companyId": 2000,
  "currency": "CAD",
  "type": "QUOTE_MINIMUM",
  "sellerCode": "ABC126",
  "restrictionsCheck": false,
  "shipFrom": {"country": "US"},
  "destinations": [
    {
      "taxRegistered": true,
      "shipTo": {
        "line1": "abc", "line2": "abc", "line3": "abc",
        "city": "Toronto", "country": "CA", "region": "ON", "postalCode": "L4t2t1",
        "latitude": "", "longitude": ""
      },
      "parameters": [
        {"name": "SHIPPING",  "value": "5", "unit": "USD"},
        {"name": "Handling",  "value": "5", "unit": "USD"},
        {"name": "INSURANCE", "value": "5", "unit": "USD"}
      ]
    },
    {
      "taxRegistered": true,
      "shipTo": {"country": "DE"},
      "parameters": [
        {"name": "SHIPPING",  "value": "3", "unit": "CAD"},
        {"name": "HANDLING",  "value": "8", "unit": "CAD"},
        {"name": "INSURANCE", "value": "3", "unit": "CAD"}
      ]
    }
  ],
  "lines": [
    {
      "lineNumber": 0,
      "classificationParameters": [
        {"name": "price", "value": 150, "unit": "GBP"},
        {"name": "preferential_program", "value": "PFDE"}
      ],
      "quantity": 2,
      "item": {
        "itemCode": "x5QkjK-EPpV:;5z35Y{{RF:f%VDiumSvy",
        "description": "{:=(@SQemk&F+/",
        "summary": "k*W9S9aF&-2mFr4_n*]eSc./Q]z",
        "itemGroup": "k*W9S9aF&-2mFr4_n*]eSc./Q]z",
        "classifications": [
          {"country": "CA", "hscode": "8906909900"},
          {"country": "US", "hscode": "111111"},
          {"country": "DE", "hscode": "9032900090"}
        ],
        "classificationParameters": [
          {"name": "coo",     "value": "CA", "unit": ""},
          {"name": "price",   "value": 75,   "unit": "GBP"},
          {"name": "hs_code", "value": "610910", "unit": ""}
        ]
      }
    },
    {
      "lineNumber": 1,
      "preferenceProgramApplicable": "false",
      "classificationParameters": [
        {"name": "price", "value": "300", "unit": "GBP"}
      ],
      "quantity": "2",
      "item": {
        "itemCode": 11,
        "description": "cottondress",
        "summary": "",
        "itemGroup": "Clothing>ForWomen>Dresses;Clothing>Girl>Dresse",
        "classifications": [{"country": "CA", "hscode": "111111"}],
        "classificationParameters": [
          {"name": "price",   "value": "150", "unit": "GBP"},
          {"name": "cooo",    "value": "CN",  "unit": ""},
          {"name": "hs_code", "value": "610910"}
        ]
      }
    }
  ]
}
```

### Example 2 — `globalCompliance` response (`SampleGlobalComplianceResponse`, abbreviated to the DE destination)

```json
{
  "b2b": false,
  "id": "1001",
  "currency": "CAD",
  "shipFrom": {"country": "US"},
  "quoteType": "QUOTE_MINIMUM",
  "globalCompliance": [
    {
      "shipTo": {"country": "DE"},
      "quote": {
        "lines": [
          {
            "number": 0,
            "quantity": 2,
            "itemCode": "x5QkjK-EPpV:;5z35Y{{RF:f%VDiumSvy",
            "classificationParameters": [
              {"name": "price", "value": "150", "unit": "GBP"},
              {"name": "preferential_program", "value": "PFDE"}
            ],
            "costLines": [
              {"type": "TAX",  "name": "TAX",         "value": 0.51,  "currency": "CAD", "rate": 0.19, "target": "handling"},
              {"type": "TAX",  "name": "TAX",         "value": 0.19,  "currency": "CAD", "rate": 0.19, "target": "insurance"},
              {"type": "TAX",  "name": "TAX",         "value": 1.45,  "currency": "CAD", "rate": 0.19, "target": "duty"},
              {"type": "TAX",  "name": "TAX",         "value": 50.72, "currency": "CAD", "rate": 0.19, "target": "product"},
              {"type": "DUTY", "name": "Minimumduty.","value": 7.61,  "currency": "CAD"},
              {"type": "TAX",  "name": "TAX",         "value": 0.19,  "currency": "CAD", "rate": 0.19, "target": "shipping"}
            ],
            "hsCode": "9032900090",
            "calculationSummary": {
              "dutyCalculationSummary": [
                {"name": "DUTY_DEMINIMIS_TOTAL_PRICE",        "value": "800.92", "unit": "CAD"},
                {"name": "DUTY_DEMINIMIS_THRESHOLD_EXCHANGE_RATE", "value": "1.496104767860", "unit": ""},
                {"name": "DUTY_DEMINIMIS_THRESHOLD_CURRENCY", "value": "EUR",    "unit": ""},
                {"name": "DUTY_DEMINIMIS_ORIGINAL_THRESHOLD", "value": "150.00", "unit": "EUR"},
                {"name": "DUTY_DEMINIMIS_THRESHOLD",          "value": "224.42", "unit": "CAD"},
                {"name": "CIF",                               "value": "271.64", "unit": "CAD"},
                {"name": "RATE",                              "value": "0.028",  "unit": "PERCENTAGE"},
                {"name": "TARIFF_TYPE",                       "value": "STANDARD","unit": ""},
                {"name": "DUTY_DEMINIMIS_APPLIED",            "value": "false",  "unit": ""}
              ],
              "taxCalculationSummary": [
                {"name": "IS_TAX_REGISTERED",   "value": "true",   "unit": ""},
                {"name": "INSURANCE",           "value": "1.00",   "unit": "CAD"},
                {"name": "PERCENTAGE",          "value": "0.19",   "unit": ""},
                {"name": "TAX_DEMINIMIS_APPLIED","value": "false", "unit": ""},
                {"name": "PRICE",               "value": "266.97", "unit": "CAD"},
                {"name": "SHIPPING",            "value": "1.00",   "unit": "CAD"},
                {"name": "DUTY",                "value": "7.61",   "unit": "CAD"},
                {"name": "HANDLING",            "value": "2.67",   "unit": "CAD"}
              ]
            }
          }
        ]
      }
    }
  ]
}
```

### Example 3 — Tariff-trade-library `EnhanceProductComplianceRequest` (FTA preference matched)

```json
{
  "id": "epc-doc-fta-ca",
  "countryOfExport": "US",
  "countryOfImport": "AU",
  "countryOfManufacture": "CA",
  "hscode": "4802699082",
  "preferenceProgramApplicable": true,
  "ftaName": "ca",
  "startDate": "2026-04-23",
  "endDate":   "2026-04-23"
}
```

### Example 4 — Tariff-trade-library response (FTA preference matched, single snapshot)

```json
[
  {
    "id": "epc-doc-fta-ca",
    "countryOfExport": "US",
    "countryOfImport": "AU",
    "countryOfManufacture": "CA",
    "hscode": "4802699082",
    "effectiveDate": "2026-04-23",
    "restrictions": [],
    "hasRestrictions": true,
    "hasPGA": false,
    "duty": {
      "calculationBasis": "CIF",
      "mfn": {"rate": "0.05", "uom": "Percentage", "currency": ""},
      "hasPunitiveRate": false,
      "hasFTARate": true,
      "ftaRates": [
        {"ftaName": "ca",    "ftaRate": {"rate": "0.025", "uom": "Percentage", "currency": ""}},
        {"ftaName": "cptpp", "ftaRate": {"rate": "0.0",   "uom": "Percentage", "currency": ""}}
      ]
    },
    "hasCVD": false,
    "hasADD": false,
    "effectiveRate": 0.025
  }
]
```

> The Section 232 / IEEPA / Section 122 / U.S. inbound postal examples are reproduced
> verbatim in the spec at lines 753–1530. Reference the YAML directly when implementing
> Section 232 or postal-shipment logic; the request/response pairs there demonstrate the
> April 6, 2026 regime, the Section 122 era (2026-02-24 to 2026-04-05), the IEEPA era
> (pre-2026-02-24), the GB Annex I-A (25%) and Annex I-B (15%) reduced rates, the
> zero-metal exemption, the auto/vehicle filter, and U.S. inbound postal.

---

## Error model

All non-2xx responses are typed with [ErrorInfo](#errorinfo). The shape is:

```json
{
  "code":    "ModelStateInvalid",
  "target":  "HttpRequest",
  "message": "Bad JSON Request",
  "details": [
    {
      "code":        "InvalidCountry",
      "number":      125,
      "message":     "The country 'ZZ' is not a recognized country code.",
      "description": "Please use the `ListCountries` API to identify a list of ISO 3166 countries and codes.",
      "helpLink":    "http://developer.avalara.com/avatax/errors/EntityNotFoundError",
      "severity":    "ERROR"
    }
  ]
}
```

### Common documented error codes

| `code` | Documented `number` | Where it appears | Meaning |
|---|---|---|---|
| `AuthenticationException` | 30 | 401 on every endpoint | Unable to authenticate the user or the account |
| `ModelStateInvalid` | 70 | 400 on quote / bulk / globalcompliance | Invalid JSON object (malformed body) |
| `ValueRequiredError` | 5 | 422 | A required field is missing (e.g. `id`) |
| `InvalidCountry` | 125 | 422 | Country code is not a recognized ISO 3166 country code |
| `InvalidValue` | (not specified) | 422 on EPC | Generic invalid value. Used for `postal-shipment-non-us-import` (`'shipmentType postal is only supported when countryOfImport is US.'`) and for `ftaName` not matching any returned FTA |
| `InvalidRequestParameter` | 400 | 400 on EPC `tariff-trade-library/search` | Invalid `section232Parameters` (total > 100%, negative percentage, invalid `auto` value) |

### `target` values (on `ErrorInfo.target`)

`Unknown`, `HttpRequest`, `HttpRequestHeaders`, `IncorrectData`.

### `severity` values (on `ErrorDetail.severity`)

`Success`, `Warning`, `Error`, `Exception`.

> Severity casing in the spec is inconsistent: examples use both `Error`/`Exception` and the
> upper-cased `ERROR`. Treat the field as case-insensitive when matching.

### Documented EPC 400 examples

`section232-exceeds-100`, `section232-negative-percentage`, `section232-invalid-auto`,
`malformed-json` — see the [tariff-trade-library/search endpoint section](#post-apiv2compliancetariff-trade-librarysearch).

### Documented EPC 422 examples

`field-required`, `invalid-country`, `postal-shipment-non-us-import`.

---

## Spec ambiguities & notes

The following points were noted while transcribing the spec; flag them when implementing.

1. **`CCF` cost-line `type` is not in any enum.** The OpenAPI spec describes
   `administrative_fee` and the resulting basket-level `CCF` cost lines in prose on
   `Basket.parameters`, but `CostComponentModel.type` declares only `DUTY` / `TAX` / Incoterm
   names in its examples; `CCF` is not enumerated. Treat `CostComponentModel.type` as an
   open string and match by category.

2. **`type` enum vs. `shipmentType` enum.** `BasketModelBase.type` (pricing strategy) and
   `BasketModelBase.shipmentType` are independent enums. `shipmentType` accepts
   `postal_flat`, `postal`, `courier` on basket schemas but only `postal`, `courier` on the
   EPC `EnhanceProductComplianceRequest.shipmentType`; legacy `postal_flat` is **rejected**
   on the EPC endpoint with 422.

3. **`taxRegistered` interaction with `b2b`.** Both flags can affect de minimis behavior.
   The spec describes them independently; behavior when both are set is destination-specific
   and not formally specified.

4. **Bearer auth not attached to operations.** `bearerAuth` is declared in
   `securitySchemes` but not referenced in any path-level `security` block. The spec only
   requires `basicAuth`. Bearer is platform-supported but not advertised at the OpenAPI
   level.

5. **`GET /api/v2/countries` has no declared `security` block.** Every other endpoint
   declares `basicAuth`. Treat the countries endpoint as subject to platform policy rather
   than assuming it is anonymous.

6. **`severity` casing inconsistency.** The schema lists `Success`, `Warning`, `Error`,
   `Exception`, but inline error examples use both `Error` and `ERROR`. Match
   case-insensitively.

7. **`preferenceProgramApplicable` in `SampleBulkRequest` / `SampleGlobalComplianceRequest`**
   is sent as a **string** (`"false"`) on `lineNumber: 1`, even though the schema declares it
   as `boolean`. The server appears to coerce. Prefer real booleans in new code.

8. **`storeMerchandiseTypes`** is declared on `BasketModelBase` but not enumerated; values
   are merchant-configured.

9. **`SampleBulkRequest` and `SampleGlobalComplianceRequest`** include several looser typings
   that don't strictly match the schema (e.g. `quantity` sent as the string `"2"` and
   `value` sent as a number rather than a string in `classificationParameters`). The
   server tolerates these in samples; new code should follow the schema (strings on
   `ItemParameterModel.value`, numbers on `BasketLineItemModel.quantity`).

10. **`Section232Parameters.auto` lives in the same object as the material map.** The schema
    uses `additionalProperties: Section232MaterialConfig` plus a `properties.auto` enum. In
    practice this means `auto` is a reserved key inside the `section232Parameters` object;
    everything else is a material name (`steel`, `aluminum`, `copper`, …).

11. **`PunitiveRate.notes` is explicitly **not stable**.** The spec states it is "useful for
    sales demos and audit logs but **not stable**, so do not parse." Use `rateLabel` (with
    prefix matching) and `effectiveRate` instead.

12. **`Duty.calculationBasis` examples vary** (`CIF`, `PRICE`, `QUANTITY`, `FOB`). The schema
    does not define an enum; treat as an open string.
