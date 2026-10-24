# Changelog

## v0.3 — Existing RestCommon framework integration

- Added a second Java generator mode for existing `com.restapitest`-style frameworks.
- Generated endpoint TestNG classes use a configurable `RestCommon` request-specification getter.
- Centralized endpoint constants, payload variants, status codes, response paths and safe extra headers.
- Added reusable `RestApiHelper` methods and a `testng.xml` class-entry snippet.
- Avoided generating or overwriting `pom.xml` or `RestCommon.java` in integration mode.
- Added integration notes explaining the supplied framework archive's missing Java source files and the assumed getter signature.
- Added unit tests for the new source-patch generator.


## v0.2 — API project generator

- Added a multi-file Maven project generator for RestAssured + TestNG.
- Added a reusable RequestSpecFactory helper and configurable base URI/endpoint.
- Added positive request verification, selected missing-field tests, optional missing-auth and malformed-JSON tests, and configurable non-null response JSON-path assertions.
- Added a generated test-design note and project README with environment-based setup instructions.
- Added a default skip guard; integration requests require explicit `-DrunApiTests=true`.
- Expanded best-effort redaction for Basic-auth inputs, sensitive headers, URL user-info, query-string credentials, and sensitive JSON string values.
- Added unit tests for project generation and secret handling.

## v0.1 — Initial portfolio prototype

- Requirements-to-test-case workflow with Markdown guidance input.
- Single-class cURL-to-RestAssured preview.
- Rule-based / optional AI-assisted failure triage with a demo review gate.
